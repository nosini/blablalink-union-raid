# SPDX-License-Identifier: AGPL-3.0-or-later

"""Tests with synthetic data shaped like the website's own union raid data."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from blablalink_union_raid import api, cli, report
from blablalink_union_raid.model import DataError, days, parse

FIXTURE = Path(__file__).parent / "fixtures/season.json"
DATA = json.loads(FIXTURE.read_text())


class Model(unittest.TestCase):
    def test_groups_runs_per_member_sorted_by_total(self):
        members = parse(DATA)
        self.assertEqual([m.nickname for m in members], ["Alice", "Carol", "Bob"])
        alice = members[0]
        self.assertEqual([r.damage for r in alice.day_runs(1)],
                         [900_000_000, 1_200_000_000, 800_000_000])
        self.assertEqual([r.number for r in alice.day_runs(1)], [1, 2, 3])
        self.assertEqual(alice.day_total(1), 2_900_000_000)
        self.assertEqual(alice.total, 3_900_000_000)
        self.assertTrue(alice.runs[2].final_hit)

    def test_days_are_one_based(self):
        self.assertEqual(days(parse(DATA)), [1, 2])

    def test_accepts_envelope_data_and_fetch_output(self):
        rows = DATA["data"]
        self.assertEqual(len(parse(rows)), 3)
        self.assertEqual(len(parse(DATA)), 3)

    def test_boss_name_language_and_fallback(self):
        self.assertEqual(parse(DATA, "ja")[0].runs[0].boss_name, "ボス1")
        self.assertEqual(parse(DATA, "de")[0].runs[0].boss_name, "Boss 1")

    def test_bad_input(self):
        with self.assertRaises(DataError):
            parse({"code": 0, "data": {"other": 1}})
        with self.assertRaises(DataError):
            parse([])

    def test_tolerates_missing_and_odd_fields(self):
        members = parse({"participate_data": [
            {"openid": "x", "day": 0, "total_damage": None},
            {"openid": "x", "day": "0", "total_damage": "12"}]})
        self.assertEqual(members[0].nickname, "Player")
        self.assertEqual([r.damage for r in members[0].runs], [0, 12])


class Reports(unittest.TestCase):
    def setUp(self):
        self.members = parse(DATA)

    def test_runs_csv(self):
        lines = report.runs_csv(self.members, day=2).splitlines()
        self.assertEqual(lines[0].split(",")[:4], ["openid", "member", "day", "run"])
        self.assertEqual(len(lines), 1 + 3)  # Alice 1, Bob 2

    def test_summary_csv_has_day_and_member_totals(self):
        rows = [l.split(",") for l in report.summary_csv(self.members).splitlines()]
        self.assertEqual(rows[0], ["openid", "member", "day", "run1", "run2",
                                   "run3", "day_total", "member_total"])
        alice_day1 = next(r for r in rows if r[1] == "Alice" and r[2] == "1")
        self.assertEqual(alice_day1[3:], ["900000000", "1200000000", "800000000",
                                          "2900000000", "3900000000"])

    def test_table_mentions_everyone_and_totals(self):
        text = report.table(self.members)
        for expected in ("Day 1", "Day 2", "Season total", "Alice", "3,900,000,000"):
            self.assertIn(expected, text)

    def test_day_table_is_sorted_by_that_days_damage(self):
        day1 = report.table(self.members, day=1)
        self.assertLess(day1.index("Carol"), day1.index("Alice"))
        self.assertLess(day1.index("Alice"), day1.index("Bob"))

    def test_table_single_day(self):
        text = report.table(self.members, day=2)
        self.assertNotIn("Day 1", text)
        self.assertNotIn("Carol", text)

    def test_runs_csv_has_squad_and_boss_model(self):
        rows = list(__import__("csv").DictReader(
            io.StringIO(report.runs_csv(self.members))))
        first = next(r for r in rows if r["member"] == "Alice")
        self.assertEqual(first["monster_model_id"], "5001")
        self.assertEqual(json.loads(first["squad"])[0]["lv"], 200)

    def test_json_has_squad_and_icon(self):
        alice = json.loads(report.as_json(self.members))[0]
        self.assertEqual(alice["icon_id"], 2001)
        self.assertEqual(alice["days"]["1"]["runs"][0]["squad"][0]["tid"], 1001)

    def test_json(self):
        data = json.loads(report.as_json(self.members))
        self.assertEqual(data[0]["member"], "Alice")
        self.assertEqual(data[0]["days"]["1"]["total"], 2_900_000_000)


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def test_report_command(self):
        text = self.run_cli("report", str(FIXTURE), "--format", "runs-csv",
                            "--member", "alice")
        self.assertEqual(len(text.splitlines()), 1 + 4)

    def test_report_reads_fetch_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raid.json"
            path.write_text(json.dumps({"GetUnionRaidData": DATA,
                                        "GetUnionRaidLevelInfo": {}}))
            self.assertIn("Alice", self.run_cli("report", str(path)))

    def test_error_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text("{}")
            with self.assertRaises(SystemExit) as ctx:
                self.run_cli("report", str(path))
            self.assertIn("participate_data", str(ctx.exception))


class Api(unittest.TestCase):
    COOKIES = "# Netscape HTTP Cookie File\n"

    def client(self, responses):
        with tempfile.NamedTemporaryFile("w", delete=False) as stream:
            stream.write(self.COOKIES)
        self.addCleanup(Path(stream.name).unlink)
        client = api.Client(stream.name)
        calls = []

        def fake_open(request, timeout=None):
            calls.append((request.full_url, json.loads(request.data)))
            return io.BytesIO(json.dumps(responses.pop(0)).encode())

        client.opener = mock.Mock(open=fake_open)
        return client, calls

    def test_short_openid(self):
        self.assertEqual(api.short_openid("29080-18377088987798847343"),
                         "18377088987798847343")

    def test_current_season_requests(self):
        client, calls = self.client([{"code": 0, "data": {}}] * 2)
        client.current_season("g1", "84", "29080-123")
        self.assertEqual(calls[0], (f"{api.API}/GetUnionRaidData",
                                    {"guild_id": "g1", "nikke_area_id": 84,
                                     "intl_open_id": "123"}))
        self.assertTrue(calls[1][0].endswith("/GetUnionRaidLevelInfo"))

    def test_past_season_requests(self):
        client, calls = self.client([{"code": 0, "data": {}}] * 2)
        client.past_season("g1", "84", 7)
        self.assertEqual(calls[0][1], {"area_id": 84, "guild_id": "g1",
                                       "season_id": "7"})
        self.assertTrue(calls[0][0].endswith("/GetUnionRaidDataOfGuildSeason"))

    def test_login_error_is_explained(self):
        client, _ = self.client([{"code": 300001, "msg": "game not login"}])
        with self.assertRaisesRegex(api.ApiError, "not logged in"):
            client.call("GetUnionRaidData", {})

    def test_other_api_error(self):
        client, _ = self.client([{"code": 5, "msg": "nope"}])
        with self.assertRaisesRegex(api.ApiError, "5: nope"):
            client.call("GetUnionRaidData", {})


if __name__ == "__main__":
    unittest.main()
