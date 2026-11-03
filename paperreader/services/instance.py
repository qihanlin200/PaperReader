"""Restart only Python module instances belonging to this checkout."""
import os
from pathlib import Path
import psutil


def is_reader_process(process, project):
    try:
        args = process.cmdline()
        # Exact module invocation, not substring searches that can match editors/tests.
        module = any(args[i:i+2] == ['-m', 'paperreader'] for i in range(1, len(args)-1))
        executable = Path(process.exe()).name.lower()
        return (process.pid != os.getpid() and module
                and executable.startswith('python')
                and Path(process.cwd()).resolve() == Path(project).resolve())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def restart_previous(project, timeout=3):
    previous = [p for p in psutil.process_iter() if is_reader_process(p, project)]
    for process in previous:
        try: process.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(previous, timeout=timeout)
    for process in alive:
        try: process.kill()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(alive, timeout=2)
    if alive:
        raise RuntimeError('已有 PaperReader 进程无法退出，未启动新实例。')
