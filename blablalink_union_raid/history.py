# SPDX-License-Identifier: AGPL-3.0-or-later

"""Keep the runs of every ingested season in a local SQLite database.

The database holds member names and openids, so it lives in the user's data
directory (not in this repository) and is only readable by the user.
"""

import json
import os
from pathlib import Path
import re
import sqlite3
import time

from .model import Member, Run

SCHEMA = """
CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    openid TEXT NOT NULL,
    nickname TEXT NOT NULL,
    day INTEGER NOT NULL,
    number INTEGER NOT NULL,
    boss_id INTEGER NOT NULL,
    boss_name TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    level INTEGER NOT NULL,
    step INTEGER NOT NULL,
    damage INTEGER NOT NULL,
    final_hit INTEGER NOT NULL,
    monster_model_id INTEGER NOT NULL DEFAULT 0,
    squad TEXT NOT NULL DEFAULT '[]',
    elements TEXT NOT NULL DEFAULT '[]',
    boss_icon TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_season ON runs(season_id);
"""


# Columns added after the first version; older databases get them on open.
ADDED_COLUMNS = {
    "monster_model_id": "INTEGER NOT NULL DEFAULT 0",
    "squad": "TEXT NOT NULL DEFAULT '[]'",
    "elements": "TEXT NOT NULL DEFAULT '[]'",
    "boss_icon": "TEXT NOT NULL DEFAULT ''",
}
# Columns of an intermediate version that read these fields wrongly (it took
# the element list and the boss icon name for numbers); they only hold zeros.
DROPPED_COLUMNS = ("element_id", "icon_id")


class HistoryError(RuntimeError):
    pass


def season_order(name):
    """Sort key putting '2026-09' before '2026-10' and 'S9' before 'S10'."""
    # re.split alternates text and number, so keys of different names
    # compare text with text and number with number.
    return [int(part) if part.isdigit() else part
            for part in re.split(r"(\d+)", name)]


def default_path():
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share"
    return Path(base) / "blablalink-union-raid" / "history.sqlite3"


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Create the file private before SQLite does with default permissions.
        os.close(os.open(self.path, os.O_CREAT | os.O_RDONLY, 0o600))
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        have = {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}
        with self.db:
            for column, definition in ADDED_COLUMNS.items():
                if column not in have:
                    self.db.execute(
                        f"ALTER TABLE runs ADD COLUMN {column} {definition}")
            for column in DROPPED_COLUMNS:
                if column in have:
                    self.db.execute(f"ALTER TABLE runs DROP COLUMN {column}")

    def close(self):
        self.db.close()

    def save(self, name, members):
        """Store a season. Saving a name again replaces its runs, keeping its
        place in the history, so a running season can be ingested repeatedly.
        """
        with self.db:
            row = self.db.execute(
                "SELECT id FROM seasons WHERE name = ?", (name,)).fetchone()
            if row:
                season_id = row[0]
                self.db.execute(
                    "DELETE FROM runs WHERE season_id = ?", (season_id,))
                self.db.execute(
                    "UPDATE seasons SET ingested_at = ? WHERE id = ?",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), season_id))
            else:
                season_id = self.db.execute(
                    "INSERT INTO seasons (name, ingested_at) VALUES (?, ?)",
                    (name, time.strftime("%Y-%m-%d %H:%M:%S"))).lastrowid
            self.db.executemany(
                "INSERT INTO runs (season_id, openid, nickname, day, number, "
                "boss_id, boss_name, difficulty, level, step, damage, "
                "final_hit, monster_model_id, squad, elements, boss_icon) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(season_id, m.openid, m.nickname, r.day, r.number,
                  r.boss_id, r.boss_name, r.difficulty, r.level, r.step,
                  r.damage, int(r.final_hit), r.monster_model_id,
                  json.dumps(r.squad), json.dumps(r.elements), r.boss_icon)
                 for m in members for r in m.runs])
        return bool(row)

    def seasons(self):
        """(name, ingested_at, members, total damage), oldest first.

        Oldest first means by name (see season_order), not by ingest time,
        so seasons can be ingested in any order.
        """
        rows = self.db.execute("""
            SELECT s.name, s.ingested_at, COUNT(DISTINCT r.openid),
                   COALESCE(SUM(r.damage), 0)
            FROM seasons s LEFT JOIN runs r ON r.season_id = s.id
            GROUP BY s.id""").fetchall()
        return sorted(rows, key=lambda row: season_order(row[0]))

    def names(self):
        return [row[0] for row in self.seasons()]

    def load(self, name):
        row = self.db.execute(
            "SELECT id FROM seasons WHERE name = ?", (name,)).fetchone()
        if not row:
            raise HistoryError(
                f"no season named {name!r}; stored: "
                f"{', '.join(self.names()) or 'none'}")
        members = {}
        for (openid, nickname, day, number, boss_id, boss_name, difficulty,
             level, step, damage, final_hit, monster_model_id, squad,
             elements, boss_icon) in self.db.execute(
                "SELECT openid, nickname, day, number, boss_id, boss_name, "
                "difficulty, level, step, damage, final_hit, "
                "monster_model_id, squad, elements, boss_icon FROM runs "
                "WHERE season_id = ? ORDER BY rowid", (row[0],)):
            member = members.setdefault(openid, Member(openid, nickname))
            member.runs.append(Run(
                day, number, difficulty, level, boss_id, boss_name, step,
                damage, bool(final_hit), json.loads(squad),
                json.loads(elements), boss_icon, monster_model_id))
        return sorted(members.values(), key=lambda m: (-m.total, m.nickname))
