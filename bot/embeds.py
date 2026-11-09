# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discord embeds built from the raid server's JSON."""

import discord

COLOUR = discord.Colour(0xF2A900)
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
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


def signed(n):
    return f"{'+' if n >= 0 else '-'}{short(abs(n))}"


def name(text):
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text))


def place(rank):
    return MEDALS.get(rank) or f"`{rank:>2}`"


def move(status):
    """A short sign for 'up 2', 'down 1', 'new'; nothing for 'same'."""
    kind, _, count = status.partition(" ")
    return {"up": f" 🟢▲{count}", "down": f" 🔴▼{count}",
            "new": " 🆕"}.get(kind, "")


def pages(title, intro, lines, footer):
    """Embeds with the lines spread over as many as needed, within limits."""
    kept, used = [], len(intro)
    for line in lines:
        if used + len(line) + 1 > BUDGET:
            kept.append(f"…and {len(lines) - len(kept)} more")
            break
        kept.append(line)
        used += len(line) + 1
    texts, text = [], intro
    for line in kept:
        if len(text) + len(line) + 1 > BODY:
            texts.append(text)
            text = ""
        text += ("\n" if text else "") + line
    texts.append(text)
    result = [discord.Embed(title=title if i == 0 else None, description=t,
                            colour=COLOUR) for i, t in enumerate(texts)]
    result[-1].set_footer(text=footer)
    return result


ESC = "\u001b"
RESET = f"{ESC}[0m"
COLOURS = {"green": 32, "red": 31, "yellow": 33, "blue": 34, "grey": 30}
HEADER = ["#", "IGN", "Att", "Damage (M)", "Chg", "Remark"]
LEFT = {1, 4, 5}
NAME_WIDTH = 14


def paint(text, colour):
    return f"{ESC}[0;{COLOURS[colour]}m{text}{RESET}" if colour else text


def clip(text):
    text = text.replace("`", "'")
    return text if len(text) <= NAME_WIDTH else text[:NAME_WIDTH - 1] + "…"


def change(previous, current):
    """('↑2', 'green') for a move up, comparing two ranks; None: no earlier."""
    if previous is None:
        return "-", "grey"
    if current < previous:
        return f"↑{previous - current}", "green"
    if current > previous:
        return f"↓{current - previous}", "red"
    return "-", "grey"


def grid(title, intro, rows, footer):
    """Rows of (cells, colours-per-cell) as monospace tables in embeds.

    Colours use Discord's ansi code blocks; widths come from the plain text.
    """
    cells = [HEADER] + [[str(c) for c in r[0]] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(HEADER))]

    def line(texts, colours):
        out = []
        for i, (text, width) in enumerate(zip(texts, widths)):
            padded = text.ljust(width) if i in LEFT else text.rjust(width)
            out.append(paint(padded, colours[i] if colours else None))
        return "  ".join(out).rstrip()
    head = line(HEADER, None)
    body = [line(texts, r[1]) for texts, r in zip(cells[1:], rows)]
    fence = len("```ansi\n\n```")
    kept, used = [], len(intro) + len(head)
    for text in body:
        if used + len(text) + 1 > BUDGET:
            kept.append("…" + f"and {len(body) - len(kept)} more")
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
        table = "\n".join([head] + chunk)
        result.append(discord.Embed(
            title=title if i == 0 else None,
            description=(intro if i == 0 else "") + f"```ansi\n{table}\n```",
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
    return grid(f"Union Raid · {data['season']}", intro, rows, footer)


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
    return grid(f"Union Raid · {data['season']} · day {number}", intro, rows,
                f"Updated {data['ingested_at']}")


def member(data):
    members = data["members"]
    if not members:
        raise Empty("No member matches that name.")
    embeds = []
    for m in members[:3]:  # a message holds 6000 characters of embeds
        previous = m.get("previous") or {}
        top = f"**{short(m['total'])}** total"
        if m.get("rank"):
            top += f" · rank **{m['rank']}**"
            top += move(previous.get("status", ""))
        if m.get("level"):
            top += f" · Lv {m['level']}"
        embed = discord.Embed(title=f"{m['member']} · {data['season']}",
                              description=top, colour=COLOUR)
        for key, entry in list(m["days"].items())[:25]:
            lines = [f"{r['run']}. {r['boss']} · {short(r['damage'])}"
                     + (" ☠️" if r["final_hit"] else "")
                     for r in entry["runs"]]
            embed.add_field(
                name=f"Day {key} · {short(entry['total'])}",
                value="\n".join(lines) or "-", inline=False)
        embeds.append(embed)
    footer = f"Updated {data['ingested_at']}"
    if len(members) > 3:
        footer += f" · {len(members)} match, showing 3: be more specific"
    embeds[-1].set_footer(text=footer)
    return embeds


def compare(data):
    members = data["members"]
    lines, gone = [], []
    for m in members:
        if m["rank"] is None:
            gone.append(f"{name(m['member'])} (was #{m['prev_rank']})")
            continue
        line = f"{place(m['rank'])} **{name(m['member'])}** · " \
               f"{short(m['total'])}{move(m['status'])}"
        if m["prev_rank"]:
            line += f" ({signed(m['delta'])})"
            if m["level_change"]:
                line += f" · Lv {m['level']} (+{m['level_change']})"
        lines.append(line)
    if not lines:
        raise Empty("Neither season has runs.")
    intro = f"**{short(sum(m['total'] for m in members))}** union total\n"
    footer = "Damage change is against the earlier season"
    result = pages(f"Union Raid · {data['from']} → {data['to']}", intro,
                   lines, footer)
    if gone:
        result[-1].add_field(name="No runs this season",
                             value=", ".join(gone)[:1000], inline=False)
    return result
