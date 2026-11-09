# SPDX-License-Identifier: AGPL-3.0-or-later

"""Fetch Union Raid data from the blablalink.com API.

The data is protected: the request has to carry the login cookies of an
account in the union. Export them from a logged-in browser as a Netscape
cookies.txt file; they are only sent to api.blablalink.com.
"""

from http.cookiejar import MozillaCookieJar
import json
import urllib.request

API = "https://api.blablalink.com/api/game/proxy/Game"
NOT_LOGGED_IN = 300001


class ApiError(RuntimeError):
    pass


def short_openid(openid):
    """The website sends only the last part of '29080-123…' for the current season."""
    return openid.split("-")[-1]


class Client:
    def __init__(self, cookies_path, timeout=30):
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

    def current_season(self, guild_id, area_id, openid):
        params = {"guild_id": guild_id, "nikke_area_id": int(area_id),
                  "intl_open_id": short_openid(openid)}
        return {
            "GetUnionRaidData": self.call("GetUnionRaidData", params),
            "GetUnionRaidLevelInfo": self.call("GetUnionRaidLevelInfo", params),
        }

    def past_season(self, guild_id, area_id, season_id):
        params = {"area_id": int(area_id), "guild_id": guild_id,
                  "season_id": str(season_id)}
        return {
            "GetUnionRaidDataOfGuildSeason":
                self.call("GetUnionRaidDataOfGuildSeason", params),
            "GetUnionRaidLevelDataOfGuildSeason":
                self.call("GetUnionRaidLevelDataOfGuildSeason", params),
        }
