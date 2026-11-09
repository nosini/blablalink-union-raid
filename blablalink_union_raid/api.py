# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fetch Union Raid data from the blablalink.com API.

The data is protected: the request has to carry the login cookies of an
account in the union. Export them from a logged-in browser as a Netscape
cookies.txt file; they are only sent to api.blablalink.com.
"""

from http.cookiejar import CookieJar, MozillaCookieJar
import json
import urllib.request

API = "https://api.blablalink.com/api/game/proxy/Game"
NOT_LOGGED_IN = 300001


class ApiError(RuntimeError):
    pass


def short_openid(openid):
    """The website sends only the last part of '29080-123…' for the current season."""
    return openid.split("-")[-1]


DOMAIN = ".blablalink.com"


def browser_cookies(spec):
    """Cookies of blablalink.com from a browser's own cookie store.

    `spec` is NAME[+KEYRING][:PROFILE], e.g. "brave" or "brave:Profile 1".
    Uses gallery-dl's extractor (pip install gallery-dl), which also reads
    the browser's key from the desktop keyring for encrypted cookies.
    """
    try:
        from gallery_dl.cookies import load_cookies
    except ImportError:
        raise ApiError("--cookies-from-browser needs gallery-dl: "
                       "pip install gallery-dl") from None
    name, _, profile = spec.partition(":")
    name, _, keyring = name.partition("+")
    try:
        cookies = load_cookies((name, profile or None, keyring or None,
                                None, DOMAIN))
    except (ValueError, OSError, RuntimeError) as exc:
        raise ApiError(f"can't read cookies from {spec!r}: {exc}") from None
    # gallery-dl returns a list of cookies; cookies it couldn't decrypt are
    # left out of it.
    jar = CookieJar()
    for cookie in cookies:
        jar.set_cookie(cookie)
    if not len(jar):
        raise ApiError(f"{spec!r} gave no blablalink.com cookies: log in "
                       "there first, check the profile name, and see the "
                       "messages above (the browser's cookies may be "
                       "encrypted with a key from the desktop keyring)")
    return jar


class Client:
    def __init__(self, cookies_path=None, timeout=30, browser=None):
        if bool(cookies_path) == bool(browser):
            raise ApiError("give either a cookies file or a browser")
        if browser:
            self.jar = browser_cookies(browser)
        else:
            self.jar = MozillaCookieJar(cookies_path)
            self.jar.load(ignore_discard=True, ignore_expires=True)
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.timeout = timeout

    def call(self, endpoint, params):
        request = urllib.request.Request(
            f"{API}/{endpoint}", method="POST",
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json",
                     "Origin": "https://www.blablalink.com",
                     "Referer": "https://www.blablalink.com/"})
        with self.opener.open(request, timeout=self.timeout) as response:
            body = json.load(response)
        if body.get("code") == NOT_LOGGED_IN:
            raise ApiError("not logged in: the cookies are missing, expired "
                           "or not those of blablalink.com")
        if body.get("code"):
            raise ApiError(f"API error {body['code']}: {body.get('msg')}")
        return body

    def my_union(self):
        """(guild_id, area_id, openid or None) of the logged-in account.

        The website does the same: it reads the `card` of GetMyGuildInfo.
        The openid is only taken from there if the card carries one.
        """
        body = self.call("GetMyGuildInfo", {})
        card = (body.get("data") or {}).get("card")
        if not isinstance(card, dict) or not card.get("guild_id"):
            raise ApiError(
                f"couldn't find your union (API code {body.get('code')}: "
                f"{body.get('msg')}). Is this account in a union? Otherwise "
                f"give --guild-id and --area-id")
        openid = next((str(v) for k, v in card.items()
                       if v and k.lower().replace("_", "") in
                       ("openid", "intlopenid")), None)
        return str(card["guild_id"]), card.get("nikke_area_id"), openid

    def current_season(self, guild_id=None, area_id=None, openid=None):
        if not guild_id or not area_id:
            found_guild, found_area, found_openid = self.my_union()
            guild_id = guild_id or found_guild
            area_id = area_id or found_area
            openid = openid or found_openid
        params = {"guild_id": guild_id, "nikke_area_id": int(area_id)}
        if openid:
            params["intl_open_id"] = short_openid(openid)
        return {
            "GetUnionRaidData": self.call("GetUnionRaidData", params),
            "GetUnionRaidLevelInfo": self.call("GetUnionRaidLevelInfo", params),
        }

    def past_season(self, guild_id, area_id, season_id):
        if not guild_id or not area_id:
            found_guild, found_area, _ = self.my_union()
            guild_id = guild_id or found_guild
            area_id = area_id or found_area
        params = {"area_id": int(area_id), "guild_id": guild_id,
                  "season_id": str(season_id)}
        return {
            "GetUnionRaidDataOfGuildSeason":
                self.call("GetUnionRaidDataOfGuildSeason", params),
            "GetUnionRaidLevelDataOfGuildSeason":
                self.call("GetUnionRaidLevelDataOfGuildSeason", params),
        }
