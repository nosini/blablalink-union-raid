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

    def test_json_for_the_bot(self):
        self.put("2026-09", "season.json")
        self.put("2026-10", "season2.json")
        status, text = self.call("GET", "/seasons?format=json", "r-token")
        self.assertEqual([s["name"] for s in json.loads(text)],
                         ["2026-09", "2026-10"])
        report = json.loads(self.call(
            "GET", "/report?format=json&member=bob", "r-token")[1])
        self.assertEqual(report["season"], "2026-10")
        self.assertEqual(report["compared_with"], "2026-09")
        self.assertEqual([m["member"] for m in report["members"]], ["Bob"])
        self.assertEqual(report["members"][0]["previous"]["status"], "up 2")
        before = {m["member"]: m for m in report["previous_members"]}
        self.assertEqual(before["Alice"]["days"]["1"]["total"], 2_900_000_000)
        self.assertNotIn("squad", json.dumps(report["previous_members"]))
        changes = json.loads(self.call(
            "GET", "/compare?format=json", "r-token")[1])
        self.assertEqual((changes["from"], changes["to"]),
                         ("2026-09", "2026-10"))
        self.assertEqual(self.call(
            "GET", "/report?format=json&season=nope", "r-token")[0], 404)
        self.assertEqual(self.call(
            "GET", "/report?format=json", None)[0], 401)

    def test_history_for_the_bot(self):
        self.put("S45", "season.json")
        self.put("S46", "season2.json")
        status, text = self.call("GET", "/history", "r-token")
        self.assertEqual(status, 200)
        seasons = json.loads(text)["seasons"]
        self.assertEqual([s["name"] for s in seasons], ["S45", "S46"])
        alice = {m["member"]: m for m in seasons[0]["members"]}["Alice"]
        self.assertEqual(alice["days"]["1"]["total"], 2_900_000_000)
        self.assertNotIn("squad", text)
        self.assertEqual(self.call("GET", "/history", "w-token")[0], 401)
        self.assertEqual(self.call("GET", "/history", None)[0], 401)

    def test_empty_data_is_never_stored(self):
        empty = json.dumps({"GetUnionRaidData": {
            "code": 0, "data": {"participate_data": []}}}).encode()
        self.put("S1", "season.json")
        status, text = self.call("PUT", "/seasons/S1", "w-token", empty)
        self.assertEqual(status, 422)
        self.assertEqual(self.call("PUT", "/seasons/S2", "w-token", empty)[0],
                         422)
        listing = self.call("GET", "/seasons", "r-token")[1]
        self.assertIn("S1  ", listing)
        self.assertIn("3 members", listing)  # S1 is intact
        self.assertNotIn("S2", listing)

    def test_a_much_smaller_push_needs_force(self):
        self.put("S1", "season.json")           # 9 runs
        few = json.loads((FIXTURES / "season.json").read_text())
        rows = None
        for key in ("GetUnionRaidData", "GetUnionRaidDataOfGuildSeason"):
            if key in few:
                rows = few[key]["data"]["participate_data"]
        if rows is None:
            rows = few["data"]["participate_data"]
        del rows[2:]                             # keep 2 of the runs
        body = json.dumps(few).encode()
        self.assertEqual(self.call("PUT", "/seasons/S1", "w-token", body)[0],
                         409)
        self.assertEqual(self.call(
            "PUT", "/seasons/S1?force=1", "w-token", body)[0], 200)

    def test_growing_or_equal_pushes_are_fine(self):
        self.assertEqual(self.put("S1", "season.json")[0], 200)
        self.assertEqual(self.put("S1", "season.json")[0], 200)

    def test_delete_needs_the_write_token(self):
        self.put("old", "season.json")
        self.assertEqual(self.call("DELETE", "/seasons/old", "r-token")[0], 401)
        self.assertEqual(self.call("DELETE", "/seasons/old", None)[0], 401)
        self.assertEqual(self.call("DELETE", "/seasons/old", "w-token")[0], 200)
        self.assertEqual(self.call("DELETE", "/seasons/old", "w-token")[0], 404)
        self.assertEqual(self.call("GET", "/seasons", "r-token")[1].strip(),
                         "no seasons")

    def test_rejects_junk(self):
        self.assertEqual(self.call("PUT", "/seasons/x", "w-token", b"{}")[0], 400)
        self.assertEqual(self.call("PUT", "/seasons/x", "w-token", b"no")[0], 400)
        self.assertEqual(
            self.call("PUT", "/seasons/a%2Fb", "w-token", b"{}")[0], 400)


if __name__ == "__main__":
    unittest.main()
