# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line interface."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import compare as comparison
from . import openbao, report
from .api import ApiError, Client
from .history import HistoryError, Store
from .model import DataError, parse

FORMATS = {
    "table": report.table,
    "runs-csv": report.runs_csv,
    "summary-csv": report.summary_csv,
    "json": report.as_json,
}
DATA_KEYS = ("GetUnionRaidData", "GetUnionRaidDataOfGuildSeason")


def result_data(result):
    for key in DATA_KEYS:
        if key in result:
            return result[key]
    return result


def load(path):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    # A file written by `fetch` holds one response per endpoint.
    for key in DATA_KEYS:
        if isinstance(data, dict) and key in data:
            return data[key]
    return data


def cmd_fetch(args):
    client = Client(args.cookies, browser=args.cookies_from_browser)
    if args.season_id:
        result = client.past_season(args.guild_id, args.area_id, args.season_id)
    else:
        result = client.current_season(args.guild_id, args.area_id, args.openid)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)


def clean_token(value):
    """The token from RAID_WRITE_TOKEN, without paste framing.

    A hidden prompt (`read -s`) can receive the terminal's bracketed-paste
    markers around a pasted value, which are not valid in a header.
    """
    token = (value or "").replace("\x1b[200~", "").replace("\x1b[201~", "")
    token = token.strip()
    if not token:
        raise SystemExit("error: set RAID_WRITE_TOKEN")
    if not token.isascii() or not token.isprintable() or " " in token:
        raise SystemExit("error: RAID_WRITE_TOKEN has spaces or control "
                         "characters in it; set it again")
    return token


def season_name(season_id):
    """S46 for the season id 1000046: the id is 1000000 plus the number."""
    if season_id.isdigit() and int(season_id) > 1_000_000:
        return f"S{int(season_id) - 1_000_000}"
    return None


def write_token():
    """RAID_WRITE_TOKEN, or the OpenBao secret when BLABLALINK_UNION_RAID=
    openbao is set."""
    try:
        if openbao.selected():
            return clean_token(openbao.write_token())
    except openbao.OpenBaoError as exc:
        raise SystemExit(f"error: {exc}")
    return clean_token(os.environ.get("RAID_WRITE_TOKEN"))


def send(url, method, name, token, data=None, force=False):
    """Call the server's /seasons/<name> with the write token."""
    request = urllib.request.Request(
        f"{url.rstrip('/')}/seasons/{urllib.parse.quote(name)}"
        + ("?force=1" if force else ""),
        method=method, data=data,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(response.read().decode().strip())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"error: server said {exc.code}: "
                         f"{exc.read().decode().strip()}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: can't reach {url}: {exc.reason}")


def cmd_push(args):
    name = args.season or season_name(args.season_id or "")
    if not name:
        raise SystemExit("error: give --season (a past season's name is "
                         "taken from its --season-id, e.g. S46)")
    token = write_token()  # before any fetching: a login may open a browser
    client = Client(args.cookies, browser=args.cookies_from_browser)
    if args.season_id:
        result = client.past_season(args.guild_id, args.area_id, args.season_id)
    else:
        result = client.current_season(args.guild_id, args.area_id, args.openid)
    if not any(m.runs for m in parse(result_data(result))):
        # Expected between seasons; a timer should not fail for it.
        print(f"no runs yet for {name}; nothing pushed")
        return
    send(args.url, "PUT", name, token, json.dumps(result).encode(),
         args.force)


def cmd_remove(args):
    send(args.url, "DELETE", args.season, write_token())


def stored_seasons(args):
    """(members, name, previous members or None, previous name)."""
    store = Store(args.db)
    try:
        names = store.names()
        name = args.season or (names[-1] if names else None)
        if name is None:
            raise HistoryError("no seasons stored yet; use `ingest`")
        members = store.load(name)
        previous, previous_name = _previous(store, names, name, args)
        return members, previous, previous_name
    finally:
        store.close()


def _previous(store, names, name, args):
    if args.no_compare:
        return None, ""
    if args.against:
        return store.load(args.against), args.against
    if name in names and names.index(name) > 0:
        before = names[names.index(name) - 1]
        return store.load(before), before
    return None, ""


def cmd_report(args):
    if args.input and args.season:
        raise SystemExit("error: give a file or --season, not both")
    if args.input:
        members = parse(load(args.input), args.lang)
        previous, previous_name = None, ""
        if args.against and not args.no_compare:
            store = Store(args.db)
            try:
                previous, previous_name = store.load(args.against), args.against
            finally:
                store.close()
    else:
        members, previous, previous_name = stored_seasons(args)
    only = None
    if args.member:
        wanted = args.member.casefold()
        only = {m.openid for m in members
                if wanted in m.nickname.casefold() or wanted == m.openid}
    print(FORMATS[args.format](members, args.day, previous, previous_name,
                               only).rstrip("\n"))


def cmd_ingest(args):
    members = parse(load(args.input), args.lang)
    store = Store(args.db)
    try:
        replaced = store.save(args.season, members)
    finally:
        store.close()
    runs = sum(len(m.runs) for m in members)
    print(f"{'replaced' if replaced else 'stored'} season {args.season!r}: "
          f"{len(members)} members, {runs} runs ({store.path})")


def cmd_seasons(args):
    store = Store(args.db)
    try:
        seasons = store.seasons()
    finally:
        store.close()
    if not seasons:
        print("no seasons stored yet; use `ingest`")
    for name, when, members, total in seasons:
        print(f"{name}  ingested {when}  {members} members  {total:,} damage")


def cmd_compare(args):
    store = Store(args.db)
    try:
        names = store.names()
        if args.old and args.new:
            old_name, new_name = args.old, args.new
        elif len(names) >= 2 and not (args.old or args.new):
            old_name, new_name = names[-2:]
        elif args.old or args.new:
            raise HistoryError("give both --from and --to, or neither")
        else:
            raise HistoryError("need at least two stored seasons to compare "
                               f"(have {len(names)}); use `ingest`")
        changes = comparison.compare(store.load(old_name), store.load(new_name))
    finally:
        store.close()
    if args.format == "csv":
        print(comparison.as_csv(changes).rstrip("\n"))
    elif args.format == "json":
        print(comparison.as_json(changes, old_name, new_name))
    else:
        print(comparison.table(changes, old_name, new_name))


def login(parser):
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cookies",
                       help="Netscape cookies.txt exported from the browser")
    group.add_argument("--cookies-from-browser", metavar="BROWSER",
                       help="read the login from a browser's cookie store, "
                       "NAME[+KEYRING][:PROFILE], e.g. brave (needs "
                       "gallery-dl)")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="blablalink-union-raid",
        description="Per-member Union Raid damage from blablalink.com.")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch", help="download the raw API responses (needs login cookies)")
    login(fetch)
    fetch.add_argument("--guild-id", help="default: your own union")
    fetch.add_argument("--area-id", type=int, help="default: your own union")
    fetch.add_argument("--openid", help="your openid, if the API asks for it")
    fetch.add_argument("--season-id", help="a past season; omit for the current")
    fetch.add_argument("-o", "--output", help="write JSON here, not to stdout")
    fetch.set_defaults(func=cmd_fetch)

    push = sub.add_parser(
        "push", help="fetch a season and send it to the server "
        "(token in RAID_WRITE_TOKEN; run it from cron or a timer)")
    push.add_argument("--url", required=True, help="e.g. https://raid.example")
    push.add_argument("--season", help="name to store it under, e.g. S47; "
                      "default for --season-id 1000046 is S46")
    login(push)
    push.add_argument("--guild-id", help="default: your own union")
    push.add_argument("--area-id", type=int, help="default: your own union")
    push.add_argument("--openid", help="your openid, if the API asks for it")
    push.add_argument("--season-id", help="a past season; omit for the current")
    push.add_argument("--force", action="store_true",
                      help="replace a stored season even when this has far "
                      "fewer runs than it")
    push.set_defaults(func=cmd_push)

    remove = sub.add_parser(
        "remove", help="delete a season from the server "
        "(token in RAID_WRITE_TOKEN)")
    remove.add_argument("--url", required=True)
    remove.add_argument("--season", required=True, help="the stored name")
    remove.set_defaults(func=cmd_remove)

    db = argparse.ArgumentParser(add_help=False)
    db.add_argument("--db", help="history database (default: "
                    "~/.local/share/blablalink-union-raid/history.sqlite3)")

    rep = sub.add_parser(
        "report", parents=[db], help="print damage per member and run")
    rep.add_argument("input", nargs="?", help="JSON written by `fetch`, or a "
                     "response saved from the browser's network tab; omit to "
                     "use a stored season")
    rep.add_argument("--season", help="a stored season (default: the latest)")
    rep.add_argument("--against", metavar="SEASON",
                     help="compare with this stored season (default for a "
                     "stored season: the one before it; none for a file)")
    rep.add_argument("--no-compare", action="store_true",
                     help="don't compare with another season")
    rep.add_argument("--format", choices=FORMATS, default="table")
    rep.add_argument("--day", type=int, help="only this day (1-based)")
    rep.add_argument("--member", help="only members matching this name/openid")
    rep.add_argument("--lang", default="en",
                     help="boss name language, for files; stored seasons keep "
                     "the language they were ingested with")
    rep.set_defaults(func=cmd_report)

    ingest = sub.add_parser(
        "ingest", parents=[db],
        help="add a season to the history (same name again replaces it)")
    ingest.add_argument("input", help="same files as `report`")
    ingest.add_argument("--season", required=True,
                        help="a name for this season, e.g. 2026-10 or its id")
    ingest.add_argument("--lang", default="en", help="boss name language")
    ingest.set_defaults(func=cmd_ingest)

    seasons = sub.add_parser("seasons", parents=[db],
                             help="list the stored seasons")
    seasons.set_defaults(func=cmd_seasons)

    comp = sub.add_parser(
        "compare", parents=[db],
        help="rank changes between two seasons (default: the last two added)")
    comp.add_argument("--from", dest="old", help="the older season")
    comp.add_argument("--to", dest="new", help="the newer season")
    comp.add_argument("--format", choices=["table", "csv", "json"],
                      default="table")
    comp.set_defaults(func=cmd_compare)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ApiError, DataError, HistoryError, OSError) as exc:
        raise SystemExit(f"error: {exc}")
