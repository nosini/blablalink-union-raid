# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line interface."""

import argparse
import json
import sys

from . import report
from .api import ApiError, Client
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


def cmd_report(args):
    members = parse(load(args.input), args.lang)
    if args.member:
        wanted = args.member.casefold()
        members = [m for m in members if wanted in m.nickname.casefold()
                   or wanted == m.openid]
    print(FORMATS[args.format](members, args.day).rstrip("\n"))


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

    rep = sub.add_parser("report", help="print damage per member and run")
    rep.add_argument("input", help="JSON written by `fetch`, or a response "
                     "saved from the browser's network tab")
    rep.add_argument("--format", choices=FORMATS, default="table")
    rep.add_argument("--day", type=int, help="only this day (1-based)")
    rep.add_argument("--member", help="only members matching this name/openid")
    rep.add_argument("--lang", default="en", help="boss name language")
    rep.set_defaults(func=cmd_report)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ApiError, DataError, OSError) as exc:
        raise SystemExit(f"error: {exc}")
