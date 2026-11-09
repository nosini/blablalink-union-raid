# SPDX-License-Identifier: AGPL-3.0-or-later

"""Compare two seasons: who moved up or down in the damage ranking."""

import csv
from dataclasses import dataclass
import io
import json


@dataclass
class Change:
    openid: str
    nickname: str
    rank: int | None        # None: didn't take part in the newer season
    prev_rank: int | None   # None: didn't take part in the older season
    total: int
    prev_total: int

    @property
    def move(self):
        """Places gained (positive) or lost (negative); None if not in both."""
        if self.rank is None or self.prev_rank is None:
            return None
        return self.prev_rank - self.rank

    @property
    def delta(self):
        return self.total - self.prev_total

    @property
    def status(self):
        if self.prev_rank is None:
            return "new"
        if self.rank is None:
            return "absent"
        if self.move > 0:
            return f"up {self.move}"
        if self.move < 0:
            return f"down {-self.move}"
        return "same"


def _ranks(members):
    """Rank by total damage, best first. Members are already sorted."""
    ordered = sorted(members, key=lambda m: (-m.total, m.nickname))
    return {m.openid: (i, m) for i, m in enumerate(ordered, 1)}


def compare(old, new):
    """Changes for everyone in either season, by current rank, then leavers."""
    before, after = _ranks(old), _ranks(new)
    changes = []
    for openid in before.keys() | after.keys():
        rank, member = after.get(openid, (None, None))
        prev_rank, prev_member = before.get(openid, (None, None))
        changes.append(Change(
            openid=openid,
            nickname=(member or prev_member).nickname,
            rank=rank,
            prev_rank=prev_rank,
            total=member.total if member else 0,
            prev_total=prev_member.total if prev_member else 0,
        ))
    return sorted(changes, key=lambda c: (
        c.rank is None, c.rank or 0, c.prev_rank or 0, c.nickname))


def table(changes, old_name, new_name):
    header = ["Member", "Rank", "Was", "Move", "Total", "Was", "Change"]
    rows = [[c.nickname,
             "-" if c.rank is None else str(c.rank),
             "-" if c.prev_rank is None else str(c.prev_rank),
             c.status,
             f"{c.total:,}" if c.rank else "-",
             f"{c.prev_total:,}" if c.prev_rank else "-",
             f"{c.delta:+,}" if c.rank and c.prev_rank else ""]
            for c in changes]
    widths = [max(len(r[i]) for r in [header] + rows) for i in range(7)]

    def line(cells):
        return "  ".join(cell.ljust(w) if i in (0, 3) else cell.rjust(w)
                         for i, (cell, w) in enumerate(zip(cells, widths)))
    return "\n".join([f"{old_name} -> {new_name}", line(header)]
                     + [line(r) for r in rows])


def as_csv(changes):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["openid", "member", "rank", "prev_rank", "move",
                     "status", "total", "prev_total", "delta"])
    for c in changes:
        writer.writerow([c.openid, c.nickname,
                         "" if c.rank is None else c.rank,
                         "" if c.prev_rank is None else c.prev_rank,
                         "" if c.move is None else c.move, c.status,
                         c.total, c.prev_total, c.delta])
    return out.getvalue()


def as_json(changes, old_name, new_name):
    return json.dumps({
        "from": old_name, "to": new_name,
        "members": [{"openid": c.openid, "member": c.nickname,
                     "rank": c.rank, "prev_rank": c.prev_rank,
                     "move": c.move, "status": c.status,
                     "total": c.total, "prev_total": c.prev_total,
                     "delta": c.delta} for c in changes],
    }, indent=2, ensure_ascii=False)
