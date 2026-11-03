import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from paperreader.services.instance import is_reader_process, restart_previous


class InstanceTests(unittest.TestCase):
    def process(self, args=None, cwd=None):
        p = Mock()
        p.pid = os.getpid() + 1000
        p.cmdline.return_value = args or ['python', '-m', 'paperreader']
        p.exe.return_value = '/tmp/python3'
        p.cwd.return_value = cwd or str(Path.cwd())
        return p

    def test_only_exact_module_in_same_project(self):
        self.assertTrue(is_reader_process(self.process(), Path.cwd()))
        self.assertFalse(is_reader_process(self.process(['python', '-m', 'unittest']), Path.cwd()))
        self.assertFalse(is_reader_process(self.process(['python', '-c', 'import paperreader']), Path.cwd()))
        self.assertFalse(is_reader_process(self.process(cwd='/tmp'), Path.cwd()))
        p = self.process(); p.pid = os.getpid()
        self.assertFalse(is_reader_process(p, Path.cwd()))

    def test_terminate_then_force_kill_only_matching_process(self):
        old = self.process(); unrelated = self.process(['python', '-m', 'unittest'])
        with patch('paperreader.services.instance.psutil.process_iter', return_value=[old, unrelated]), patch('paperreader.services.instance.psutil.wait_procs', side_effect=[([], [old]), ([old], [])]):
            restart_previous(Path.cwd(), timeout=.01)
        old.terminate.assert_called_once(); old.kill.assert_called_once()
        unrelated.terminate.assert_not_called(); unrelated.kill.assert_not_called()

    def test_refuse_new_instance_when_old_stays_alive(self):
        old = self.process()
        with patch('paperreader.services.instance.psutil.process_iter', return_value=[old]), patch('paperreader.services.instance.psutil.wait_procs', return_value=([], [old])):
            with self.assertRaises(RuntimeError): restart_previous(Path.cwd(), timeout=.01)
