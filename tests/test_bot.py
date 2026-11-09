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
                members, None, previous, "2026-09" if previous else ""))}


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

    def test_season_with_comparison(self):
        built = embeds.season(wrapped(self.new, self.old))
        text = self.plain(built)
        self.assertIn("Damage (M)", text)
        self.assertRegex(text, r"1\s+Bob\s+\d+\s+5500\s+↑2")
        self.assertRegex(text, r"Dave\s.*New!")
        self.assertRegex(text, r"Alice\s.*↓2")
        self.assertIn("\x1b[0;32m↑2", self.text(built))  # green
        self.assertIn("2026-09", built[-1].footer.text)

    def test_season_without_comparison(self):
        text = self.plain(embeds.season(wrapped(self.old)))
        self.assertNotIn("↑", text)
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
        self.assertIn("Unfinished", " ".join(body[3]))
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
        data["members"] = [dict(data["members"][0], member=f"m{i}" * 6)
                           for i in range(400)]
        built = embeds.season(data)
        self.assertTrue(all(len(e.description) <= 4096 for e in built))
        self.assertLessEqual(sum(len(e.description) + len(e.title or "")
                                 + len(e.footer.text or "")
                                 for e in built), 6000)
        self.assertIn("more", built[-1].description)
        # every embed holds a complete code block
        self.assertTrue(all(e.description.count("```") % 2 == 0
                            for e in built))


if __name__ == "__main__":
    unittest.main()
