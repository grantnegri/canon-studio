import time
import unittest
from camera_bridge import Bridge, Command


class FakeCamera:
    def __init__(self):
        self.calls = []
        self.fail_release = False
        self.mode = 'One Shot'

    def settings(self):
        return {'focusmode': {'value': self.mode}, 'afmethod': {'value': 'Live'},
                'whitebalance': {'readonly': False, 'choices': ['Auto', 'Daylight']}}

    def set(self, name, value):
        self.calls.append((name, value))
        if self.fail_release and (name, value) == ('autofocusdrive', 0):
            raise RuntimeError('USB unavailable')


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.camera = FakeCamera()
        self.bridge = Bridge(self.camera)

    def test_focus_releases_before_exposure_change(self):
        self.bridge.execute({'op': 'focus'})
        self.bridge.execute({'op': 'set', 'name': 'whitebalance', 'value': 'Daylight'})
        self.assertEqual(self.camera.calls, [('autofocusdrive', 1),
                         ('autofocusdrive', 0), ('whitebalance', 'Daylight')])
        self.assertFalse(self.bridge.auto['focusing'])

    def test_focus_releases_without_stopping_preview_loop(self):
        self.bridge.focus()
        self.bridge.focus_release_at = time.monotonic() - 1
        self.bridge.process()
        self.assertEqual(self.camera.calls[-1], ('autofocusdrive', 0))
        self.assertIsNone(self.bridge.focus_release_at)

    def test_failed_release_disables_repeats_without_retry_storm(self):
        self.bridge.execute({'op': 'auto', 'enabled': True, 'interval': 5})
        self.camera.fail_release = True
        self.bridge.focus_release_at = time.monotonic() - 1
        self.bridge.process()
        count = len(self.camera.calls)
        self.bridge.process()
        self.assertEqual(len(self.camera.calls), count)
        self.assertFalse(self.bridge.auto['enabled'])
        self.assertIn('release', self.bridge.auto['error'])

    def test_timed_out_queued_command_never_moves_lens(self):
        command = Command({'op': 'focus'})
        command.timeout()
        self.bridge.queue.put(command)
        self.bridge.process()
        self.assertFalse(command.result['ok'])
        self.assertEqual(self.camera.calls, [])

    def test_inflight_timeout_reports_uncertainty(self):
        command = Command({'op': 'focus'})
        self.assertTrue(command.begin())
        self.assertIn('still in progress', command.timeout()['error'])
        self.assertFalse(command.cancelled)

    def test_manual_lens_mode_requires_physical_switch(self):
        self.camera.mode = 'Manual'
        with self.assertRaisesRegex(ValueError, 'physical'):
            self.bridge.focus()
        self.assertEqual(self.camera.calls, [])

    def test_rejects_unknown_settings_and_unavailable_values(self):
        for payload in ({'op': 'set', 'name': 'ownername', 'value': 'x'},
                        {'op': 'set', 'name': 'whitebalance', 'value': 'unknown'}):
            with self.assertRaises(ValueError):
                self.bridge.execute(payload)
        self.assertEqual(self.camera.calls, [])

    def test_rejects_invalid_repeat_intervals(self):
        for interval in (0, 2, 61, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.bridge.execute({'op': 'auto', 'enabled': True, 'interval': interval})
        self.assertEqual(self.camera.calls, [])


if __name__ == '__main__':
    unittest.main()
