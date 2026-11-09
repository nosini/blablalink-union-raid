# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discord embeds built from the raid server's JSON."""

import discord

COLOUR = discord.Colour(0xF2A900)
BODY = 4000   # an embed description holds 4096 characters
BUDGET = 5500  # a message holds 6000 characters of embeds


class Empty(Exception):
    """Nothing to show; the message is for the user."""


def short(n):
    for size, unit, digits in ((10**9, "B", 2), (10**6, "M", 1),
                               (10**3, "K", 0)):
        if abs(n) >= size:
            return f"{n / size:.{digits}f}{unit}"
    return str(n)


ESC = "\u001b"
RESET = f"{ESC}[0m"
COLOURS = {"green": 32, "red": 31, "yellow": 33, "blue": 34, "grey": 30}
SHEET = ["#", "IGN", "Att", "Damage (M)", "Chg", "Remark"]
SHEET_LEFT = {1, 4, 5}
NAME_WIDTH = 14


def paint(text, colour):
    return f"{ESC}[0;{COLOURS[colour]}m{text}{RESET}" if colour else text


def clip(text, width=NAME_WIDTH):
    text = text.replace("`", "'")
    return text if len(text) <= width else text[:width - 1] + "…"


def change(previous, current):
    """('↑2', 'green') for a move up, comparing two ranks; None: no earlier."""
    if previous is None:
        return "-", "grey"
    if current < previous:
        return f"↑{previous - current}", "green"
    if current > previous:
        return f"↓{current - previous}", "red"
    return "-", "grey"


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


def counts(entry_or_member):
    """(attempts, finishing blows) of a day entry or of a member's season."""
    entries = entry_or_member["days"].values() if "days" in entry_or_member \
        else [entry_or_member]
    runs = [r for e in entries for r in e["runs"]]
    return len(runs), sum(1 for r in runs if r["final_hit"])


def season(data):
    members = data["members"]
    if not members:
        raise Empty("That season has no runs.")
    compared = data["compared_with"]
    rows = []
    for index, m in enumerate(members, 1):
        rank = m.get("rank") or index
        previous = m.get("previous") or {}
        if compared and previous.get("rank"):
            sign, colour = change(previous["rank"], rank)
        elif compared:
            sign, colour = "New!", "yellow"
        else:
            sign, colour = "-", "grey"
        attempts, finishers = counts(m)
        remark = f"Finisher x{finishers}" if finishers else ""
        rows.append(([rank, clip(m["member"]), attempts,
                      m["total"] // 10**6, sign, remark],
                     [None, None, None, None, colour,
                      "blue" if finishers else None]))
    intro = f"**Union total** {short(sum(m['total'] for m in members))}" \
            f" · {len(members)} members\n"
    footer = f"Updated {data['ingested_at']}"
    if compared:
        footer += f" · changes against {compared}"
    return grid(f"Union Raid · {data['season']}", intro, SHEET, SHEET_LEFT,
                rows, footer)


def day_ranking(members, number):
    """[(member, entry)] best first, and the attempts that count as full.

    Members who made every attempt come first, then the others, each by
    damage: the order the union leader's sheet uses.
    """
    key = str(number)
    played = [(m, m["days"][key]) for m in members if key in m["days"]]
    full = max((len(e["runs"]) for _, e in played), default=0)
    played.sort(key=lambda p: (len(p[1]["runs"]) < full, -p[1]["total"],
                               p[0]["member"]))
    return played, full


def day(data, number):
    played, full = day_ranking(data["members"], number)
    if not played:
        raise Empty(f"No runs on day {number} of {data['season']}.")
    before = {}
    if number > 1:
        before = {m["openid"]: i for i, (m, _) in
                  enumerate(day_ranking(data["members"], number - 1)[0], 1)}
    rows = []
    for rank, (m, entry) in enumerate(played, 1):
        attempts, finishers = counts(entry)
        if number == 1 or not before:
            sign, colour = "-", "grey"
        elif m["openid"] not in before:
            sign, colour = "New!", "yellow"
        else:
            sign, colour = change(before[m["openid"]], rank)
        remarks = []
        if attempts < full:
            remarks.append("Unfinished")
        if finishers:
            remarks.append(f"Finisher x{finishers}")
        rows.append(([rank, clip(m["member"]), attempts,
                      entry["total"] // 10**6, sign, " · ".join(remarks)],
                     [None, None, None, None, colour,
                      "red" if attempts < full else
                      "blue" if finishers else None]))
    total = sum(e["total"] for _, e in played)
    intro = f"**Day total** {short(total)} · {len(played)} members\n"
    return grid(f"Union Raid · {data['season']} · day {number}", intro, SHEET,
                SHEET_LEFT, rows, f"Updated {data['ingested_at']}")


RUNS = ["Day", "Run", "Boss", "Damage (M)", "Remark"]
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


COMPARE = ["#", "IGN", "Damage (M)", "Chg", "Change (M)", "Remark"]
COMPARE_LEFT = {1, 3, 5}


def compare(data):
    rows, gone = [], []
    for m in data["members"]:
        if m["rank"] is None:
            gone.append(f"{discord.utils.escape_markdown(m['member'])} "
                        f"(was #{m['prev_rank']})")
            continue
        if m["prev_rank"]:
            sign, colour = change(m["prev_rank"], m["rank"])
            delta = f"{m['delta'] // 10**6:+}"
        else:
            sign, colour, delta = "New!", "yellow", ""
        gain = m["level_change"]
        remark = f"Lv {m['level']}" + (f" ({gain:+})" if gain else "") \
            if m["level"] else ""
        rows.append(([m["rank"], clip(m["member"]), m["total"] // 10**6, sign,
                      delta, remark],
                     [None, None, None, colour,
                      "green" if delta.startswith("+") else
                      "red" if delta.startswith("-") else None, None]))
    if not rows:
        raise Empty("Neither season has runs.")
    total = sum(m["total"] for m in data["members"])
    result = grid(f"Union Raid · {data['from']} → {data['to']}",
                  f"**Union total** {short(total)}\n", COMPARE, COMPARE_LEFT,
                  rows, "Change is against the earlier season")
    if gone:
        result[-1].add_field(name="No runs this season",
                             value=", ".join(gone)[:1000], inline=False)
    return result
