# SPDX-License-Identifier: AGPL-3.0-or-later

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from blablalink_union_raid.history import Store
from blablalink_union_raid.server import make_handler

FIXTURES = Path(__file__).parent / "fixtures"


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        store = Store(Path(self.dir.name) / "h.sqlite3")
        store.db.close()
        import sqlite3
        store.db = sqlite3.connect(store.path, check_same_thread=False)
        handler = make_handler(store, threading.Lock(), "w-token", "r-token")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_port}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.dir.cleanup()

    def call(self, method, path, token=None, data=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(
            self.base + path, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def put(self, name, fixture, token="w-token"):
        return self.call("PUT", f"/seasons/{name}", token,
                         (FIXTURES / fixture).read_bytes())

    def test_tokens_are_separate(self):
        self.assertEqual(self.put("s1", "season.json", None)[0], 401)
        self.assertEqual(self.put("s1", "season.json", "r-token")[0], 401)
        self.assertEqual(self.call("GET", "/seasons", "w-token")[0], 401)
        self.assertEqual(self.call("GET", "/seasons")[0], 401)

    def test_push_then_read(self):
        self.assertEqual(self.put("2026-09", "season.json")[0], 200)
        self.assertEqual(self.put("2026-10", "season2.json")[0], 200)
        status, text = self.call("GET", "/seasons", "r-token")
        self.assertEqual(status, 200)
        self.assertIn("2026-10", text)
        self.assertEqual(self.call("GET", "/report?day=1", "r-token")[0], 200)
        status, text = self.call("GET", "/compare", "r-token")
        self.assertEqual(status, 200)
        self.assertIn("2026-09 -> 2026-10", text)
        self.assertEqual(
            self.call("GET", "/report?season=nope", "r-token")[0], 404)

    def test_rejects_junk(self):
        self.assertEqual(self.call("PUT", "/seasons/x", "w-token", b"{}")[0], 400)
        self.assertEqual(self.call("PUT", "/seasons/x", "w-token", b"no")[0], 400)
        self.assertEqual(
            self.call("PUT", "/seasons/a%2Fb", "w-token", b"{}")[0], 400)


if __name__ == "__main__":
    unittest.main()
