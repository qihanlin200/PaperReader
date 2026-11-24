"""PaperReader diagnostics: brace-style logging, bounded local files, and export."""

import logging
import re
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock


DEFAULT_SIZE_MB = 10
DEFAULT_RETENTION_DAYS = 14
_FORMAT = "%(asctime)s %(levelname)s %(filename)s:%(lineno)d %(message)s"
_file_handler = None
_log_dir = None
_configuration_lock = RLock()
_QUERY_SECRET = re.compile(r"(?i)([?&](?:api[_-]?key|access_token|token|signature|sig|secret|password)=)[^&\s]+")
_BEARER_SECRET = re.compile(r"(?i)(Bearer\s+)[^\s]+")


class _LineFormatter(logging.Formatter):
    def format(self, record):
        message = _BEARER_SECRET.sub(r"\1[redacted]", super().format(record))
        lines = _QUERY_SECRET.sub(r"\1[redacted]", message).splitlines()
        if len(lines) <= 1:
            return lines[0] if lines else ""
        prefix = (f"{self.formatTime(record, self.datefmt)} {record.levelname} "
                  f"{record.filename}:{record.lineno} ")
        return "\n".join([lines[0]] + [prefix + line for line in lines[1:]])


def limits(size_mb=DEFAULT_SIZE_MB, retention_days=DEFAULT_RETENTION_DAYS):
    if type(size_mb) is not int or not 1 <= size_mb <= 100:
        raise ValueError("日志大小须为 1–100 MB。")
    if type(retention_days) is not int or not 1 <= retention_days <= 90:
        raise ValueError("日志保留周期须为 1–90 天。")
    return size_mb, retention_days


class _BraceLogger:
    def __init__(self, name):
        self.logger = logging.getLogger(name)

    def _write(self, level, message, *args, exc_info=False):
        if self.logger.isEnabledFor(level):
            rendered = message.format(*args) if args else message
            self.logger.log(level, rendered, exc_info=exc_info, stacklevel=3)

    def debug(self, message, *args, exc_info=False):
        self._write(logging.DEBUG, message, *args, exc_info=exc_info)

    def info(self, message, *args, exc_info=False):
        self._write(logging.INFO, message, *args, exc_info=exc_info)

    def warning(self, message, *args, exc_info=False):
        self._write(logging.WARNING, message, *args, exc_info=exc_info)

    def error(self, message, *args, exc_info=False):
        self._write(logging.ERROR, message, *args, exc_info=exc_info)


def get_logger(name):
    return _BraceLogger(name)


def preview(value, limit=600):
    """Bound diagnostic values so a model response cannot flood the terminal."""
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + f"…（共 {len(text)} 字符）"


def response_size(response):
    """Read optional buffered response size without changing request behavior."""
    try:
        content = response.content
    except (AttributeError, RuntimeError):
        return "未知"
    return len(content) if isinstance(content, (bytes, str)) else "未知"


class _BoundedFileHandler(logging.Handler):
    def __init__(self, directory, size_mb, retention_days):
        super().__init__(logging.WARNING)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_bytes = size_mb * 1024 * 1024
        self.retention_days = retention_days
        self.active = self.directory / "paperreader.log"
        self._prune()

    def _files(self):
        return [path for path in self.directory.glob("paperreader*.log") if path.is_file()]

    def _prune(self):
        cutoff = datetime.now().timestamp() - timedelta(days=self.retention_days).total_seconds()
        for path in self._files():
            if path.stat().st_mtime < cutoff:
                path.unlink()
        files = sorted(self._files(), key=lambda path: path.stat().st_mtime)
        total = sum(path.stat().st_size for path in files)
        for path in files:
            if total <= self.max_bytes:
                break
            size = path.stat().st_size
            path.unlink()
            total -= size

    def _rotate(self):
        if self.active.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            self.active.replace(self.directory / f"paperreader-{stamp}.log")

    def emit(self, record):
        try:
            data = (self.format(record) + "\n").encode("utf-8", errors="replace")
            file_limit = min(2 * 1024 * 1024, max(1, self.max_bytes // 2))
            if len(data) > file_limit:
                data = data[:file_limit - 16].decode("utf-8", errors="ignore").encode("utf-8") + b" [truncated]\n"
            if self.active.exists():
                changed_day = datetime.fromtimestamp(self.active.stat().st_mtime).date() != datetime.now().date()
                if changed_day or self.active.stat().st_size + len(data) > file_limit:
                    self._rotate()
            with self.active.open("ab") as stream:
                stream.write(data)
            self._prune()
        except OSError:
            self.handleError(record)


def configure_logging(root, *, size_mb=DEFAULT_SIZE_MB, retention_days=DEFAULT_RETENTION_DAYS):
    """Console records all levels; local files retain warning and error only."""
    global _file_handler, _log_dir
    size_mb, retention_days = limits(size_mb, retention_days)
    with _configuration_lock:
        logger = logging.getLogger("paperreader")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        for handler in list(logger.handlers):
            if getattr(handler, "_paperreader_handler", False):
                logger.removeHandler(handler)
                handler.close()
        formatter = _LineFormatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
        if sys.stderr is not None:
            console = logging.StreamHandler(sys.stderr)
            console.setLevel(logging.DEBUG)
            console.setFormatter(formatter)
            console._paperreader_handler = True
            logger.addHandler(console)
        _log_dir = Path(root) / "logger"
        _file_handler = _BoundedFileHandler(_log_dir, size_mb, retention_days)
        _file_handler.setFormatter(formatter)
        _file_handler._paperreader_handler = True
        logger.addHandler(_file_handler)
        return _log_dir


def shutdown_logging():
    global _file_handler, _log_dir
    with _configuration_lock:
        logger = logging.getLogger("paperreader")
        for handler in list(logger.handlers):
            if getattr(handler, "_paperreader_handler", False):
                logger.removeHandler(handler)
                handler.close()
        _file_handler = None
        _log_dir = None


def export_logs(destination):
    """Write all currently retained logs to a ZIP archive."""
    if _file_handler is None:
        raise RuntimeError("日志系统尚未初始化。")
    destination = Path(destination)
    with _configuration_lock:
        _file_handler.acquire()
        try:
            _file_handler._prune()
            files = sorted(_file_handler._files())
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in files:
                    archive.write(path, arcname=path.name)
        finally:
            _file_handler.release()
    return len(files)
