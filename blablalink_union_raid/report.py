# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render members as a text table, CSV or JSON.

With `previous` (the members of the season before), the season totals also
show each member's rank, how far they moved and the damage change.
"""

import csv
import io
import json

from .compare import compare as diff
from .model import days


def _runs(member, day):
    return [r.damage for r in member.day_runs(day)]


def _shown(members, only):
    """Members to display; ranks are always computed on the whole season."""
    return members if only is None else [m for m in members if m.openid in only]


def _changes(members, previous):
    if previous is None:
        return {}
    return {c.openid: c for c in diff(previous, members)}


def _grid(title, header, rows, left=(0,)):
    cols = list(zip(header, *rows))
    widths = [max(len(c) for c in col) for col in cols]

    def line(cells):
        return "  ".join(
            c.ljust(w) if i in left else c.rjust(w)
            for i, (c, w) in enumerate(zip(cells, widths))).rstrip()
    return "\n".join([title, line(header)] + [line(r) for r in rows])


def table(members, day=None, previous=None, previous_name="", only=None):
    """One table per day, then the season totals.

    The comparison belongs to the season totals, so it is left out when a
    single day is asked for.
    """
    out = []
    shown = _shown(members, only)
    for d in ([day] if day else days(shown)):
        rows = sorted(((m.nickname, _runs(m, d), m.day_total(d))
                       for m in shown if m.day_runs(d)),
                      key=lambda row: -row[2])
        width = max((len(r) for _, r, _ in rows), default=0)
        header = (["Member"] + [f"Run {i}" for i in range(1, width + 1)]
                  + ["Total"])
        body = [[name] + [f"{v:,}" for v in runs]
                + [""] * (width - len(runs)) + [f"{total:,}"]
                for name, runs, total in rows]
        out.append(_grid(f"Day {d}", header, body))
    if not day:
        out.append(_season(members, previous, previous_name, only))
    return "\n\n".join(out)


def _season(members, previous, previous_name, only=None):
    changes = _changes(members, previous)
    shown = _shown(members, only)
    ds = days(shown)
    compared = previous is not None
    header = (["#"] if compared else []) + ["Member"] \
        + [f"D{d}" for d in ds] + ["Total"] \
        + (["Was", "Move", "Change"] if compared else [])
    rows = []
    for m in shown:
        c = changes.get(m.openid)
        row = ([str(c.rank)] if compared else []) + [m.nickname] \
            + [f"{m.day_total(d):,}" for d in ds] + [f"{m.total:,}"]
        if compared:
            row += ["-" if c.prev_rank is None else str(c.prev_rank),
                    c.status,
                    f"{c.delta:+,}" if c.prev_rank else ""]
        rows.append(row)
    title = "Season total (damage per day)"
    if compared:
        title += f", compared with {previous_name}" if previous_name else \
            ", compared with the previous season"
    left = {1, len(header) - 2} if compared else {0}
    text = _grid(title, header, rows, left=left)
    absent = [c for c in changes.values()
              if c.rank is None and only is None]
    if absent:
        absent.sort(key=lambda c: c.prev_rank)
        text += "\n\nNo runs this season: " + ", ".join(
            f"{c.nickname} (was #{c.prev_rank})" for c in absent)
    return text


def runs_csv(members, day=None, previous=None, previous_name="", only=None):
    """Long form: one row per run."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["openid", "member", "day", "run", "boss", "difficulty",
                     "level", "damage", "final_hit", "element_id",
                     "monster_model_id", "squad"])
    for m in _shown(members, only):
        for r in m.runs:
            if day and r.day != day:
                continue
            writer.writerow([m.openid, m.nickname, r.day, r.number,
                             r.boss_name, r.difficulty, r.level, r.damage,
                             int(r.final_hit), r.element_id,
                             r.monster_model_id,
                             json.dumps(r.squad, separators=(",", ":"))])
    return out.getvalue()


def summary_csv(members, day=None, previous=None, previous_name="", only=None):
    """Wide form: one row per member and day, runs side by side."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    changes = _changes(members, previous)
    width = max((r.number for m in members for r in m.runs), default=0)
    writer.writerow(["openid", "member", "day"]
                    + [f"run{i}" for i in range(1, width + 1)]
                    + ["day_total", "member_total"]
                    + (["rank", "prev_rank", "move", "prev_total"]
                       if previous is not None else []))
    for m in _shown(members, only):
        c = changes.get(m.openid)
        for d in days([m]):
            if day and d != day:
                continue
            runs = _runs(m, d)
            row = ([m.openid, m.nickname, d] + runs
                   + [""] * (width - len(runs))
                   + [m.day_total(d), m.total])
            if previous is not None:
                row += [c.rank, "" if c.prev_rank is None else c.prev_rank,
                        "" if c.move is None else c.move, c.prev_total]
            writer.writerow(row)
    return out.getvalue()


def as_json(members, day=None, previous=None, previous_name="", only=None):
    changes = _changes(members, previous)
    result = []
    for m in _shown(members, only):
        entry = {
            "openid": m.openid,
            "member": m.nickname,
            "total": m.total,
            "icon_id": next((r.icon_id for r in m.runs), 0),
            "days": {str(d): {"runs": [{"run": r.number, "boss": r.boss_name,
                                        "damage": r.damage,
                                        "final_hit": r.final_hit,
                                        "element_id": r.element_id,
                                        "squad": r.squad}
                                       for r in m.day_runs(d)],
                              "total": m.day_total(d)}
                     for d in days([m]) if not day or d == day},
        }
        if previous is not None:
            c = changes[m.openid]
            entry["compared_with"] = previous_name
            entry["rank"] = c.rank
            entry["previous"] = {"rank": c.prev_rank, "total": c.prev_total,
                                 "move": c.move, "status": c.status,
                                 "delta": c.delta}
        result.append(entry)
    return json.dumps(result, indent=2, ensure_ascii=False)
