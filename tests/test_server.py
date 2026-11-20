# SPDX-License-Identifier: AGPL-3.0-or-later

from http.server import ThreadingHTTPServer
import html
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from blablalink_union_raid import card, sheet
from blablalink_union_raid.history import Store
from blablalink_union_raid.server import make_handler

try:
    from PIL import Image
except ImportError:
    Image = None

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

    def fetch(self, path, token=None):
        """(status, body, headers) for the card routes, which take a token."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(self.base + path, headers=headers)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read(), response.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def public(self):
        return mock.patch.dict(os.environ, {"RAID_PUBLIC_CARD": "1"})

    def two_seasons(self):
        self.put("2026-09", "season.json")
        self.put("2026-10", "season2.json")

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

    def test_the_card_routes_need_the_read_token_by_default(self):
        """Only the bot reads them; a link preview needs RAID_PUBLIC_CARD."""
        self.two_seasons()
        self.assertEqual(self.call("GET", "/card")[0], 401)
        self.assertEqual(self.call("GET", "/card.png")[0], 401)
        self.assertEqual(self.call("GET", "/card", "r-token")[0], 200)
        self.assertEqual(self.call("GET", "/card", "w-token")[0], 401)
        status, body, headers = self.fetch("/card.png?season=2026-10",
                                           "r-token")
        if Image:
            self.assertEqual(status, 200)
            self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")

    def test_the_card_page_can_be_public(self):
        """With RAID_PUBLIC_CARD Discord's crawler, too, can read it."""
        self.two_seasons()
        with self.public():
            status, body, headers = self.fetch("/card")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"],
                             "text/html; charset=utf-8")
        page = body.decode()
        self.assertIn('<meta property="og:title"'
                      ' content="Union Raid · 2026-10 · day 2">', page)
        self.assertIn('<meta name="twitter:card"'
                      ' content="summary_large_image">', page)
        self.assertRegex(
            page, r'<meta property="og:image" '
                  r'content="https://[^"]+/card\.png\?chunk=0">')
        self.assertIn("discord:component-embed", page)
        page = self.call("GET", "/card?day=1", "r-token")[1]
        self.assertIn('<meta property="og:title"'
                      ' content="Union Raid · 2026-10 · day 1">', page)
        self.assertEqual(
            self.call("GET", "/card?season=2026-09", "r-token")[0], 200)
        self.assertEqual(
            self.call("GET", "/card?season=nope", "r-token")[0], 404)

    def test_the_card_compares_seasons(self):
        self.two_seasons()
        page = self.call("GET", "/card?from=2026-09&to=2026-10",
                         "r-token")[1]
        self.assertIn('content="Union Raid · 2026-09 → 2026-10', page)
        self.assertIn("Carol (was #2)", page)

    def test_card_errors(self):
        self.assertEqual(self.call("GET", "/card", "r-token")[0], 404)
        self.two_seasons()
        self.assertEqual(self.call("GET", "/card?day=x", "r-token")[0], 404)
        self.assertEqual(
            self.call("GET", "/card.png?chunk=x", "r-token")[0], 404)
        self.assertEqual(
            self.call("GET", "/card.png?chunk=99", "r-token")[0], 404)

    def test_the_card_images(self):
        self.two_seasons()
        status, body, headers = self.fetch("/card.png", "r-token")
        if Image:      # with Pillow the sheet is drawn
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "image/png")
            self.assertEqual(body[:8], b"\x89PNG\r\n\x1a\n")
            self.assertLess(len(body), 200 * 1024)
        else:          # without it the server says so, plainly
            self.assertEqual(status, 500)
        status, _, _ = self.fetch("/card.png?season=2026-09", "r-token")
        if Image:
            self.assertEqual(status, 200)

    def test_the_day_card_compares_with_the_day_before(self):
        """`day` goes to sheet.day only, or the report loses the other
        days and the change column has nothing to compare with."""
        self.two_seasons()
        data = json.loads(self.call(
            "GET", "/report?format=json&season=2026-10", "r-token")[1])
        footer = sheet.day(data, 2).footer
        self.assertIn("changes against day 1", footer)
        page = self.call("GET", "/card?season=2026-10&day=2", "r-token")[1]
        self.assertIn(html.escape(footer), page)

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_the_day_card_draws_the_full_report_sheet(self):
        self.two_seasons()
        data = json.loads(self.call(
            "GET", "/report?format=json&season=2026-10", "r-token")[1])
        drawn = card.png(sheet.day(data, 2))
        status, body, _ = self.fetch("/card.png?season=2026-10&day=2",
                                     "r-token")
        self.assertEqual(status, 200)
        self.assertEqual(body, drawn)

    def test_the_compare_json_carries_the_cache_buster(self):
        """The card link needs `v`; a compare has no single season time."""
        self.two_seasons()
        changes = json.loads(self.call(
            "GET", "/compare?format=json", "r-token")[1])
        seasons = {s["name"]: s["ingested_at"] for s in json.loads(
            self.call("GET", "/seasons?format=json", "r-token")[1])}
        self.assertEqual(changes["ingested_at"],
                         max(seasons["2026-09"], seasons["2026-10"]))

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_a_broken_font_answers_500_for_the_image_only(self):
        """The page still renders (without dimensions); the image says why."""
        self.two_seasons()
        with tempfile.NamedTemporaryFile() as bad:
            bad.write(b"not a font")
            bad.flush()
            with mock.patch.dict(os.environ, {"RAID_CARD_FONT": bad.name}):
                card._FONTS = None
                try:
                    status, body, _ = self.fetch("/card.png", "r-token")
                    self.assertEqual(status, 500)
                    self.assertIn(bad.name, body.decode())
                    status, page, _ = self.fetch("/card", "r-token")
                    self.assertEqual(status, 200)
                    page = page.decode()
                    self.assertIn("og:title", page)
                    self.assertNotIn("og:image:width", page)
                finally:
                    card._FONTS = None


if __name__ == "__main__":
    unittest.main()
