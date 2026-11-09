# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line interface."""

import argparse
import json
import sys

from . import compare as comparison
from . import report
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


def load(path):
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    # A file written by `fetch` holds one response per endpoint.
    for key in DATA_KEYS:
        if isinstance(data, dict) and key in data:
            return data[key]
    return data


def cmd_fetch(args):
    client = Client(args.cookies)
    if args.season_id:
        result = client.past_season(args.guild_id, args.area_id, args.season_id)
    else:
        if not args.openid:
            raise SystemExit("--openid is needed for the current season")
        result = client.current_season(args.guild_id, args.area_id, args.openid)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            stream.write(text + "\n")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)


def stored_season(args):
    store = Store(args.db)
    try:
        names = store.names()
        name = args.season or (names[-1] if names else None)
        if name is None:
            raise HistoryError("no seasons stored yet; use `ingest`")
        return store.load(name)
    finally:
        store.close()


def cmd_report(args):
    if args.input and args.season:
        raise SystemExit("error: give a file or --season, not both")
    if args.input:
        members = parse(load(args.input), args.lang)
    else:
        members = stored_season(args)
    if args.member:
        wanted = args.member.casefold()
        members = [m for m in members if wanted in m.nickname.casefold()
                   or wanted == m.openid]
    print(FORMATS[args.format](members, args.day).rstrip("\n"))


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


def build_parser():
    parser = argparse.ArgumentParser(
        prog="blablalink-union-raid",
        description="Per-member Union Raid damage from blablalink.com.")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser(
        "fetch", help="download the raw API responses (needs login cookies)")
    fetch.add_argument("--cookies", required=True,
                       help="Netscape cookies.txt exported from the browser")
    fetch.add_argument("--guild-id", required=True)
    fetch.add_argument("--area-id", required=True, type=int)
    fetch.add_argument("--openid", help="your openid, for the current season")
    fetch.add_argument("--season-id", help="a past season; omit for the current")
    fetch.add_argument("-o", "--output", help="write JSON here, not to stdout")
    fetch.set_defaults(func=cmd_fetch)

    db = argparse.ArgumentParser(add_help=False)
    db.add_argument("--db", help="history database (default: "
                    "~/.local/share/blablalink-union-raid/history.sqlite3)")

    rep = sub.add_parser(
        "report", parents=[db], help="print damage per member and run")
    rep.add_argument("input", nargs="?", help="JSON written by `fetch`, or a "
                     "response saved from the browser's network tab; omit to "
                     "use a stored season")
    rep.add_argument("--season", help="a stored season (default: the latest)")
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
