# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.

import curses
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from habit_tracker.model import DAILY, WEEKLY, Tracker
from habit_tracker.storage import CSVStore
from habit_tracker.ui import (
    HabitChainApp,
    chain_layout,
    day_count_for_width,
)


class FakeInputWindow:
    def __init__(self, keys: list[str | int]):
        self.keys = keys
        self.nodelay_calls: list[bool] = []

    def nodelay(self, enabled: bool) -> None:
        self.nodelay_calls.append(enabled)

    def get_wch(self) -> str | int:
        if not self.keys:
            raise curses.error
        return self.keys.pop(0)


class FakePromptWindow:
    def __init__(self, keys: list[str | int], width: int = 40):
        self.keys = keys
        self.width = width
        self.moves: list[tuple[int, int]] = []

    def getmaxyx(self) -> tuple[int, int]:
        return 10, self.width

    def addnstr(self, *args) -> None:
        pass

    def move(self, y: int, x: int) -> None:
        self.moves.append((y, x))

    def refresh(self) -> None:
        pass

    def get_wch(self) -> str | int:
        if not self.keys:
            raise curses.error
        return self.keys.pop(0)


class CountingTracker(Tracker):
    def __init__(self) -> None:
        super().__init__()
        self.streak_calls = 0
        self.symbol_calls = 0

    def streaks(self, habit, through=None):
        self.streak_calls += 1
        return super().streaks(habit, through)

    def weekly_chain_symbols(self, habit, dates, through=None):
        self.symbol_calls += 1
        return super().weekly_chain_symbols(habit, dates, through)


class LayoutTests(unittest.TestCase):
    def test_chain_always_fills_its_width(self) -> None:
        parts = chain_layout([".", "X", "2", "X"], 7, 1)
        rendered = "".join(part.text for part in parts)

        self.assertEqual(rendered, ".-X-2-X")

    def test_every_connector_is_one_hyphen(self) -> None:
        parts = chain_layout([".", "10", "X"], 8, 2)
        links = [part.text for part in parts if part.kind == "link"]
        self.assertEqual(links, ["-", "-"])

    def test_day_count_fits(self) -> None:
        days = day_count_for_width(40, 1)
        self.assertLessEqual(days + days - 1, 40)
        self.assertEqual(days, 20)

    def test_queued_navigation_keys_are_applied_before_redraw(self) -> None:
        app = HabitChainApp(
            Tracker(), CSVStore(Path("unused.csv")), use_color=False
        )
        app.handle_key(curses.KEY_LEFT)
        window = FakeInputWindow(
            [curses.KEY_LEFT, curses.KEY_LEFT, "x"]
        )
        app.stdscr = window

        self.assertTrue(app._drain_navigation_keys())

        self.assertEqual(app.cursor_date, date.today() - timedelta(days=3))
        self.assertEqual(window.nodelay_calls, [True, False])
        self.assertEqual(app._read_key(), "x")

    def test_history_calculations_are_cached_until_data_changes(self) -> None:
        today = date(2026, 7, 26)
        tracker = CountingTracker()
        habit = tracker.add_habit(
            "Exercise", WEEKLY, 3, today - timedelta(days=10)
        )
        app = HabitChainApp(
            tracker, CSVStore(Path("unused.csv")), use_color=False
        )
        dates = [today - timedelta(days=1), today]

        app._habit_streaks(habit, today)
        app._habit_streaks(habit, today)
        app._weekly_symbols(habit, dates, today)
        app._weekly_symbols(habit, dates, today)

        self.assertEqual(tracker.streak_calls, 1)
        self.assertEqual(tracker.symbol_calls, 1)

        app._invalidate_history_cache()
        app._habit_streaks(habit, today)
        app._weekly_symbols(habit, dates, today)
        self.assertEqual(tracker.streak_calls, 2)
        self.assertEqual(tracker.symbol_calls, 2)

    def test_escape_is_non_destructive_outside_a_prompt(self) -> None:
        tracker = Tracker()
        app = HabitChainApp(
            tracker, CSVStore(Path("unused.csv")), use_color=False
        )

        self.assertTrue(app.handle_key(27))
        self.assertEqual(app.message, "Cancelled.")
        self.assertEqual(tracker.habits, [])

    def test_escape_cancels_prompt_input(self) -> None:
        app = HabitChainApp(
            Tracker(), CSVStore(Path("unused.csv")), use_color=False
        )
        app.stdscr = FakePromptWindow(["a", "b", "\x1b"])

        with patch("habit_tracker.ui.curses.curs_set") as curs_set:
            self.assertIsNone(app.prompt("Habit name: "))

        self.assertEqual(app.message, "Cancelled.")
        self.assertEqual(curs_set.call_args_list[0].args, (1,))
        self.assertEqual(curs_set.call_args_list[-1].args, (0,))

    def test_prompt_supports_backspace_and_enter(self) -> None:
        app = HabitChainApp(
            Tracker(), CSVStore(Path("unused.csv")), use_color=False
        )
        app.stdscr = FakePromptWindow(
            ["a", "b", curses.KEY_BACKSPACE, "c", "\n"]
        )

        with patch("habit_tracker.ui.curses.curs_set"):
            answer = app.prompt("Habit name: ")

        self.assertEqual(answer, "ac")

    def test_prompt_read_error_cancels_instead_of_spinning(self) -> None:
        app = HabitChainApp(
            Tracker(), CSVStore(Path("unused.csv")), use_color=False
        )
        app.stdscr = FakePromptWindow([])

        with patch("habit_tracker.ui.curses.curs_set"):
            self.assertIsNone(app.prompt("Habit name: "))

        self.assertEqual(app.message, "Input cancelled.")

    def test_weekly_target_prompt_rejects_an_invalid_daily_default(self) -> None:
        app = HabitChainApp(
            Tracker(), CSVStore(Path("unused.csv")), use_color=False
        )
        app.prompt = lambda label: ""

        self.assertIsNone(app._ask_target(WEEKLY, default=8))
        self.assertEqual(app.message, "Error: target must be 1-7.")
        app.prompt = lambda label: "8"
        self.assertEqual(app._ask_target(DAILY), 8)


if __name__ == "__main__":
    unittest.main()
