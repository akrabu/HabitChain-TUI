# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.

from datetime import date, timedelta
import unittest

from habit_tracker.model import DAILY, WEEKLY, Tracker


class SegmentRecordingTracker(Tracker):
    def __init__(self) -> None:
        super().__init__()
        self.segment_lengths: list[int] = []

    def _build_weekly_chain_history(
        self, habit, history_start, through, *, open_day
    ):
        self.segment_lengths.append((through - history_start).days + 1)
        return super()._build_weekly_chain_history(
            habit, history_start, through, open_day=open_day
        )


class TrackerTests(unittest.TestCase):
    def test_once_daily_uses_dot_and_x(self) -> None:
        today = date(2026, 7, 25)
        tracker = Tracker()
        habit = tracker.add_habit("Write", DAILY, 1, today)

        self.assertEqual(tracker.status(habit, today).symbol, ".")
        tracker.increment(habit, today)
        self.assertEqual(tracker.status(habit, today).symbol, "X")

    def test_multiple_daily_counts_then_becomes_x(self) -> None:
        today = date(2026, 7, 25)
        tracker = Tracker()
        habit = tracker.add_habit("Water", DAILY, 3, today)

        tracker.increment(habit, today)
        self.assertEqual(tracker.status(habit, today).symbol, "1")
        tracker.increment(habit, today)
        self.assertEqual(tracker.status(habit, today).symbol, "2")
        tracker.increment(habit, today)
        self.assertEqual(tracker.status(habit, today).symbol, "X")
        self.assertFalse(tracker.increment(habit, today))

    def test_weekly_goal_uses_stars_until_chain_is_complete(self) -> None:
        start = date(2026, 7, 13)
        display_start = start - timedelta(days=9)
        through = start + timedelta(days=5)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        tracker.increment(habit, start)
        tracker.increment(habit, start + timedelta(days=2))
        dates = [
            display_start + timedelta(days=offset) for offset in range(15)
        ]

        self.assertEqual(
            "-".join(
                tracker.weekly_chain_symbols(habit, dates, through=through)
            ),
            ".-.-.-.-.-.-.-.-.-1-*-2-*-*-.",
        )

        tracker.increment(habit, through)
        self.assertEqual(
            "-".join(
                tracker.weekly_chain_symbols(habit, dates, through=through)
            ),
            ".-.-.-.-.-.-.-.-.-X---X-----X",
        )

    def test_weekly_habit_can_only_be_marked_once_per_day(self) -> None:
        start = date(2026, 7, 13)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)

        self.assertTrue(tracker.increment(habit, start))
        self.assertFalse(tracker.increment(habit, start))
        self.assertEqual(tracker.raw_count(habit, start), 1)
        tracker.set_count(habit, start, 10)
        self.assertEqual(tracker.raw_count(habit, start), 1)
        self.assertEqual(
            tracker.weekly_chain_symbols(habit, [start], through=start),
            ["1"],
        )

    def test_weekly_broken_or_not_started_chain_uses_dots(self) -> None:
        start = date(2026, 7, 13)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        tracker.increment(habit, start)
        tracker.increment(habit, start + timedelta(days=7))
        dates = [start + timedelta(days=offset) for offset in range(-1, 8)]

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit, dates, through=start + timedelta(days=7)
            ),
            [".", "1", ".", ".", ".", ".", ".", ".", "1"],
        )

    def test_weekly_chain_does_not_complete_outside_seven_days(self) -> None:
        start = date(2026, 7, 13)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        tracker.set_count(habit, start, 1)
        tracker.set_count(habit, start + timedelta(days=3), 1)
        tracker.set_count(habit, start + timedelta(days=7), 1)

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=offset) for offset in range(8)],
                through=start + timedelta(days=7),
            ),
            ["1", ".", ".", "2", ".", ".", ".", "1"],
        )

    def test_weekly_x_chain_stays_active_until_it_breaks(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        for offset in (0, 2, 5, 6, 10):
            tracker.increment(habit, start + timedelta(days=offset))

        dates = [start + timedelta(days=offset) for offset in range(11)]
        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit, dates, through=start + timedelta(days=10)
            ),
            ["X", "-", "X", "-", "-", "X", "X", ".", ".", ".", "1"],
        )

        tracker.increment(habit, start + timedelta(days=11))
        tracker.increment(habit, start + timedelta(days=12))
        dates.extend(
            [start + timedelta(days=11), start + timedelta(days=12)]
        )
        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit, dates, through=start + timedelta(days=12)
            ),
            [
                "X",
                "-",
                "X",
                "-",
                "-",
                "X",
                "X",
                ".",
                ".",
                ".",
                "X",
                "X",
                "X",
            ],
        )

    def test_open_day_keeps_a_weekly_chain_alive_until_tomorrow(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        for offset in (0, 2, 5):
            tracker.increment(habit, start + timedelta(days=offset))

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=offset) for offset in range(8)],
                through=start + timedelta(days=7),
            ),
            ["X", "-", "X", "-", "-", "X", "*", "."],
        )
        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=offset) for offset in range(9)],
                through=start + timedelta(days=8),
            ),
            ["X", "-", "X", "-", "-", "X", ".", ".", "."],
        )

    def test_mark_on_expiration_day_links_the_weekly_chain(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        for offset in (0, 2, 5, 7):
            tracker.increment(habit, start + timedelta(days=offset))

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=offset) for offset in range(8)],
                through=start + timedelta(days=7),
            ),
            ["X", "-", "X", "-", "-", "X", "-", "X"],
        )

    def test_weekly_target_one_can_link_marks_seven_days_apart(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 1, start)
        tracker.increment(habit, start)
        tracker.increment(habit, start + timedelta(days=7))

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=offset) for offset in range(8)],
                through=start + timedelta(days=7),
            ),
            ["X", "-", "-", "-", "-", "-", "-", "X"],
        )

    def test_weekly_target_cannot_exceed_available_days(self) -> None:
        tracker = Tracker()

        with self.assertRaisesRegex(ValueError, "cannot exceed 7"):
            tracker.add_habit(
                "Impossible", WEEKLY, 8, date(2026, 7, 1)
            )

    def test_changing_daily_to_weekly_normalizes_existing_counts(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", DAILY, 5, start)
        tracker.set_count(habit, start, 4)

        tracker.update_habit(
            habit, name=" Exercise ", schedule=WEEKLY, target=3
        )

        self.assertEqual(habit.name, "Exercise")
        self.assertEqual(tracker.raw_count(habit, start), 1)

    def test_invalid_update_does_not_partially_mutate_habit(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", DAILY, 5, start)

        with self.assertRaisesRegex(ValueError, "cannot exceed 7"):
            tracker.update_habit(
                habit, name="Changed", schedule=WEEKLY, target=8
            )

        self.assertEqual((habit.name, habit.schedule, habit.target), (
            "Exercise",
            DAILY,
            5,
        ))

    def test_weekly_symbol_queries_only_scan_near_requested_dates(self) -> None:
        tracker = SegmentRecordingTracker()
        start = date(1970, 1, 1)
        habit = tracker.add_habit("Exercise", WEEKLY, 3, start)
        requested = [date(2000, 1, 1), date(2026, 7, 26)]

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit, requested, through=requested[-1]
            ),
            [".", "."],
        )
        self.assertEqual(len(tracker.segment_lengths), 2)
        self.assertTrue(
            all(length <= 15 for length in tracker.segment_lengths)
        )

    def test_bounded_query_recovers_a_long_active_chain(self) -> None:
        start = date(2026, 1, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 1, start)
        for offset in (0, 7, 14):
            tracker.increment(habit, start + timedelta(days=offset))

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=10)],
                through=start + timedelta(days=14),
            ),
            ["-"],
        )

    def test_bounded_query_does_not_reuse_a_consumed_active_mark(self) -> None:
        start = date(2026, 1, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 2, start)
        for offset in (0, 1, 6, 11):
            tracker.increment(habit, start + timedelta(days=offset))

        self.assertEqual(
            tracker.weekly_chain_symbols(
                habit,
                [start + timedelta(days=10)],
                through=start + timedelta(days=11),
            ),
            ["."],
        )

    def test_calendar_boundaries_do_not_overflow(self) -> None:
        for boundary in (date.min, date.max):
            with self.subTest(boundary=boundary):
                tracker = Tracker()
                habit = tracker.add_habit(
                    "Exercise", WEEKLY, 1, boundary
                )
                tracker.increment(habit, boundary)

                self.assertEqual(
                    tracker.weekly_chain_symbols(
                        habit, [boundary], through=boundary
                    ),
                    ["X"],
                )
                self.assertEqual(tracker.streaks(habit, boundary), (1, 1))

    def test_sparse_daily_streaks_preserve_current_and_best(self) -> None:
        start = date(1970, 1, 1)
        through = date(2026, 7, 26)
        tracker = Tracker()
        habit = tracker.add_habit("Write", DAILY, 1, start)
        tracker.set_count(habit, through - timedelta(days=2), 1)
        tracker.set_count(habit, through - timedelta(days=1), 1)

        self.assertEqual(tracker.streaks(habit, through), (2, 2))

    def test_sparse_weekly_streaks_preserve_rolling_completion(self) -> None:
        start = date(2026, 7, 1)
        tracker = Tracker()
        habit = tracker.add_habit("Exercise", WEEKLY, 2, start)
        tracker.increment(habit, start)
        tracker.increment(habit, start + timedelta(days=1))

        self.assertEqual(
            tracker.streaks(habit, start + timedelta(days=7)),
            (6, 6),
        )
        self.assertEqual(
            tracker.streaks(habit, start + timedelta(days=8)),
            (0, 6),
        )

    def test_streaks_keep_yesterdays_chain_active(self) -> None:
        today = date(2026, 7, 25)
        tracker = Tracker()
        habit = tracker.add_habit(
            "Read", DAILY, 1, today - timedelta(days=4)
        )
        for days_ago in (4, 3, 2, 1):
            tracker.set_count(habit, today - timedelta(days=days_ago), 1)

        self.assertEqual(tracker.streaks(habit, today), (4, 4))

    def test_backfill_moves_creation_date_back(self) -> None:
        today = date(2026, 7, 25)
        earlier = today - timedelta(days=10)
        tracker = Tracker()
        habit = tracker.add_habit("Walk", DAILY, 1, today)

        tracker.set_count(habit, earlier, 1)

        self.assertEqual(habit.created_on, earlier)


if __name__ == "__main__":
    unittest.main()
