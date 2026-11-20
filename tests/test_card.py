# SPDX-License-Identifier: AGPL-3.0-or-later

"""The card page and its images; the images need Pillow, skipped without."""

import html
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from blablalink_union_raid import card, report, sheet
from blablalink_union_raid.cli import load
from blablalink_union_raid.model import parse

try:
    from PIL import Image
except ImportError:
    Image = None

FIXTURES = Path(__file__).parent / "fixtures"


def wrapped(members, previous=None):
    return {"season": "2026-10", "ingested_at": "2026-11-09 20:17:35",
            "compared_with": "2026-09" if previous else None,
            "members": json.loads(report.as_json(
                members, None, previous, "2026-09" if previous else "")),
            "previous_members": json.loads(report.as_json(previous or []))}


def season(number_of_rows):
    """A synthetic sheet of any length, without a big fixture."""
    rows = [([i, f"Member{i}", "3/3", 100 + i, "-", ""], [None] * 6)
            for i in range(1, number_of_rows + 1)]
    return sheet.Sheet(f"Union Raid · S1 · day 1",
                       f"**Day total** 1B · {number_of_rows} members",
                       sheet.SHEET, sheet.SHEET_LEFT, rows, "Updated t")


class CardTest(unittest.TestCase):
    def setUp(self):
        self.table = sheet.season(wrapped(
            parse(load(FIXTURES / "season2.json")),
            parse(load(FIXTURES / "season.json"))))

    def payload(self, page):
        found = re.search(
            r'<script id="discord:component-embed"[^>]*>(.*?)</script>',
            page, re.S)
        return json.loads(found.group(1))

    def test_page_carries_the_link_preview_tags(self):
        page = card.page(self.table, "https://raid.example.org",
                         {"season": "2026-10", "v": "2026-11-09 20:17:35"})
        self.assertIn('<meta name="twitter:card"'
                      ' content="summary_large_image">', page)
        self.assertIn('<meta property="og:title"'
                      ' content="Union Raid · 2026-10 · day 2">', page)
        # & is escaped in the attribute; the reader decodes it back
        self.assertIn('content="https://raid.example.org/card.png'
                      '?season=2026-10&amp;v=2026-11-09+20%3A17%3A35"', page)
        self.assertEqual(page.count('<img src="/card.png?'), 1)

    def test_component_payload_shows_one_image(self):
        page = card.page(season(30), "https://raid.example.org", {})
        payload = self.payload(page)["component"]
        self.assertEqual(payload["type"], 17)
        self.assertEqual(payload["accent_color"], 0xF2A900)
        galleries = [c for c in payload["components"] if c["type"] == 12]
        self.assertEqual(len(galleries), 1)
        self.assertEqual(galleries[0]["items"][0]["media"]["url"],
                         "https://raid.example.org/card.png")
        texts = [c["content"] for c in payload["components"]
                 if c["type"] == 10]
        self.assertIn("**Day total** 1B · 30 members", texts[0])
        self.assertTrue(texts[-1].startswith("-# Updated t"))

    def test_a_leaving_member_is_listed(self):
        # Carol is in the old season and not in the new one
        table = sheet.Sheet("Union Raid · 2026-09 → 2026-10", "**Union total**",
                            sheet.COMPARE, sheet.COMPARE_LEFT, [([1, "Bob", 5,
                            "-", "+2", ""], [None] * 6)], "Updated t",
                            ["Carol (was #2)"])
        page = card.page(table, "https://raid.example.org", {})
        self.assertIn("No runs this season: Carol (was #2)", page)
        payload = self.payload(page)["component"]
        self.assertIn("Carol (was #2)", payload["components"][1]["content"])

    def test_payload_never_closes_the_script_tag(self):
        table = sheet.Sheet("Union Raid · </script> · day 1", "intro",
                            sheet.SHEET, sheet.SHEET_LEFT,
                            [([1, "A", "1/1", 1, "-", ""], [None] * 6)],
                            "Updated", ["</script> (was #1)"])
        page = card.page(table, "https://raid.example.org", {})
        found = re.search(
            r'<script id="discord:component-embed"[^>]*>(.*?)</script>',
            page, re.S)
        self.assertNotIn("</script", found.group(1))

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_png_is_a_readable_image_of_the_sheet(self):
        blob = card.png(self.table)
        self.assertEqual(blob[:8], b"\x89PNG\r\n\x1a\n")
        image = Image.open(io.BytesIO(blob))
        self.assertEqual(image.format, "PNG")
        width, height, _, _ = card._layout(self.table)
        self.assertEqual(image.size, (width, height))

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_long_names_are_clipped_to_the_column(self):
        table = sheet.Sheet("t", "i", sheet.SHEET, sheet.SHEET_LEFT,
                            [([1, "A" * 99, "3/3", 1, "-", ""], [None] * 6)],
                            "f")
        _, _, columns, cells = card._layout(table)
        clipped = cells[0][1]
        self.assertTrue(clipped.endswith("…"))
        limit = card.fonts().length("M" * card.NAME_CHARS)
        self.assertLessEqual(card.fonts().length(clipped), limit)
        self.assertEqual(columns[1], int(limit) + 2 * card.GAP)

    def test_the_page_escapes_every_url_it_writes(self):
        """`base` can be the request's Host header; it must stay inert."""
        page = card.page(self.table, 'https://host"><script>', {})
        self.assertIn('content="https://host&quot;&gt;&lt;script&gt;'
                      '/card.png"', page)
        self.assertIn('content="https://host&quot;&gt;&lt;script&gt;/card?"',
                      page)
        self.assertIn('<img src="/card.png"', page)
        self.assertNotIn('"><script>', page)

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_every_row_is_in_the_one_image(self):
        small = Image.open(io.BytesIO(card.png(season(12)))).size
        large = Image.open(io.BytesIO(card.png(season(32)))).size
        self.assertEqual(large[1] - small[1], 20 * card.ROW_H)

    @unittest.skipUnless(Image, "Pillow is not installed")
    def test_a_bad_font_file_is_a_card_error(self):
        with tempfile.NamedTemporaryFile() as bad:
            bad.write(b"not a font")
            bad.flush()
            with mock.patch.dict(os.environ, {"RAID_CARD_FONT": bad.name}):
                card._FONTS = None      # reload with the broken override
                try:
                    with self.assertRaises(card.CardError) as raised:
                        card.png(self.table)
                    self.assertIn(bad.name, str(raised.exception))
                finally:
                    card._FONTS = None   # later tests load the fonts again


if __name__ == "__main__":
    unittest.main()
