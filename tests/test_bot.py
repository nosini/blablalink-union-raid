# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Discord bot's embeds; needs discord.py, skipped without it."""

import json
from pathlib import Path
import re
import sys
import unittest

from blablalink_union_raid import compare, report
from blablalink_union_raid.cli import load
from blablalink_union_raid.model import parse
from blablalink_union_raid.server import brief

sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))
try:
    import embeds
except ImportError:
    embeds = None

FIXTURES = Path(__file__).parent / "fixtures"


def wrapped(members, previous=None):
    return {"season": "2026-10", "ingested_at": "2026-11-09 20:17:35",
            "compared_with": "2026-09" if previous else None,
            "members": json.loads(report.as_json(
                members, None, previous, "2026-09" if previous else "")),
            "previous_members": json.loads(report.as_json(previous or []))}


@unittest.skipUnless(embeds, "discord.py is not installed")
class EmbedTest(unittest.TestCase):
    def setUp(self):
        self.old = parse(load(FIXTURES / "season.json"))
        self.new = parse(load(FIXTURES / "season2.json"))

    def text(self, built):
        return "\n".join(e.description or "" for e in built)

    def test_short(self):
        self.assertEqual(embeds.short(5_500_000_000), "5.50B")
        self.assertEqual(embeds.short(950_000_000), "950.0M")
        self.assertEqual(embeds.short(1234), "1K")

    def plain(self, built):
        return re.sub("\x1b\\[[0-9;]*m", "", self.text(built))

    def test_season_is_the_last_day_against_last_seasons_same_day(self):
        built = embeds.season(wrapped(self.new, self.old))
        text = self.plain(built)
        self.assertIn("day 2", built[0].title)
        self.assertNotIn("Alice", text)  # Alice never played day 2
        # day 2: Bob 2500, Dave 500. Last season's day 2: Alice 1000,
        # Bob 2100 -> Bob was 1st and stays, Dave is new.
        self.assertRegex(text, r"1\s+Bob\s+1/1\s+2500\s+-")
        self.assertRegex(text, r"2\s+Dave\s+1/1\s+500\s+New!")
        self.assertIn("2026-09 day 2", built[-1].footer.text)

    def test_season_moves_against_last_seasons_day(self):
        def day2(openid, name, damage):
            run = {"run": 1, "damage": damage, "final_hit": False,
                   "boss": "B", "elements": [], "boss_icon": "", "squad": []}
            return {"openid": openid, "member": name,
                    "days": {"2": {"total": damage, "runs": [run]}}}
        data = {"season": "S2", "ingested_at": "t", "compared_with": "S1",
                "members": [day2("b", "Bea", 900), day2("a", "Abe", 800),
                            day2("c", "Cy", 700)],
                "previous_members": [day2("a", "Abe", 900),
                                     day2("b", "Bea", 800)]}
        text = self.plain(embeds.season(data))
        self.assertRegex(text, r"1\s+Bea\s.*↑1")
        self.assertRegex(text, r"2\s+Abe\s.*↓1")
        self.assertRegex(text, r"3\s+Cy\s.*New!")

    def test_season_without_a_last_season_has_no_changes(self):
        text = self.plain(embeds.season(wrapped(self.old)))
        self.assertNotIn("↑", text)
        self.assertNotIn("↓", text)
        self.assertNotIn("New!", text)

    def test_day_ranks_like_the_leaders_sheet(self):
        def entry(total, runs, kills=0):
            return {"total": total, "runs": [
                {"run": i, "boss": "B", "damage": total // runs,
                 "final_hit": i <= kills, "elements": [], "boss_icon": "",
                 "squad": []} for i in range(1, runs + 1)]}
        members = [
            # a is first on day 1, second on day 2; d has missed an attempt
            {"openid": "a", "member": "Ann", "days": {
                "1": entry(300_000_000, 3), "2": entry(200_000_000, 3, 2)}},
            {"openid": "b", "member": "Bo", "days": {
                "1": entry(200_000_000, 3), "2": entry(250_000_000, 3)}},
            {"openid": "d", "member": "Di", "days": {
                "1": entry(100_000_000, 3), "2": entry(900_000_000, 2)}},
            {"openid": "n", "member": "Neo", "days": {
                "2": entry(50_000_000, 3)}},
        ]
        data = {"season": "S", "ingested_at": "t", "compared_with": None,
                "members": members}
        rows = self.plain(embeds.day(data, 2)).splitlines()
        body = [r.split() for r in rows if r.split()[:1] and
                r.split()[0].isdigit()]
        # Di made 2 of 3 attempts: last despite the most damage
        self.assertEqual([r[1] for r in body], ["Bo", "Ann", "Neo", "Di"])
        self.assertEqual(body[0][4], "↑1")      # Bo was 2nd on day 1
        self.assertEqual(body[1][4], "↓1")
        self.assertEqual(body[2][4], "New!")
        self.assertIn("Finisher x2", " ".join(body[1]))
        self.assertEqual(body[3][2], "2/3")  # Di made 2 of 3 attempts
        self.assertEqual(body[0][2], "3/3")
        self.assertIn("\x1b[0;31m2/3", self.text(embeds.day(data, 2)))
        first = self.plain(embeds.day(data, 1))
        self.assertNotIn("↑", first)  # nothing to compare with

    def test_day_not_found(self):
        with self.assertRaises(embeds.Empty):
            embeds.day(wrapped(self.new, self.old), 99)

    def test_member_card(self):
        built = embeds.member(wrapped(
            [m for m in self.new if m.nickname == "Bob"], self.old))
        text = self.plain(built)
        self.assertEqual(built[0].title, "Bob · 2026-10")
        self.assertRegex(text, r"1\s+Bob\s+2\s+5500\s+↑2")
        self.assertIn("Boss 1", text)
        self.assertIn("Lv 522", text)
        self.assertEqual(text.count("```") % 2, 0)
        self.assertNotIn("``````", text)

    def test_member_shows_at_most_three(self):
        data = wrapped(self.new)
        data["members"] = data["members"] * 2
        built = embeds.member(data)
        self.assertEqual(len(built), 3)
        self.assertIn("6 match", built[-1].footer.text)

    def test_compare_lists_leavers(self):
        data = json.loads(compare.as_json(
            compare.compare(self.old, self.new), "2026-09", "2026-10"))
        built = embeds.compare(data)
        text = self.plain(built)
        self.assertIn("Carol (was #2)", built[-1].fields[0].value)
        self.assertRegex(text, r"1\s+Bob\s+5500\s+↑2\s+\+2900")
        self.assertRegex(text, r"Dave\s.*New!")
        self.assertRegex(text, r"Alice\s.*↓2\s+-2900")

    def test_long_rankings_stay_within_discord_limits(self):
        data = wrapped(self.new)
        data["members"] = [dict(data["members"][0], member=f"m{i}" * 6,
                                openid=str(i)) for i in range(400)]
        built = embeds.season(data)
        self.assertTrue(all(len(e.description) <= 4096 for e in built))
        self.assertLessEqual(sum(len(e.description) + len(e.title or "")
                                 + len(e.footer.text or "")
                                 for e in built), 6000)
        self.assertIn("more", built[-1].description)
        # every embed holds a complete code block
        self.assertTrue(all(e.description.count("```") % 2 == 0
                            for e in built))


@unittest.skipUnless(embeds, "discord.py is not installed")
class HistoryTest(unittest.TestCase):
    def setUp(self):
        old = parse(load(FIXTURES / "season.json"))
        new = parse(load(FIXTURES / "season2.json"))
        self.data = {"seasons": [
            {"name": "S45", "ingested_at": "t", "members": brief(old)},
            {"name": "S46", "ingested_at": "t", "members": brief(new)}]}

    def plain(self, built):
        return re.sub("\x1b\\[[0-9;]*m", "", "\n".join(
            e.description or "" for e in built))

    def test_shows_each_season_newest_first(self):
        built = embeds.history(self.data, "Bob")
        text = self.plain(built)
        self.assertIn("Bob · Union Raid history", built[0].title)
        table = text.split("```ansi")[1]
        self.assertLess(table.index("S46"), table.index("S45"))
        # S45 day 2: Bob 2100 was 1st; S46 day 2: Bob 2500 is 1st
        self.assertRegex(text, r"S46\s+1\s+1/1\s+2500\s+-")
        self.assertRegex(text, r"S45\s+1\s+2/2\s+2100")
        self.assertIn("2 seasons", text)

    def test_name_is_matched_ignoring_case_and_spaces(self):
        self.assertIn("S46", self.plain(embeds.history(self.data, "  bOb ")))

    def test_member_new_this_season_has_no_change(self):
        text = self.plain(embeds.history(self.data, "Dave"))
        self.assertNotIn("S45", text)
        self.assertRegex(text, r"S46\s+2\s+1/1\s+500\s+-")

    def test_member_who_missed_the_final_day(self):
        text = self.plain(embeds.history(self.data, "Alice"))
        self.assertRegex(text, r"S46\s+-\s+0/1\s+0\s+-\s+No runs")

    def test_unknown_name_explains_what_to_do(self):
        with self.assertRaises(embeds.Empty) as raised:
            embeds.history(self.data, "Nobody")
        self.assertIn("server nickname", str(raised.exception))

    def test_only_the_caller_s_row_is_shown(self):
        text = self.plain(embeds.history(self.data, "Bob"))
        for other in ("Alice", "Carol", "Dave"):
            self.assertNotIn(other, text)


if __name__ == "__main__":
    unittest.main()
