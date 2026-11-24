import time
_started = time.perf_counter()
if __name__ == "__main__":
    # Divert frozen worker processes before importing the Qt application.
    from multiprocessing import freeze_support
    freeze_support()
import signal
import sys
from pathlib import Path
from PySide6.QtCore import QLockFile, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon
from platformdirs import user_data_dir
from paperreader.services.instance import restart_previous
from paperreader.logger import configure_logging, get_logger, limits


log = get_logger(__name__)


def main():
    timings = {"imports": round(time.perf_counter() - _started, 3)}
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    timings["application"] = round(time.perf_counter() - _started, 3)
    app.setApplicationName("PaperReader")
    resource_root = Path(sys._MEIPASS) / "paperreader" if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    icon_path = resource_root / "assets" / "icon-1024.png"
    app.setWindowIcon(QIcon(str(icon_path)))
    if '--smoke-test' in sys.argv:
        from paperreader.ui.window import Window
        import tempfile
        import fitz
        from paperreader.services.library import Library
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            doc = fitz.open(); doc.new_page().insert_text((72,72), 'Bundled PDF preview')
            paper = library.import_pdf(doc.tobytes(), 'Smoke test'); doc.close()
            window = Window(library=library); window.show(); window.reload(paper['id'])
            window.summary.set_markdown(r"## Formula" + "\n\n" + r"\(x_i^2+\tau\)")
            check = QTimer()
            zoom_started = False
            def finish_smoke():
                nonlocal zoom_started
                pages = window.view.pages
                if not window.summary.math_resources or not pages or pages[0].bitmap is None:
                    return
                if not zoom_started:
                    window.view.zoom(1.05)
                    zoom_started = True
                elif pages[0].render_scale == window.view.scale:
                    app.exit(0 if not app.windowIcon().isNull() else 2)
            check.timeout.connect(finish_smoke); check.start(100)
            # A fresh CI runner may spend several seconds building Matplotlib's
            # font cache before the bundled window can render its first page.
            QTimer.singleShot(60000, lambda: app.exit(2))
            result = app.exec(); window.close(); library.db.close()
            return result
    root = Path(user_data_dir("PaperReader", appauthor=False))
    root.mkdir(parents=True, exist_ok=True)
    try:
        import json
        saved = json.loads((root / "config.json").read_text()) if (root / "config.json").exists() else {}
        size_mb, days = limits(saved.get("log_size_mb", 10), saved.get("log_retention_days", 14))
    except (OSError, ValueError, TypeError):
        size_mb, days = 10, 14
    configure_logging(root, size_mb=size_mb, retention_days=days)
    sys.excepthook = lambda kind, error, traceback: log.error(
        "未捕获的应用异常", exc_info=(kind, error, traceback))
    # Serialize startup across double-clicks. A second simultaneous launch is ignored.
    gate = QLockFile(str(root / "startup.lock"))
    gate.setStaleLockTime(30000)
    if not gate.tryLock(0):
        log.info("PaperReader 正在启动，忽略重复启动。")
        return 0
    try:
        restart_previous(Path(__file__).resolve().parent.parent)
        timings["previous_process"] = round(time.perf_counter() - _started, 3)
        from paperreader.ui.window import Window
        timings["window_imports"] = round(time.perf_counter() - _started, 3)
        window = Window()
        timings["window_ready"] = round(time.perf_counter() - _started, 3)
    except Exception as exc:
        log.error("应用启动失败", exc_info=True)
        gate.unlock()
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    window.show()
    def record_startup():
        import json
        timings["event_loop"] = round(time.perf_counter() - _started, 3)
        try:
            (root / "startup.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
        except OSError:
            pass
    QTimer.singleShot(0, record_startup)
    gate.unlock()
    # Give Python regular opportunities to dispatch SIGTERM while Qt owns the loop.
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(100)
    def terminate(signum, frame):
        window.save_notes()
        window.persist()
        app.quit()
    signal.signal(signal.SIGTERM, terminate)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
