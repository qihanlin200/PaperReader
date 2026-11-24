"""Run each unittest in its own process with a hard per-case timeout."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS = ROOT / 'tests'
VISUAL_CASES = frozenset({
    'test_theme_color_and_animation_stop',
    'test_note_edit_and_preview_buttons_share_the_report_layout',
    'test_create_group_dialog_has_wider_input',
    'test_read_button_matches_mode_selector_height_in_every_theme',
    'test_scrollbar_reveal_hides_whole_bar_without_changing_layout',
    'test_heading_is_one_line_and_editors_are_taller',
    'test_short_window_scroll_reaches_bottom_and_shrinks_after_fold',
    'test_naruto_rail_art_is_distinct_and_theme_recolors_catalog',
})


def discover_cases(tests_dir):
    """Read test IDs without importing Qt or executing test module top-level code."""
    for path in sorted(tests_dir.glob('test_*.py')):
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(path))
        qt = 'QApplication' in source
        for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for method in (node for node in cls.body
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and node.name.startswith('test_')):
                yield f'{path.stem}.{cls.name}.{method.name}', qt, method.name in VISUAL_CASES


def stop_process_tree(process):
    """End a timed-out test and any workers it started."""
    if os.name == 'nt':
        import psutil
        try:
            parent = psutil.Process(process.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except psutil.NoSuchProcess:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.communicate()


def run_case(name, timeout, env):
    command = [sys.executable, '-m', 'unittest', name]
    start = time.monotonic()
    process = subprocess.Popen(command, cwd=ROOT, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, start_new_session=os.name != 'nt')
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_process_tree(process)
        return 'TIMEOUT', time.monotonic() - start, ''
    return ('PASS' if process.returncode == 0 else 'FAIL',
            time.monotonic() - start, output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=20,
                        help='Seconds allowed for each case (default: 20)')
    parser.add_argument('--jobs', type=int, default=2,
                        help='Number of isolated cases to run at once (default: 2)')
    parser.add_argument('--suite', choices=('fast', 'qt', 'visual', 'all'), default='fast',
                        help='Case group to run when no IDs are given (default: fast)')
    parser.add_argument('--list', action='store_true', help='List selected cases without running them')
    parser.add_argument('--tests-dir', type=Path, default=DEFAULT_TESTS,
                        help=argparse.SUPPRESS)
    parser.add_argument('tests', nargs='*', help='Optional unittest case IDs')
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    if args.jobs <= 0:
        parser.error('--jobs must be positive')

    tests_dir = args.tests_dir.resolve()
    env = os.environ.copy()
    env.setdefault('QT_QPA_PLATFORM', 'offscreen')
    env['PYTHONPATH'] = os.pathsep.join(filter(None, (
        str(ROOT), str(tests_dir), env.get('PYTHONPATH', ''))))
    inventory = list(discover_cases(tests_dir))
    if args.tests:
        names = [name for name, _, _ in inventory if any(
            name == requested or name.startswith(requested + '.') for requested in args.tests)]
        missing = [requested for requested in args.tests if not any(
            name == requested or name.startswith(requested + '.') for name, _, _ in inventory)]
        if missing:
            parser.error('unknown test ID: ' + ', '.join(missing))
    else:
        names = [name for name, qt, visual in inventory
                 if (args.suite == 'all' or
                     (args.suite == 'fast' and not qt) or
                     (args.suite == 'qt' and qt and not visual) or
                     (args.suite == 'visual' and visual))]
    if not names:
        print('No test cases found.', file=sys.stderr)
        return 2
    if args.list:
        print('\n'.join(names))
        print(f'{len(names)} cases selected.')
        return 0

    counts = {'PASS': 0, 'FAIL': 0, 'TIMEOUT': 0}
    durations = []
    remaining = iter(names)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        pending = {}

        def submit_next():
            name = next(remaining, None)
            if name is None:
                return
            print(f'RUN     {name}', flush=True)
            pending[pool.submit(run_case, name, args.timeout, env)] = name

        for _ in range(min(args.jobs, len(names))):
            submit_next()
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                name = pending.pop(future)
                status, elapsed, output = future.result()
                counts[status] += 1
                durations.append((elapsed, name))
                print(f'{status:7} {elapsed:6.2f}s  {name}', flush=True)
                if status == 'FAIL':
                    print(output[-6000:].rstrip(), flush=True)
                elif status == 'TIMEOUT':
                    print(f'        exceeded {args.timeout:g}s; process stopped', flush=True)
                submit_next()
    print(f"Results: {counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['TIMEOUT']} timed out ({len(names)} cases).")
    print('Slowest: ' + ', '.join(f'{name} {elapsed:.2f}s'
                               for elapsed, name in sorted(durations, reverse=True)[:5]))
    return 1 if counts['FAIL'] or counts['TIMEOUT'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
