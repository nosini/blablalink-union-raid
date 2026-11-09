# SPDX-License-Identifier: AGPL-3.0-or-later

import contextlib
import io
import json
import os
from pathlib import Path
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

    def test_resave_replaces_and_keeps_place(self):
        store = Store(self.path)
        store.save("s1", parse(OLD))
        store.save("s2", parse(NEW))
        self.assertTrue(store.save("s1", parse(NEW)))
        self.assertEqual(store.names(), ["s1", "s2"])
        self.assertEqual(len(store.load("s1")), 3)  # not 6

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
