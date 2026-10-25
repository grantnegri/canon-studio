import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import server


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.http.server_address[1]
        cls.patches = [patch.object(server, 'PORT', cls.port),
                       patch.object(server, 'CAPTURES', Path(cls.directory.name)),
                       patch.object(server, 'camera_on', return_value=False)]
        for item in cls.patches: item.start()
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()
        for item in reversed(cls.patches): item.stop()
        cls.directory.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_cross_origin_mutation_is_rejected(self):
        status, _, _ = self.request('POST', '/api/snapshot', '{}',
                                   {'X-Camera-Studio':'1', 'Origin':'https://example.com'})
        self.assertEqual(status, 403)

    def test_post_requires_custom_header(self):
        status, _, _ = self.request('POST', '/api/snapshot', '{}')
        self.assertEqual(status, 403)

    def test_non_object_json_is_rejected(self):
        status, _, _ = self.request('POST', '/api/focus', '[]', {'X-Camera-Studio':'1'})
        self.assertEqual(status, 400)

    def test_negative_content_length_is_rejected(self):
        status, _, _ = self.request('POST', '/api/focus', '',
                                   {'X-Camera-Studio':'1','Content-Length':'-1'})
        self.assertEqual(status, 400)

    def test_dns_rebinding_host_is_rejected(self):
        status, _, _ = self.request('GET', '/api/status', headers={'Host':'example.com'})
        self.assertEqual(status, 403)

    def test_video_byte_ranges_for_playback(self):
        path = server.CAPTURES/'fixture.mp4'
        path.write_bytes(b'0123456789')
        status, headers, body = self.request('GET','/captures/fixture.mp4',headers={'Range':'bytes=3-6'})
        self.assertEqual((status,body), (206,b'3456'))
        self.assertEqual(headers['Content-Range'],'bytes 3-6/10')

    def test_snapshot_saves_latest_frame_in_capture_directory(self):
        with patch.object(server,'frame',b'test-jpeg'), patch.object(server,'frame_time',time.monotonic()):
            status, _, body = self.request('POST','/api/snapshot','{}',{'X-Camera-Studio':'1'})
        self.assertEqual(status,200)
        self.assertTrue(json.loads(body)['ok'])
        photos = list(server.CAPTURES.glob('Photo-*.jpg'))
        self.assertEqual(len(photos),1)
        self.assertEqual(photos[0].read_bytes(),b'test-jpeg')


if __name__ == '__main__':
    unittest.main()
