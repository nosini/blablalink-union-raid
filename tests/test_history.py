# SPDX-License-Identifier: AGPL-3.0-or-later

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

from blablalink_union_raid import cli, compare
from blablalink_union_raid.history import HistoryError, Store
from blablalink_union_raid.model import Member, Run, parse

FIXTURES = Path(__file__).parent / "fixtures"
OLD = json.loads((FIXTURES / "season.json").read_text())
NEW = json.loads((FIXTURES / "season2.json").read_text())


def member(openid, name, *damage):
    return Member(openid, name, [Run(1, i, 1, 1, 1, "B", 1, d, False)
                                 for i, d in enumerate(damage, 1)])


class Compare(unittest.TestCase):
    def changes(self):
        return {c.nickname: c
                for c in compare.compare(parse(OLD), parse(NEW))}

    def test_moves(self):
        changes = self.changes()
        self.assertEqual((changes["Bob"].prev_rank, changes["Bob"].rank), (3, 1))
        self.assertEqual(changes["Bob"].status, "up 2")
        self.assertEqual(changes["Alice"].status, "down 2")
        self.assertEqual(changes["Alice"].delta, 1_000_000_000 - 3_900_000_000)

    def test_new_and_absent(self):
        changes = self.changes()
        self.assertEqual(changes["Dave"].status, "new")
        self.assertIsNone(changes["Dave"].move)
        self.assertEqual(changes["Carol"].status, "absent")
        self.assertIsNone(changes["Carol"].rank)

    def test_order_is_current_rank_then_absent(self):
        names = [c.nickname for c in compare.compare(parse(OLD), parse(NEW))]
        self.assertEqual(names, ["Bob", "Dave", "Alice", "Carol"])

    def test_same_rank(self):
        old = [member("a", "A", 10), member("b", "B", 5)]
        new = [member("a", "A", 20), member("b", "B", 6)]
        self.assertEqual({c.nickname: c.status
                          for c in compare.compare(old, new)},
                         {"A": "same", "B": "same"})

    def test_matches_by_openid_so_renames_follow(self):
        old = [member("a", "Old name", 10)]
        new = [member("a", "New name", 10)]
        (change,) = compare.compare(old, new)
        self.assertEqual((change.nickname, change.status), ("New name", "same"))

    def test_renderers(self):
        changes = compare.compare(parse(OLD), parse(NEW))
        self.assertIn("up 2", compare.table(changes, "a", "b"))
        self.assertEqual(compare.as_csv(changes).splitlines()[1].split(",")[:3],
                         ["o2", "Bob", "1"])
        self.assertEqual(json.loads(compare.as_json(changes, "a", "b"))["to"], "b")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data" / "history.sqlite3"

    def test_roundtrip(self):
        store = Store(self.path)
        self.assertFalse(store.save("s1", parse(OLD)))
        loaded = store.load("s1")
        self.assertEqual([m.nickname for m in loaded], ["Alice", "Carol", "Bob"])
        self.assertEqual(loaded[0].total, 3_900_000_000)
        self.assertEqual([r.damage for r in loaded[0].day_runs(1)],
                         [900_000_000, 1_200_000_000, 800_000_000])
        self.assertTrue(loaded[0].runs[2].final_hit)

    def test_extra_run_fields_roundtrip(self):
        store = Store(self.path)
        store.save("s1", parse(OLD))
        alice = store.load("s1")[0]
        run = alice.runs[0]                          # her first run
        self.assertEqual((run.elements, run.boss_icon, run.monster_model_id),
                         ([500001], "bbg001_boss_intercept", 152041))
        self.assertEqual(run.boss_id, 1520040151)
        self.assertEqual([c["slot"] for c in run.squad], [1, 2, 3, 4, 5])
        self.assertEqual((run.squad[0]["lv"], run.squad[0]["tid"]), (528, 301001))
        self.assertEqual(alice.level, 528)

    def test_old_database_is_migrated(self):
        self.path.parent.mkdir(parents=True)
        db = sqlite3.connect(self.path)
        db.executescript("""
            CREATE TABLE seasons (id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE, ingested_at TEXT NOT NULL);
            CREATE TABLE runs (season_id INTEGER NOT NULL, openid TEXT NOT NULL,
                nickname TEXT NOT NULL, day INTEGER NOT NULL,
                number INTEGER NOT NULL, boss_id INTEGER NOT NULL,
                boss_name TEXT NOT NULL, difficulty INTEGER NOT NULL,
                level INTEGER NOT NULL, step INTEGER NOT NULL,
                damage INTEGER NOT NULL, final_hit INTEGER NOT NULL);
            INSERT INTO seasons VALUES (1, 'old', '2026-11-09 20:00:00');
            INSERT INTO runs VALUES (1, 'o1', 'Alice', 1, 1, 1, 'Boss 1', 1, 1,
                1, 123, 0);""")
        db.commit()
        db.close()
        store = Store(self.path)                     # opens and migrates
        (run,) = store.load("old")[0].runs
        self.assertEqual((run.damage, run.elements, run.squad), (123, [], []))
        store.save("old", parse(OLD))                # re-ingest fills the data
        self.assertEqual(store.load("old")[0].runs[0].boss_icon,
                         "bbg001_boss_intercept")
        Store(self.path)                             # opening again is fine

    def test_intermediate_columns_are_dropped(self):
        store = Store(self.path)
        store.db.execute("ALTER TABLE runs ADD COLUMN element_id INTEGER DEFAULT 0")
        store.db.execute("ALTER TABLE runs ADD COLUMN icon_id INTEGER DEFAULT 0")
        store.db.commit()
        store.close()
        columns = {r[1] for r in Store(self.path).db.execute("PRAGMA table_info(runs)")}
        self.assertFalse({"element_id", "icon_id"} & columns)
        self.assertTrue({"elements", "boss_icon", "squad"} <= columns)

    def test_resave_replaces_and_keeps_place(self):
        store = Store(self.path)
        store.save("s1", parse(OLD))
        store.save("s2", parse(NEW))
        self.assertTrue(store.save("s1", parse(NEW)))
        self.assertEqual(store.names(), ["s1", "s2"])
        self.assertEqual(len(store.load("s1")), 3)  # not 6

    def test_seasons_are_ordered_by_name_not_ingest_time(self):
        store = Store(self.path)
        for name in ("2026-10", "S10", "2026-09", "S9", "S100", "S2"):
            store.save(name, parse(OLD))
        self.assertEqual(store.names(), ["2026-09", "2026-10", "S2", "S9",
                                         "S10", "S100"])

    def test_unknown_season(self):
        with self.assertRaisesRegex(HistoryError, "no season named 'x'"):
            Store(self.path).load("x")

    def test_files_are_private(self):
        Store(self.path)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)


class HistoryCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "h.sqlite3")

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(list(argv))
        return out.getvalue()

    def ingest(self, name, fixture):
        return self.run_cli("ingest", str(FIXTURES / fixture), "--season", name,
                            "--db", self.db)

    def test_ingest_seasons_compare(self):
        self.assertIn("stored season '2026-09'", self.ingest("2026-09", "season.json"))
        with self.assertRaisesRegex(SystemExit, "at least two"):
            self.run_cli("compare", "--db", self.db)
        self.ingest("2026-10", "season2.json")
        self.assertIn("replaced", self.ingest("2026-09", "season.json"))
        seasons = self.run_cli("seasons", "--db", self.db).splitlines()
        self.assertEqual([l.split()[0] for l in seasons], ["2026-09", "2026-10"])
        text = self.run_cli("compare", "--db", self.db)
        self.assertIn("2026-09 -> 2026-10", text)
        self.assertIn("up 2", text)
        swapped = self.run_cli("compare", "--from", "2026-10", "--to", "2026-09",
                               "--db", self.db, "--format", "csv")
        self.assertIn("o2,Bob,3,1,-2,down 2", swapped)

    def test_default_compare_ignores_ingest_order(self):
        self.ingest("2026-10", "season2.json")  # newer season first
        self.ingest("2026-09", "season.json")
        text = self.run_cli("compare", "--db", self.db)
        self.assertIn("2026-09 -> 2026-10", text)
        self.assertIn("up 2", text)

    def test_report_from_the_database(self):
        self.ingest("2026-09", "season.json")
        self.ingest("2026-10", "season2.json")
        latest = self.run_cli("report", "--db", self.db)
        self.assertIn("Dave", latest)
        self.assertRegex(latest, r"#\s+Member\s+Lv\s+D1")
        self.assertRegex(latest, r"1\s+Bob\s+522\s")
        self.assertIn("compared with 2026-09", latest)
        self.assertIn("No runs this season: Carol (was #2)", latest)
        old = self.run_cli("report", "--season", "2026-09", "--db", self.db,
                           "--format", "runs-csv", "--member", "carol")
        self.assertEqual(len(old.splitlines()), 1 + 1)
        self.assertIn("Day 2", self.run_cli("report", "--db", self.db, "--day", "2"))

    def test_report_compares_with_previous_season_by_default(self):
        self.ingest("2026-09", "season.json")
        self.ingest("2026-10", "season2.json")
        text = self.run_cli("report", "--db", self.db)
        self.assertRegex(text, r"1\s+Bob .*\s3\s+up 2\s+\+2,900,000,000")
        self.assertRegex(text, r"3\s+Alice .*\s1\s+down 2")
        self.assertIn("compared with", self.run_cli(
            "report", "--db", self.db, "--season", "2026-10"))
        # the first season has nothing before it; options turn it off or pick one
        self.assertNotIn("compared", self.run_cli(
            "report", "--db", self.db, "--season", "2026-09"))
        self.assertNotIn("compared", self.run_cli(
            "report", "--db", self.db, "--no-compare"))
        self.assertIn("compared with 2026-09", self.run_cli(
            "report", str(FIXTURES / "season2.json"), "--db", self.db,
            "--against", "2026-09"))
        self.assertNotIn("compared", self.run_cli(
            "report", str(FIXTURES / "season2.json"), "--db", self.db))

    def test_member_filter_keeps_season_ranks(self):
        self.ingest("2026-09", "season.json")
        self.ingest("2026-10", "season2.json")
        text = self.run_cli("report", "--db", self.db, "--member", "alice")
        self.assertRegex(text, r"3\s+Alice")      # rank 3 of the season, not 1
        self.assertNotIn("Bob", text)
        self.assertNotIn("No runs this season", text)
        csv_text = self.run_cli("report", "--db", self.db, "--member", "dave",
                                "--format", "summary-csv")
        self.assertEqual(csv_text.splitlines()[0].split(",")[-4:],
                         ["rank", "prev_rank", "move", "prev_total"])
        self.assertIn(",2,,,0", csv_text.splitlines()[1])
        data = json.loads(self.run_cli("report", "--db", self.db, "--member",
                                       "bob", "--format", "json"))
        self.assertEqual((data[0]["rank"], data[0]["previous"]["move"]), (1, 2))

    def test_report_database_errors(self):
        with self.assertRaisesRegex(SystemExit, "no seasons stored"):
            self.run_cli("report", "--db", self.db)
        self.ingest("a", "season.json")
        with self.assertRaisesRegex(SystemExit, "no season named 'x'"):
            self.run_cli("report", "--season", "x", "--db", self.db)
        with self.assertRaisesRegex(SystemExit, "not both"):
            self.run_cli("report", str(FIXTURES / "season.json"),
                         "--season", "a", "--db", self.db)

    def test_half_a_range_is_an_error(self):
        self.ingest("a", "season.json")
        self.ingest("b", "season2.json")
        with self.assertRaisesRegex(SystemExit, "both --from and --to"):
            self.run_cli("compare", "--from", "a", "--db", self.db)

    def test_default_location_follows_xdg_data_home(self):
        old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.tmp.name
        try:
            self.run_cli("ingest", str(FIXTURES / "season.json"), "--season", "x")
        finally:
            if old is None:
                del os.environ["XDG_DATA_HOME"]
            else:
                os.environ["XDG_DATA_HOME"] = old
        self.assertTrue((Path(self.tmp.name) /
                         "blablalink-union-raid/history.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
