"""Background Qt job wrapper."""
from PySide6.QtCore import QObject, QRunnable, Signal
from paperreader.logger import get_logger
log = get_logger(__name__)

class Signals(QObject):
    done = Signal(object)
    error = Signal(str)
    chunk = Signal(str)


class Job(QRunnable):
    def __init__(self, fn, streaming=False):
        super().__init__(); self.fn = fn; self.streaming = streaming; self.signals = Signals()

    def run(self):
        try:
            self.signals.done.emit(self.fn(self.signals.chunk.emit) if self.streaming else self.fn())
        except Exception as exc:
            log.error("后台任务失败：{}", type(exc).__name__, exc_info=True)
            self.signals.error.emit(str(exc))
