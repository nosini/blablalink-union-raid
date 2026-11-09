# SPDX-License-Identifier: AGPL-3.0-or-later

"""Turn the Union Raid API data into per-member, per-run damage.

The API returns one row per run in `participate_data`; the website groups
them by member the same way (its shiftyspad union raid page).
"""

from dataclasses import dataclass, field


class DataError(ValueError):
    """The input isn't Union Raid data."""


@dataclass
class Run:
    day: int            # 1-based, the API counts from 0
    number: int         # 1-based run of this member on this day
    difficulty: int
    level: int
    boss_id: int
    boss_name: str
    step: int
    damage: int
    final_hit: bool
    squad: list = field(default_factory=list)  # [{tid, costume_id, lv, combat}]
    element_id: int = 0
    icon_id: int = 0
    monster_model_id: int = 0


@dataclass
class Member:
    openid: str
    nickname: str
    runs: list = field(default_factory=list)

    @property
    def total(self):
        return sum(run.damage for run in self.runs)

    def day_runs(self, day):
        return [run for run in self.runs if run.day == day]

    def day_total(self, day):
        return sum(run.damage for run in self.day_runs(day))


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def boss_name(localvalues, lang="en"):
    if isinstance(localvalues, dict):
        return localvalues.get(lang) or localvalues.get("en") or "Unknown Boss"
    return "Unknown Boss"


def find_rows(data):
    """Return the `participate_data` list from an API response or its data."""
    if isinstance(data, dict):
        if isinstance(data.get("participate_data"), list):
            return data["participate_data"]
        if isinstance(data.get("data"), dict):
            return find_rows(data["data"])
    raise DataError("no 'participate_data' list found; expected the response "
                    "of GetUnionRaidData or GetUnionRaidDataOfGuildSeason")


def parse(data, lang="en"):
    """Group the runs by member. Members are sorted by total damage."""
    members = {}
    per_day = {}
    for row in find_rows(data):
        openid = str(row.get("openid", ""))
        member = members.setdefault(
            openid, Member(openid, row.get("nickname") or "Player"))
        day = _int(row.get("day")) + 1
        number = per_day[openid, day] = per_day.get((openid, day), 0) + 1
        member.runs.append(Run(
            day=day,
            number=number,
            difficulty=_int(row.get("difficulty")),
            level=_int(row.get("level")),
            boss_id=_int(row.get("boss_id")),
            boss_name=boss_name(row.get("name_localvalues"), lang),
            step=_int(row.get("step")),
            damage=_int(row.get("total_damage")),
            final_hit=bool(row.get("is_final_hit")),
            squad=row.get("squad") or [],
            element_id=_int(row.get("element_id")),
            icon_id=_int(row.get("icon_id")),
            monster_model_id=_int(row.get("monster_model_id")),
        ))
    return sorted(members.values(), key=lambda m: (-m.total, m.nickname))


def days(members):
    return sorted({run.day for member in members for run in member.runs})
