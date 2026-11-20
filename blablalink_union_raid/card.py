# SPDX-License-Identifier: AGPL-3.0-or-later

"""The raid sheet as a link-preview card: PNG images and the page behind them.

Discord builds a link preview by fetching the page at `/card` and reading
its Open Graph tags, so the sheet is drawn to PNG images that stay readable
at the ~400 pixels a preview shows. A taller table is split into several
images of `ROWS_PER_IMAGE` rows; the page carries a component-embed payload
that stacks them all inside one preview, with the plain Open Graph tags as
the fallback for clients that show neither.

Drawing needs Pillow, an optional dependency (`pip install ".[card]"`).
Without it the page is still served, just without image dimensions and
without the images themselves.

Nicknames are drawn with a Latin font; characters it lacks (CJK, emoji)
appear as replacement boxes.
"""

import glob
import html
import io
import json
import os
from urllib.parse import urlencode

ROWS_PER_IMAGE = 12   # rows per PNG; one preview shows ~400px of width
MAX_IMAGES = 10       # Discord's cap for one component embed
NAME_CHARS = 13       # an IGN is clipped to this many characters

# Discord caches a preview for ~30 minutes; a new push busts it with ?v=
CACHED = (("Cache-Control", "public, max-age=1800"),)

SCALE = 2             # two pixels per point: crisp when zoomed and scaled
PAPER = "#2B2D31"     # Discord's embed background
ZEBRA = "#303237"
INK = "#DBDEE1"
MUTED = "#949BA4"
ACCENT = "#F2A900"
COLOURS = {"green": "#57F287", "red": "#ED4245", "yellow": "#FEE75C",
           "blue": "#5865F2", "grey": MUTED, None: INK}

PAD = 14 * SCALE      # margin around everything
GAP = 12 * SCALE      # padding on each side of a cell
ROW_H = 19 * SCALE
TITLE_H = 24 * SCALE
INTRO_H = 20 * SCALE
HEAD_H = 22 * SCALE
FOOTER_H = 18 * SCALE

FONT_SIZES = {"title": 17 * SCALE, "intro": 13 * SCALE, "body": 13 * SCALE,
              "footer": 11 * SCALE}
BOLD = {"title": True, "intro": False, "body": False, "footer": False}

FONT_STYLES = {   # the first one found anywhere under /usr/share/fonts
    False: ("LiberationMono-Regular.ttf", "DejaVuSansMono.ttf"),
    True: ("LiberationMono-Bold.ttf", "DejaVuSansMono-Bold.ttf")}


class CardError(RuntimeError):
    """The image cannot be drawn (most likely: Pillow is missing)."""


def _font_path(bold):
    """A monospace font file, searched by name so it survives other distros."""
    override = os.environ.get("RAID_CARD_FONT")
    if override and os.path.exists(override):
        return override
    for name in FONT_STYLES[bold]:
        found = glob.glob(f"/usr/share/fonts/**/{name}", recursive=True)
        if found:
            return found[0]
    return None


class _Fonts:
    """The fonts used by the card, or Pillow's default when none is found."""

    def __init__(self):
        try:
            from PIL import ImageFont
        except ImportError as exc:
            raise CardError("Pillow is not installed") from exc
        self._fonts = {}
        for bold, sizes in ((False, FONT_SIZES), (True, FONT_SIZES)):
            for name, size in sizes.items():
                self._fonts[bold, name] = self._load(ImageFont, bold, size)

    def _load(self, ImageFont, bold, size):
        path = _font_path(bold)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError as exc:    # the file exists but is no font
                raise CardError(f"cannot load the font {path}") from exc
        try:                       # Pillow's built-in font, sized since 10.1
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()

    def font(self, name):
        return self._fonts[BOLD[name], name]

    def length(self, text, name="body"):
        return self.font(name).getlength(text)

    def clip(self, text):
        """An IGN that fits: too long becomes '…'."""
        limit = self.length("M" * NAME_CHARS)
        if self.length(text) <= limit:
            return text
        while text and self.length(text + "…") > limit:
            text = text[:-1]
        return text + "…"


_FONTS = None


def fonts():
    global _FONTS
    if _FONTS is None:
        _FONTS = _Fonts()
    return _FONTS


def chunk_rows(table):
    """The sheet's rows, split into the images that each show a part."""
    return [table.rows[i:i + ROWS_PER_IMAGE]
            for i in range(0, len(table.rows), ROWS_PER_IMAGE)]


def _layout(table, chunk=0):
    """(width, height, column widths, drawn cell texts) of one image.

    The columns are measured over every row of the table, so all its
    images come out equally wide; the height follows this image's rows.
    """
    pen = fonts()
    ign = table.header.index("IGN") if "IGN" in table.header else None
    cells = [[pen.clip(str(c)) if i == ign else str(c)
              for i, c in enumerate(values)] for values, _ in table.rows]
    columns = [int(max(pen.length(text)
                       for text in [str(table.header[i])] +
                       [row[i] for row in cells])) + 2 * GAP
               for i in range(len(table.header))]
    width = 2 * PAD + sum(columns)
    shown = cells[chunk * ROWS_PER_IMAGE:(chunk + 1) * ROWS_PER_IMAGE]
    height = (PAD + TITLE_H + INTRO_H + HEAD_H + len(shown) * ROW_H
              + FOOTER_H + PAD)
    return width, height, columns, shown


def png(table, chunk=0):
    """One image of the sheet as PNG bytes."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise CardError("Pillow is not installed") from exc
    rows = chunk_rows(table)[chunk]
    width, height, columns, cells = _layout(table, chunk)
    pen = fonts()
    image = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(image)

    def text(xy, value, name, colour):
        draw.text(xy, str(value), font=pen.font(name), fill=colour)

    y = PAD
    text((PAD, y), table.title, "title", ACCENT)
    y += TITLE_H
    text((PAD, y), table.intro.replace("**", ""), "intro", MUTED)
    y += INTRO_H
    for i, head in enumerate(table.header):
        x = PAD + sum(columns[:i]) + (GAP if i in table.left else
                                      int(columns[i] - GAP
                                          - pen.length(head)))
        text((x, y), head, "body", ACCENT)
    y += HEAD_H
    for number, ((_, colours), row) in enumerate(zip(rows, cells)):
        if number % 2:      # a faint zebra line to follow the rows
            draw.rectangle((0, y, width, y + ROW_H), fill=ZEBRA)
        for i, value in enumerate(row):
            x = PAD + sum(columns[:i]) + (GAP if i in table.left else
                                          int(columns[i] - GAP
                                              - pen.length(value)))
            text((x, y), value, "body", COLOURS[colours[i]])
        y += ROW_H
    text((PAD, height - FOOTER_H), table.footer, "footer", MUTED)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def _component(table, urls):
    """The component-embed payload: the stacked images as one preview."""
    parts = [{"type": 10, "content": f"## **{table.title}**\n{table.intro}"}]
    if table.gone:
        gone = ", ".join(name.replace("`", "'") for name in table.gone[:12])
        parts.append({"type": 10,
                      "content": f"-# No runs this season: {gone}"})
    for i, url in enumerate(urls[:MAX_IMAGES]):
        parts.append({"type": 12, "items": [
            {"media": {"url": url},
             "description": f"part {i + 1} of the table"}]})
    if len(urls) > MAX_IMAGES:
        parts.append({"type": 10, "content":
                      f"-# …and {len(urls) - MAX_IMAGES} more parts"
                      " on the page"})
    parts.append({"type": 10, "content": f"-# {table.footer}"})
    payload = json.dumps({"component": {
        "type": 17, "accent_color": int(ACCENT[1:], 16),
        "components": parts}}, separators=(",", ":"))
    while len(payload) > 2950 and len(parts) > 3:  # Discord caps at 3000
        parts.pop(max(1, len(parts) - 2))
        payload = json.dumps({"component": {
            "type": 17, "accent_color": int(ACCENT[1:], 16),
            "components": parts}}, separators=(",", ":"))
    return payload


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta property="og:site_name" content="Union Raid">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{intro}">
<meta property="og:image" content="{image}">
{dims}
<meta property="og:url" content="{url}">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="{accent}">
<script id="discord:component-embed" type="application/json">{payload}</script>
<style>
body{{background:#1e1f22;color:#dbdee1;font:15px/1.5 system-ui,sans-serif;
margin:0;padding:2rem 1rem}}
main{{max-width:52rem;margin:0 auto}}
img{{display:block;width:100%;border-radius:.5rem;margin:1rem 0}}
.intro{{color:#949ba4}}
footer{{color:#949ba4;font-size:.85rem;margin-top:1rem}}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<p class="intro">{intro}</p>
{images}
{gone}
<footer>{footer}</footer>
</main>
</body>
</html>
"""


def page(table, base, params):
    """The page Discord reads: Open Graph tags, the component payload and
    the images, so the link opens the same sheet for people."""
    query = urlencode(params)
    chunk = f"?{query}&chunk=" if query else "?chunk="
    count = len(chunk_rows(table))
    urls = [f"{base}/card.png{chunk}{i}" for i in range(count)]
    title = html.escape(table.title)
    intro = html.escape(table.intro.replace("**", ""))
    try:
        width, height, _, _ = _layout(table)
        dims = (f'<meta property="og:image:width" content="{width}">'
                f'<meta property="og:image:height" content="{height}">')
    except CardError:
        dims = ""    # optional: Discord measures the image without them
    # `base` may be the request's Host header: every URL is escaped so it
    # cannot break out of the attribute or element it is written into.
    # (The payload keeps them raw: JSON escapes are its own protection.)
    srcs = [html.escape(f"/card.png{chunk}{i}") for i in range(count)]
    images = "\n".join(
        f'<img src="{src}" alt="part {i + 1} of the table">'
        for i, src in enumerate(srcs))
    gone = ('<p class="intro">No runs this season: '
            + html.escape(", ".join(table.gone)) + "</p>") \
        if table.gone else ""
    # < would let a nickname close the script tag; JSON escapes are safe.
    payload = _component(table, urls).replace("<", "\\u003c")
    return PAGE.format(
        title=title, intro=intro, image=html.escape(urls[0]), dims=dims,
        url=html.escape(f"{base}/card?{query}"), accent=ACCENT,
        payload=payload, images=images, gone=gone,
        footer=html.escape(table.footer))
