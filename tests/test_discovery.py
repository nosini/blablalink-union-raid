# SPDX-License-Identifier: AGPL-3.0-or-later

from http.cookiejar import Cookie
import sys
import types
import unittest
from unittest import mock

from blablalink_union_raid.cli import clean_token, season_name
from blablalink_union_raid.api import ApiError, Client, browser_cookies


def cookie(name):
    return Cookie(0, name, "v", None, False, ".blablalink.com", True, True,
                  "/", True, True, None, False, None, None, {})


class FakeClient(Client):
    def __init__(self, card):
        self.card = card
        self.sent = []

    def call(self, endpoint, params):
        self.sent.append((endpoint, params))
        if endpoint == "GetMyGuildInfo":
            return {"code": 0, "data": {"card": self.card}}
        return {"code": 0}


class DiscoveryTest(unittest.TestCase):
    def test_finds_union_and_openid(self):
        client = FakeClient({"guild_id": 42, "nikke_area_id": 84,
                             "intl_open_id": "29080-777"})
        client.current_season()
        self.assertEqual(client.sent[1][1], {
            "guild_id": "42", "nikke_area_id": 84, "intl_open_id": "777"})

    def test_openid_is_left_out_when_unknown(self):
        client = FakeClient({"guild_id": 42, "nikke_area_id": 84})
        client.current_season()
        self.assertNotIn("intl_open_id", client.sent[1][1])

    def test_given_values_win(self):
        client = FakeClient({"guild_id": 42, "nikke_area_id": 84})
        client.past_season("7", 9, "S1")
        self.assertEqual([e for e, _ in client.sent],
                         ["GetUnionRaidDataOfGuildSeason",
                          "GetUnionRaidLevelDataOfGuildSeason"])

    def test_no_union(self):
        with self.assertRaises(ApiError):
            FakeClient(None).current_season()


class BrowserCookiesTest(unittest.TestCase):
    def load(self, cookies):
        module = types.ModuleType("gallery_dl.cookies")
        module.load_cookies = mock.Mock(return_value=cookies)
        with mock.patch.dict(sys.modules, {
                "gallery_dl": types.ModuleType("gallery_dl"),
                "gallery_dl.cookies": module}):
            return browser_cookies("brave+kwallet:Profile 1"), module

    def test_list_becomes_a_jar(self):
        jar, module = self.load([cookie("a"), cookie("b")])
        self.assertTrue(hasattr(jar, "add_cookie_header"))
        self.assertEqual(len(jar), 2)
        module.load_cookies.assert_called_once_with(
            ("brave", "Profile 1", "kwallet", None, ".blablalink.com"))

    def test_nothing_decrypted(self):
        with self.assertRaises(ApiError):
            self.load([])


class TokenTest(unittest.TestCase):
    def test_paste_framing_is_removed(self):
        self.assertEqual(clean_token("\x1b[200~abc+/=\x1b[201~\n"), "abc+/=")

    def test_bad_tokens(self):
        for bad in (None, "", "  ", "a b", "a\x07b", "a\x1b[Ab"):
            with self.assertRaises(SystemExit):
                clean_token(bad)


class SeasonNameTest(unittest.TestCase):
    def test_name_comes_from_the_season_id(self):
        self.assertEqual(season_name("1000046"), "S46")
        self.assertEqual(season_name("1000009"), "S9")
        for other in ("", "46", "abc", "1000000"):
            self.assertIsNone(season_name(other))


if __name__ == "__main__":
    unittest.main()
