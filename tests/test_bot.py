# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Discord bot's embeds; needs discord.py, skipped without it."""

import json
from pathlib import Path
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
        self.assertEqual(embeds.signed(-2_900_000_000), "-2.90B")

    def test_season_with_comparison(self):
        built = embeds.season(wrapped(self.new, self.old))
        text = self.text(built)
        self.assertIn("🥇 **Bob** · 5.50B 🟢▲2 (+2.90B)", text)
        self.assertIn("🆕", text)  # Dave is new
        self.assertIn("2026-09", built[-1].footer.text)

    def test_season_without_comparison(self):
        text = self.text(embeds.season(wrapped(self.old)))
        self.assertIn("🥇", text)
        self.assertNotIn("▲", text)

    def test_day_and_member(self):
        data = wrapped(self.new, self.old)
        self.assertIn("day 1", embeds.day(data, 1)[0].title)
        with self.assertRaises(embeds.Empty):
            embeds.day(data, 99)
        built = embeds.member(wrapped(
            [m for m in self.new if m.nickname == "Bob"], self.old))
        self.assertEqual(built[0].title, "Bob · 2026-10")
        self.assertTrue(built[0].fields)

    def test_compare_lists_leavers(self):
        data = json.loads(compare.as_json(
            compare.compare(self.old, self.new), "2026-09", "2026-10"))
        built = embeds.compare(data)
        self.assertIn("Carol (was #2)", built[-1].fields[0].value)

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

    def test_names_cannot_inject_markdown_or_mentions(self):
        self.assertNotIn("@everyone", embeds.name("@everyone"))
        self.assertEqual(embeds.name("a*b"), "a\\*b")


if __name__ == "__main__":
    unittest.main()
