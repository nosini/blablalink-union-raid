# SPDX-License-Identifier: AGPL-3.0-or-later

"""HTTP service that receives seasons from `push` and serves reports.

Two bearer tokens: the write token (PUT /seasons/<name>, used by `push`) and
the read token (GET endpoints, used by the Discord bot). TLS and public
exposure are the reverse proxy's job; this listens on plain HTTP.

    PUT /seasons/<name>      body: JSON written by `fetch`; refused when it
                             has no runs, or less than half of the stored
                             runs, unless ?force=1
    DELETE /seasons/<name>   remove a season (write token)
    GET /seasons             one line per stored season
    GET /report?season=&day=&member=
    GET /compare?from=&to=
    GET /history             every season's runs per member, as JSON only
    GET /card[.png]          the sheet as images for the bot to attach, or
                             as a link-preview page: they answer the read
                             token, or anyone with RAID_PUBLIC_CARD=1

The GET endpoints answer with a text table, or with JSON for ?format=json
(the Discord bot's input). `/card` answers with the HTML page whose Open
Graph tags describe the sheet, `/card.png` with one image of it (`&chunk=N`,
twelve rows per image); anyone with the link can read the raid data.
"""

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sqlite3
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from . import card
from . import compare as comparison
from . import report
from . import sheet
from .history import HistoryError, Store
from .model import DataError, days, parse

MAX_BODY = 20 * 1024 * 1024
NAME = re.compile(r"[\w.\-]{1,64}")
DATA_KEYS = ("GetUnionRaidData", "GetUnionRaidDataOfGuildSeason")


def raid_data(data):
    for key in DATA_KEYS:
        if isinstance(data, dict) and key in data:
            return data[key]
    return data


def brief(members):
    """Each member's damage per day and run, without squads and the like."""
    return [{"openid": m.openid, "member": m.nickname, "days": {
        str(d): {"total": m.day_total(d), "runs": [
            {"run": r.number, "damage": r.damage, "final_hit": r.final_hit}
            for r in m.day_runs(d)]}
        for d in days([m])}} for m in members]


def make_handler(store, lock, write_token, read_token):
    def allowed(header, token):
        return hmac.compare_digest(header.encode(), f"Bearer {token}".encode())

    class Handler(BaseHTTPRequestHandler):
        server_version = "union-raid"

        def reply(self, status, text, kind="text/plain", headers=()):
            body = text.encode() if isinstance(text, str) else text
            self.send_response(status)
            if kind.startswith("image/"):
                self.send_header("Content-Type", kind)
            else:
                self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, token):
            if allowed(self.headers.get("Authorization", ""), token):
                return True
            self.reply(401, "unauthorized\n")
            return False

        def do_PUT(self):
            match = re.fullmatch(r"/seasons/([^/]+)", urlsplit(self.path).path)
            if not match:
                return self.reply(404, "not found\n")
            if not self.authorized(write_token):
                return
            name = unquote(match.group(1))
            force = parse_qs(urlsplit(self.path).query).get("force") == ["1"]
            if not NAME.fullmatch(name):
                return self.reply(400, "bad season name\n")
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_BODY:
                return self.reply(413, "body missing or too large\n")
            try:
                members = parse(raid_data(json.loads(self.rfile.read(length))))
            except (ValueError, DataError) as exc:
                return self.reply(400, f"not union raid data: {exc}\n")
            runs = sum(len(m.runs) for m in members)
            if not runs:
                return self.reply(422, "no runs in this data; not stored\n")
            with lock:
                have = store.run_count(name)
                if have and runs * 2 < have and not force:
                    return self.reply(
                        409, f"{name} has {have} runs stored and this has "
                        f"{runs}; not replaced (use force to override)\n")
                replaced = store.save(name, members)
            self.reply(200, f"{'replaced' if replaced else 'stored'} {name}: "
                       f"{len(members)} members, {runs} runs\n")

        def do_DELETE(self):
            match = re.fullmatch(r"/seasons/([^/]+)", urlsplit(self.path).path)
            if not match:
                return self.reply(404, "not found\n")
            if not self.authorized(write_token):
                return
            name = unquote(match.group(1))
            with lock:
                removed = store.delete(name)
            if not removed:
                return self.reply(404, f"no season named {name}\n")
            self.reply(200, f"removed {name}\n")

        def do_GET(self):
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path in ("/card", "/card.png"):
                return self.card(url.path, query)
            if url.path not in ("/seasons", "/report", "/compare", "/history"):
                return self.reply(404, "not found\n")
            if not self.authorized(read_token):
                return
            as_json = query.get("format") == "json" or url.path == "/history"
            try:
                with lock:
                    text = (self.read_json if as_json else self.read)(
                        url.path, query)
            except (HistoryError, ValueError) as exc:
                return self.reply(404, f"{exc}\n")
            self.reply(200, text + "\n",
                       "application/json" if as_json else "text/plain")

        def selected(self, query):
            """(name, members, previous name, previous members or None)."""
            names = store.names()
            if not names:
                raise HistoryError("no seasons stored yet")
            name = query.get("season") or names[-1]
            members = store.load(name)
            before = names.index(name) - 1
            if before < 0:
                return name, members, "", None
            return name, members, names[before], store.load(names[before])

        def pair(self, query):
            names = store.names()
            if query.get("from") and query.get("to"):
                old, new = query["from"], query["to"]
            elif len(names) >= 2:
                old, new = names[-2:]
            else:
                raise HistoryError("need at least two stored seasons")
            return old, new, comparison.compare(store.load(old),
                                                store.load(new))

        def read_json(self, path, query):
            if path == "/history":
                return json.dumps({"seasons": [
                    {"name": n, "ingested_at": w, "members": brief(
                        store.load(n))} for n, w, _, _ in store.seasons()]})
            if path == "/seasons":
                return json.dumps([
                    {"name": n, "ingested_at": w, "members": m, "total": t}
                    for n, w, m, t in store.seasons()])
            if path == "/compare":
                old, new, changes = self.pair(query)
                # the card link's cache buster: the newer of the two pushes
                when = max(w for n, w, _, _ in store.seasons()
                           if n in (old, new))
                return comparison.as_json(changes, old, new, when)
            name, members, before, previous = self.selected(query)
            wanted = (query.get("member") or "").casefold()
            only = {m.openid for m in members
                    if wanted in m.nickname.casefold()} if wanted else None
            day = int(query["day"]) if query.get("day") else None
            when = next(w for n, w, _, _ in store.seasons() if n == name)
            return json.dumps({
                "season": name, "ingested_at": when,
                "compared_with": before if previous else None,
                "members": json.loads(report.as_json(
                    members, day, previous, before, only)),
                "previous_members": brief(previous or [])})

        def read(self, path, query):
            names = store.names()
            if path == "/seasons":
                return "\n".join(
                    f"{n}  {w}  {m} members  {t:,} damage"
                    for n, w, m, t in store.seasons()) or "no seasons"
            if path == "/report":
                if not names:
                    raise HistoryError("no seasons stored yet")
                name = query.get("season") or names[-1]
                members = store.load(name)
                before = names.index(name) - 1 if name in names else -1
                previous = store.load(names[before]) if before >= 0 else None
                only = None
                if query.get("member"):
                    wanted = query["member"].casefold()
                    only = {m.openid for m in members
                            if wanted in m.nickname.casefold()}
                day = int(query["day"]) if query.get("day") else None
                return report.table(
                    members, day, previous,
                    names[before] if previous else "", only).rstrip("\n")
            if len(names) < 2 and not (query.get("from") and query.get("to")):
                raise HistoryError("need at least two stored seasons")
            old, new = (query.get("from"), query.get("to")) \
                if query.get("from") and query.get("to") else names[-2:]
            return comparison.table(
                comparison.compare(store.load(old), store.load(new)), old, new)

        def card(self, path, query):
            """The sheet as images (or as a link-preview page, same routes).

            The bot fetches the images with its read token. A link preview
            needs the routes public, because Discord's crawler cannot send
            a token: set RAID_PUBLIC_CARD=1 for that (anyone with the link
            can then read the raid data, member names included).

            `?from=&to=` compares two seasons, anything else is the report
            (`?season=&day=`, the last day without `day`); `v` is ignored
            here, but kept in the links so a new push makes Discord's
            30-minute cache fetch fresh data.
            """
            if os.environ.get("RAID_PUBLIC_CARD") != "1" \
                    and not self.authorized(read_token):
                return
            params = {k: query[k] for k in ("v", "season", "day", "from", "to")
                      if k in query}
            try:
                with lock:
                    if "from" in query and "to" in query:
                        table = sheet.compare(
                            json.loads(self.read_json("/compare", params)))
                    else:
                        # `day` goes to sheet.day alone: asked of the
                        # report, it drops every other day, and the
                        # change column has no day before to compare with.
                        report = {k: v for k, v in params.items()
                                  if k != "day"}
                        data = json.loads(self.read_json("/report", report))
                        table = sheet.day(data, int(params["day"])) \
                            if "day" in params else sheet.season(data)
            except (HistoryError, ValueError) as exc:
                return self.reply(404, f"{exc}\n")
            if path == "/card.png":
                try:
                    chunk = int(query.get("chunk") or 0)
                except ValueError:
                    return self.reply(404, "bad chunk\n")
                if not 0 <= chunk < len(card.chunk_rows(table)):
                    return self.reply(404, "no such chunk\n")
                try:
                    image = card.png(table, chunk)
                except card.CardError as exc:
                    return self.reply(500, f"{exc}\n")
                return self.reply(200, image, "image/png",
                                  headers=card.CACHED)
            base = (os.environ.get("RAID_PUBLIC_URL")
                    or f"https://{self.headers.get('Host', 'localhost')}"
                    ).rstrip("/")
            return self.reply(200, card.page(table, base, params),
                              "text/html", headers=card.CACHED)

        def log_message(self, *args):
            pass

    return Handler


def main():
    write_token = os.environ["RAID_WRITE_TOKEN"]
    read_token = os.environ["RAID_READ_TOKEN"]
    if write_token == read_token:
        raise SystemExit("RAID_WRITE_TOKEN and RAID_READ_TOKEN must differ")
    store = Store(os.environ["RAID_DB"])
    # Handlers run in other threads; the lock serialises every use.
    store.db.close()
    store.db = sqlite3.connect(store.path, check_same_thread=False)
    store.db.execute("PRAGMA foreign_keys = ON")
    handler = make_handler(store, threading.Lock(), write_token, read_token)
    ThreadingHTTPServer(("0.0.0.0", 8080), handler).serve_forever()


if __name__ == "__main__":
    main()
