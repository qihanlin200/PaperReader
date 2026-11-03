import signal
import sys
from pathlib import Path
from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from platformdirs import user_data_dir
from paperreader.services.instance import restart_previous
from paperreader.ui.window import Window


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PaperReader")
    root = Path(user_data_dir("PaperReader", appauthor=False))
    root.mkdir(parents=True, exist_ok=True)
    # Serialize startup across double-clicks. A second simultaneous launch is ignored.
    gate = QLockFile(str(root / "startup.lock"))
    gate.setStaleLockTime(30000)
    if not gate.tryLock(0):
        print("PaperReader 正在启动，忽略重复启动。")
        return 0
    try:
        restart_previous(Path(__file__).resolve().parent.parent)
        window = Window()
    except Exception as exc:
        gate.unlock()
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    window.show()
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
