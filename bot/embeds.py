# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discord embeds built from the raid server's JSON.

The ranking rows come from `blablalink_union_raid.sheet`; this module only
paints them as ANSI-coloured text and wraps them in embeds.
"""

import discord

from blablalink_union_raid import sheet

COLOUR = discord.Colour(0xF2A900)
BODY = 4000   # an embed description holds 4096 characters
BUDGET = 5500  # a message holds 6000 characters of embeds

# The ranking rules live in the shared module; these stay as its aliases.
Empty = sheet.Empty
short = sheet.short
change = sheet.change
counts = sheet.counts
day_ranking = sheet.day_ranking
last_day = sheet.last_day
SHEET = sheet.SHEET
SHEET_LEFT = sheet.SHEET_LEFT

ESC = "\u001b"
RESET = f"{ESC}[0m"
ANSI = {"green": 32, "red": 31, "yellow": 33, "blue": 34, "grey": 30}
NAME_WIDTH = 12


def paint(text, colour):
    return f"{ESC}[0;{ANSI[colour]}m{text}{RESET}" if colour else text


def clip(text, width=NAME_WIDTH):
    text = text.replace("`", "'")
    return text if len(text) <= width else text[:width - 1] + "…"


def table_lines(header, left, rows):
    """(header line, row lines) of a monospace table with coloured cells.

    Each row is (cells, colours per cell); widths come from the plain text.
    """
    cells = [header] + [[str(c) for c in r[0]] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(header))]

    def line(texts, colours):
        out = []
        for i, (text, width) in enumerate(zip(texts, widths)):
            padded = text.ljust(width) if i in left else text.rjust(width)
            out.append(paint(padded, colours[i] if colours else None))
        return "  ".join(out).rstrip()
    return line(header, None), [line(t, r[1]) for t, r in zip(cells[1:], rows)]


def block(header, left, rows):
    head, body = table_lines(header, left, rows)
    return "```ansi\n" + "\n".join([head] + body) + "\n```"


def grid(title, intro, header, left, rows, footer):
    """The table as embeds, split into complete code blocks as needed."""
    head, body = table_lines(header, left, rows)
    fence = len("```ansi\n\n```")
    kept, used = [], len(intro) + len(head)
    for text in body:
        if used + len(text) + 1 > BUDGET:
            kept.append(f"…and {len(body) - len(kept)} more")
            break
        kept.append(text)
        used += len(text) + 1
    chunks, current = [], []
    for text in kept:
        if sum(len(t) + 1 for t in current) + len(text) + len(head) + fence \
                + len(intro) > BODY:
            chunks.append(current)
            current = []
        current.append(text)
    chunks.append(current)
    result = []
    for i, chunk in enumerate(chunks):
        text = "\n".join([head] + chunk)
        result.append(discord.Embed(
            title=title if i == 0 else None,
            description=(intro if i == 0 else "") + f"```ansi\n{text}\n```",
            colour=COLOUR))
    result[-1].set_footer(text=footer)
    return result


def _grid(table):
    """A sheet as embeds, with the IGN column clipped to fit the block."""
    ign = table.header.index("IGN") if "IGN" in table.header else None
    rows = [(( [clip(cell) if i == ign else cell
                for i, cell in enumerate(cells)], colours))
            for cells, colours in table.rows]
    return grid(table.title, f"{table.intro}\n", table.header, table.left,
                rows, table.footer)


def day(data, number):
    """One day, with the change since the day before."""
    return _grid(sheet.day(data, number))


def season(data):
    """The season's last day, compared with the same day of the season before."""
    return _grid(sheet.season(data))


HISTORY = ["Season", "#", "Att", "Dmg (M)", "Chg", "Remark"]
HISTORY_LEFT = {0, 4, 5}
SEASONS_SHOWN = 12


def history(data, name):
    """One member's final-day result in each season, newest first.

    The member is found by name, ignoring case; the rank is the one the
    season sheet shows for the season's last day, and the change is against
    the season stored just before.
    """
    wanted = name.strip().casefold()
    results, before, taken_part = [], None, False
    for season in data["seasons"]:
        members = season["members"]
        number = last_day(members)
        played, full = day_ranking(members, number) if number else ([], 0)
        in_season = any(m["member"].strip().casefold() == wanted
                        for m in members)
        taken_part = taken_part or in_season
        hit = next(((rank, entry) for rank, (m, entry)
                    in enumerate(played, 1)
                    if m["member"].strip().casefold() == wanted), None)
        if in_season:
            attempts, finishers = counts(hit[1]) if hit else (0, 0)
            results.append({
                "season": season["name"], "full": full,
                "rank": hit[0] if hit else None, "attempts": attempts,
                "damage": hit[1]["total"] if hit else 0,
                "finishers": finishers, "before": before})
        before = hit[0] if hit else None
    if not taken_part:
        raise Empty(f"No Union Raid member named {name.strip()!r} found. Set "
                    "your server nickname to your in-game name and try again.")
    rows = []
    for r in reversed(results):
        if r["rank"] is None:
            sign, colour = "-", "grey"
        elif r["before"] is None:
            sign, colour = "-", "grey"
        else:
            sign, colour = change(r["before"], r["rank"])
        missed = r["attempts"] < r["full"]
        rows.append((
            [r["season"], r["rank"] or "-", f"{r['attempts']}/{r['full']}",
             r["damage"] // 10**6, sign,
             f"Finisher x{r['finishers']}" if r["finishers"] else
             "No runs" if r["rank"] is None else ""],
            [None, None, "red" if missed else None, None, colour,
             "blue" if r["finishers"] else "red" if r["rank"] is None
             else None]))
    ranked = [r for r in results if r["rank"]]
    intro = f"**{len(results)} seasons**"
    if ranked:
        best = min(ranked, key=lambda r: r["rank"])
        average = sum(r["rank"] for r in ranked) / len(ranked)
        intro += (f" · best rank {best['rank']} ({best['season']})"
                  f" · average {average:.1f}")
    return grid(f"{clip(name.strip(), 32)} · Union Raid history", intro + "\n",
                HISTORY, HISTORY_LEFT, rows[:SEASONS_SHOWN],
                "Rank on each season's final day · matched on your nickname")


RUNS = ["Day", "Run", "Boss", "Dmg (M)", "Remark"]
RUNS_LEFT = {2, 4}
MAX_RUNS = 30


def member(data):
    members = data["members"]
    if not members:
        raise Empty("No member matches that name.")
    compared = data["compared_with"]
    result = []
    for index, m in enumerate(members[:3], 1):  # 6000 characters per message
        previous = m.get("previous") or {}
        rank = m.get("rank") or index
        if compared and previous.get("rank"):
            sign, colour = change(previous["rank"], rank)
        elif compared:
            sign, colour = "New!", "yellow"
        else:
            sign, colour = "-", "grey"
        attempts, finishers = counts(m)
        summary = block(SHEET, SHEET_LEFT, [(
            [rank, clip(m["member"]), attempts, m["total"] // 10**6, sign,
             f"Finisher x{finishers}" if finishers else ""],
            [None, None, None, None, colour,
             "blue" if finishers else None])])
        rows = [([day, r["run"], clip(r["boss"], 18), r["damage"] // 10**6,
                  "Finisher" if r["final_hit"] else ""],
                 [None, None, None, None, "blue" if r["final_hit"] else None])
                for day, entry in m["days"].items() for r in entry["runs"]]
        text = f"Lv {m['level']}\n" if m.get("level") else ""
        text += summary
        if rows:
            text += "\n" + block(RUNS, RUNS_LEFT, rows[:MAX_RUNS])
        if len(rows) > MAX_RUNS:
            text += f"\n…and {len(rows) - MAX_RUNS} more runs"
        result.append(discord.Embed(
            title=f"{m['member']} · {data['season']}", description=text,
            colour=COLOUR))
    footer = f"Updated {data['ingested_at']}"
    if len(members) > 3:
        footer += f" · {len(members)} match, showing 3: be more specific"
    result[-1].set_footer(text=footer)
    return result


def compare(data):
    table = sheet.compare(data)
    result = _grid(table)
    if table.gone:
        result[-1].add_field(name="No runs this season", value=", ".join(
            discord.utils.escape_markdown(name)
            for name in table.gone)[:1000], inline=False)
    return result
