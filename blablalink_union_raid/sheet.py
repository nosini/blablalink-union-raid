# SPDX-License-Identifier: AGPL-3.0-or-later

"""The union leader's sheet: the ranking rows every renderer shows.

The bot turns these rows into ANSI-coloured text; the card page renders
them as PNG images for Discord link previews. Both read the same rows from
here, so the ranking rules live in exactly one place.

The input is the JSON the server's GET endpoints produce (`report` and
`compare` with `?format=json`), the same the bot fetches.

Rows are `(cells, colours per cell)`, where a colour is one of the keys of
`COLOURS` in `card.py` or None for the default. `intro` is one markdown
line; the plain-text renderers drop the markup.
"""

from dataclasses import dataclass, field


class Empty(ValueError):
    """Nothing to show; the message is for the user."""


SHEET = ["#", "IGN", "Att", "Dmg (M)", "Chg", "Remark"]
SHEET_LEFT = {1, 4, 5}
COMPARE = ["#", "IGN", "Dmg (M)", "Chg", "Δ (M)", "Remark"]
COMPARE_LEFT = {1, 3, 5}


@dataclass
class Sheet:
    title: str
    intro: str            # one markdown line, shown above the table
    header: list
    left: set            # column indexes aligned to the left
    rows: list            # [(cells, colours per cell)]
    footer: str
    gone: list = field(default_factory=list)  # compare: who has no runs


def short(n):
    for size, unit, digits in ((10**9, "B", 2), (10**6, "M", 1),
                               (10**3, "K", 0)):
        if abs(n) >= size:
            return f"{n / size:.{digits}f}{unit}"
    return str(n)


def change(previous, current):
    """('↑2', 'green') for a move up, comparing two ranks; None: no earlier."""
    if previous is None:
        return "-", "grey"
    if current < previous:
        return f"↑{previous - current}", "green"
    if current > previous:
        return f"↓{current - previous}", "red"
    return "-", "grey"


def counts(entry_or_member):
    """(attempts, finishing blows) of a day entry or of a member's season."""
    entries = entry_or_member["days"].values() if "days" in entry_or_member \
        else [entry_or_member]
    runs = [r for e in entries for r in e["runs"]]
    return len(runs), sum(1 for r in runs if r["final_hit"])


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


def ranks(members, number):
    """openid -> rank of a day, in the order the sheet uses."""
    return {m["openid"]: i for i, (m, _) in
            enumerate(day_ranking(members, number)[0], 1)}


def last_day(members):
    return max((int(d) for m in members for d in m["days"]), default=0)


def _day_sheet(data, number, before, note):
    """The sheet for one day; `before` maps openid to an earlier rank.

    With nothing to compare against (None or empty) every change is '-'.
    """
    played, full = day_ranking(data["members"], number)
    if not played:
        raise Empty(f"No runs on day {number} of {data['season']}.")
    rows = []
    for rank, (m, entry) in enumerate(played, 1):
        attempts, finishers = counts(entry)
        if not before:
            sign, colour = "-", "grey"
        elif m["openid"] not in before:
            sign, colour = "New!", "yellow"
        else:
            sign, colour = change(before[m["openid"]], rank)
        rows.append(([rank, m["member"], f"{attempts}/{full}",
                      entry["total"] // 10**6, sign,
                      f"Finisher x{finishers}" if finishers else ""],
                     [None, None, "red" if attempts < full else None, None,
                      colour, "blue" if finishers else None]))
    total = sum(e["total"] for _, e in played)
    intro = f"**Day total** {short(total)} · {len(played)} members"
    footer = f"Updated {data['ingested_at']}"
    if note:
        footer += f" · changes against {note}"
    return Sheet(f"Union Raid · {data['season']} · day {number}", intro,
                 SHEET, SHEET_LEFT, rows, footer)


def day(data, number):
    """One day, with the change since the day before."""
    before = ranks(data["members"], number - 1) if number > 1 else None
    return _day_sheet(data, number, before,
                     f"day {number - 1}" if before else "")


def season(data):
    """The season's last day, compared with the same day of the season before."""
    number = last_day(data["members"])
    if not number:
        raise Empty("That season has no runs.")
    previous = data["compared_with"]
    before = ranks(data["previous_members"], number) if previous else None
    return _day_sheet(data, number, before,
                     f"{previous} day {number}" if before else "")


def compare(data):
    """Rank changes between two seasons, from the compare endpoint's JSON."""
    rows, gone = [], []
    for m in data["members"]:
        if m["rank"] is None:
            gone.append(f"{m['member']} (was #{m['prev_rank']})")
            continue
        if m["prev_rank"]:
            sign, colour = change(m["prev_rank"], m["rank"])
            delta = f"{m['delta'] // 10**6:+}"
        else:
            sign, colour, delta = "New!", "yellow", ""
        gain = m["level_change"]
        remark = f"Lv {m['level']}" + (f" ({gain:+})" if gain else "") \
            if m["level"] else ""
        rows.append(([m["rank"], m["member"], m["total"] // 10**6, sign,
                      delta, remark],
                     [None, None, None, colour,
                      "green" if delta.startswith("+") else
                      "red" if delta.startswith("-") else None, None]))
    if not rows:
        raise Empty("Neither season has runs.")
    total = sum(m["total"] for m in data["members"])
    return Sheet(f"Union Raid · {data['from']} → {data['to']}",
                 f"**Union total** {short(total)}", COMPARE, COMPARE_LEFT,
                 rows, "Change is against the earlier season", gone)
