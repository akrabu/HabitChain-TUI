# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.

from datetime import date
from pathlib import Path
import tempfile
import unittest

from habit_tracker.model import DAILY, WEEKLY, Tracker
from habit_tracker.storage import CSVStore, StorageError


class CSVStoreTests(unittest.TestCase):
    def test_csv_round_trip_preserves_habits_and_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "habits.csv"
            tracker = Tracker()
            first = tracker.add_habit(
                'Write,\n"quietly"', DAILY, 2, date(2026, 7, 1)
            )
            second = tracker.add_habit("Exercise", WEEKLY, 3, date(2026, 7, 2))
            tracker.set_count(first, date(2026, 7, 3), 2)
            tracker.set_count(second, date(2026, 7, 4), 1)

            store = CSVStore(path)
            store.save(tracker)
            loaded = store.load()

            self.assertEqual(
                [(habit.name, habit.schedule, habit.target) for habit in loaded.habits],
                [
                    ('Write,\n"quietly"', DAILY, 2),
                    ("Exercise", WEEKLY, 3),
                ],
            )
            self.assertEqual(
                loaded.raw_count(loaded.habits[0], date(2026, 7, 3)), 2
            )
            self.assertEqual(
                loaded.raw_count(loaded.habits[1], date(2026, 7, 4)), 1
            )

    def test_tsv_is_selected_by_file_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "habits.tsv"
            tracker = Tracker()
            tracker.add_habit("Read", DAILY, 1, date(2026, 7, 1))

            CSVStore(path).save(tracker)

            self.assertIn("\t", path.read_text(encoding="utf-8").partition("\n")[0])
            self.assertEqual(CSVStore(path).load().habits[0].name, "Read")

    def test_duplicate_entry_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "habits.csv"
            path.write_text(
                "record_type,habit_id,habit_name,schedule,target,date,count,"
                "created_on\n"
                "habit,h1,Read,daily,1,,,2026-07-01\n"
                "entry,h1,,,,2026-07-02,1,\n"
                "entry,h1,,,,2026-07-02,1,\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StorageError, "duplicate entry"):
                CSVStore(path).load()

    def test_zero_count_entry_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "habits.csv"
            path.write_text(
                "record_type,habit_id,habit_name,schedule,target,date,count,"
                "created_on\n"
                "habit,h1,Read,daily,1,,,2026-07-01\n"
                "entry,h1,,,,2026-07-02,0,\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(StorageError, "greater than zero"):
                CSVStore(path).load()


if __name__ == "__main__":
    unittest.main()
