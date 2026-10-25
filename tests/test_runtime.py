from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from runtime import CameraRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.runtime = CameraRuntime('container', Path('/app'), Path(self.directory.name))
        self.proc = Mock(pid=1234)
        self.proc.poll.return_value = None
        self.popen = patch('runtime.subprocess.Popen', return_value=self.proc).start()
        self.killpg = patch('runtime.os.killpg').start()
        self.run = patch('runtime.subprocess.run').start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.runtime.close)

    def test_start_owns_group_and_log_without_systemd(self):
        self.assertFalse(self.runtime.active())
        self.runtime.start()
        self.assertTrue(self.runtime.active())
        self.popen.assert_called_once_with(
            ['bash', '/app/webcam.sh', 'stream'], stdin=subprocess.DEVNULL,
            stdout=self.runtime.log, stderr=self.runtime.log, start_new_session=True)
        self.assertEqual(Path(self.runtime.log.name).name, 'camera.log')
        self.run.assert_not_called()
        self.runtime.start()
        self.popen.assert_called_once()

    def test_stop_interrupts_group_waits_and_closes_log(self):
        self.runtime.start()
        log = self.runtime.log
        self.runtime.stop()
        self.killpg.assert_called_once_with(1234, signal.SIGINT)
        self.proc.wait.assert_called_once_with(timeout=10)
        self.assertTrue(log.closed)
        self.assertFalse(self.runtime.active())
        self.runtime.stop()
        self.killpg.assert_called_once()
        self.run.assert_not_called()

    def test_timeout_kills_whole_group(self):
        self.runtime.start()
        self.proc.wait.side_effect = [subprocess.TimeoutExpired('stream', 10), 0]
        self.runtime.close()
        self.assertEqual([call.args for call in self.killpg.call_args_list],
                         [(1234, signal.SIGINT), (1234, signal.SIGKILL)])
        self.assertEqual(self.proc.wait.call_count, 2)

    def test_process_exit_race_still_reaps(self):
        self.runtime.start()
        self.killpg.side_effect = ProcessLookupError
        self.runtime.stop()
        self.proc.wait.assert_called_once_with(timeout=10)

    def test_exited_feed_can_restart_and_closes_old_log(self):
        self.runtime.start()
        old_log = self.runtime.log
        self.proc.poll.return_value = 1
        self.assertFalse(self.runtime.active())
        self.runtime.start()
        self.assertTrue(old_log.closed)
        self.assertEqual(self.popen.call_count, 2)
        self.killpg.assert_not_called()

    def test_spawn_failure_releases_log(self):
        self.popen.side_effect = OSError('cannot spawn')
        with self.assertRaises(OSError):
            self.runtime.start()
        self.assertIsNone(self.runtime.log)
        self.assertFalse(self.runtime.active())

    def test_native_mode_retains_service_behavior_and_independent_lifetime(self):
        native = CameraRuntime('systemd', Path('/app'))
        self.run.return_value.returncode = 0
        self.assertTrue(native.active())
        native.start()
        native.stop()
        native.close()
        self.assertEqual([call.args[0] for call in self.run.call_args_list], [
            ['systemctl', '--user', 'is-active', '--quiet', 'canon-webcam.service'],
            ['bash', '/app/webcam.sh', 'start'], ['bash', '/app/webcam.sh', 'stop']])
        self.popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
