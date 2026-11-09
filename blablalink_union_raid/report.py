# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render members as a text table, CSV or JSON."""

import csv
import io
import json

from .model import days


def _runs(member, day):
    return [r.damage for r in member.day_runs(day)]


def table(members, day=None):
    """One table per day, then the season totals."""
    out = []
    for d in ([day] if day else days(members)):
        rows = sorted(((m.nickname, _runs(m, d), m.day_total(d))
                       for m in members if m.day_runs(d)),
                      key=lambda row: -row[2])
        width = max((len(r) for _, r, _ in rows), default=0)
        out.append(_render(f"Day {d}", rows, width))
    if not day:
        rows = [(m.nickname, [m.day_total(d) for d in days(members)], m.total)
                for m in members]
        out.append(_render("Season total (damage per day)", rows,
                           len(days(members)), prefix="D"))
    return "\n\n".join(out)


def _render(title, rows, width, prefix="Run "):
    header = ["Member"] + [f"{prefix}{i}" for i in range(1, width + 1)]
    header.append("Total")
    body = [[name] + [f"{v:,}" for v in runs] + [""] * (width - len(runs))
            + [f"{total:,}"] for name, runs, total in rows]
    cols = list(zip(header, *body))
    widths = [max(len(c) for c in col) for col in cols]
    lines = [title, "  ".join(
        h.ljust(w) if i == 0 else h.rjust(w)
        for i, (h, w) in enumerate(zip(header, widths)))]
    for row in body:
        lines.append("  ".join(
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(row, widths))))
    return "\n".join(lines)


def runs_csv(members, day=None):
    """Long form: one row per run."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["openid", "member", "day", "run", "boss", "difficulty",
                     "level", "damage", "final_hit"])
    for m in members:
        for r in m.runs:
            if day and r.day != day:
                continue
            writer.writerow([m.openid, m.nickname, r.day, r.number,
                             r.boss_name, r.difficulty, r.level, r.damage,
                             int(r.final_hit)])
    return out.getvalue()


def summary_csv(members, day=None):
    """Wide form: one row per member and day, runs side by side."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    width = max((r.number for m in members for r in m.runs), default=0)
    writer.writerow(["openid", "member", "day"]
                    + [f"run{i}" for i in range(1, width + 1)]
                    + ["day_total", "member_total"])
    for m in members:
        for d in days([m]):
            if day and d != day:
                continue
            runs = _runs(m, d)
            writer.writerow([m.openid, m.nickname, d] + runs
                            + [""] * (width - len(runs))
                            + [m.day_total(d), m.total])
    return out.getvalue()


def as_json(members, day=None):
    return json.dumps([{
        "openid": m.openid,
        "member": m.nickname,
        "total": m.total,
        "days": {str(d): {"runs": [{"run": r.number, "boss": r.boss_name,
                                    "damage": r.damage,
                                    "final_hit": r.final_hit}
                                   for r in m.day_runs(d)],
                          "total": m.day_total(d)}
                 for d in days([m]) if not day or d == day},
    } for m in members], indent=2, ensure_ascii=False)
