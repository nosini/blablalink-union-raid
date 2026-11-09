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


def season(data):
    members = data["members"]
    if not members:
        raise Empty("That season has no runs.")
    compared = data["compared_with"]
    lines = []
    for index, m in enumerate(members, 1):
        rank = m.get("rank") or index
        line = f"{place(rank)} **{name(m['member'])}** · {short(m['total'])}"
        if compared and m.get("previous"):
            previous = m["previous"]
            line += move(previous["status"])
            if previous["rank"]:
                line += f" ({signed(previous['delta'])})"
        lines.append(line)
    intro = f"**Union total** {short(sum(m['total'] for m in members))}" \
            f" · {len(members)} members"
    footer = f"Updated {data['ingested_at']}"
    if compared:
        footer += f" · changes against {compared}"
    return pages(f"Union Raid · {data['season']}", intro + "\n", lines, footer)


def day(data, number):
    key = str(number)
    rows = sorted(((m["member"], m["days"][key]) for m in data["members"]
                   if key in m["days"]), key=lambda row: -row[1]["total"])
    if not rows:
        raise Empty(f"No runs on day {number} of {data['season']}.")
    lines = []
    for index, (who, entry) in enumerate(rows, 1):
        runs = " · ".join(short(r["damage"]) for r in entry["runs"])
        line = f"{place(index)} **{name(who)}** · {short(entry['total'])}"
        if len(entry["runs"]) > 1:
            line += f"\n⠀⠀{runs}"
        lines.append(line)
    intro = f"**Day total** {short(sum(e['total'] for _, e in rows))}" \
            f" · {len(rows)} members\n"
    return pages(f"Union Raid · {data['season']} · day {number}", intro,
                 lines, f"Updated {data['ingested_at']}")


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
