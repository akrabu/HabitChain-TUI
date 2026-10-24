# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.

"""Curses terminal interface for the Habit Chain app."""

from __future__ import annotations

import curses
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .model import (
    DAILY,
    MAX_DAILY_COUNT,
    MAX_TARGET,
    MAX_WEEKLY_TARGET,
    WEEKLY,
    Habit,
    Tracker,
)
from .storage import CSVStore, StorageError


@dataclass(frozen=True, slots=True)
class ChainPart:
    kind: str
    text: str
    start: int
    width: int
    index: int | None = None


def chain_layout(
    symbols: list[str], total_width: int, node_width: int
) -> list[ChainPart]:
    """Lay out a chain with exactly one hyphen between each day."""

    if not symbols or total_width <= 0:
        return []
    node_width = max(node_width, max(len(symbol) for symbol in symbols))
    count = len(symbols)
    required = count * node_width + max(0, count - 1)
    if required != total_width:
        raise ValueError("Chain width must match its nodes and single links.")

    if count == 1:
        return [
            ChainPart(
                "node",
                symbols[0].center(total_width),
                0,
                total_width,
                0,
            )
        ]

    parts: list[ChainPart] = []
    cursor = 0
    for index, symbol in enumerate(symbols):
        parts.append(
            ChainPart(
                "node",
                symbol.center(node_width),
                cursor,
                node_width,
                index,
            )
        )
        cursor += node_width
        if index < count - 1:
            parts.append(ChainPart("link", "-", cursor, 1))
            cursor += 1
    return parts


def day_count_for_width(total_width: int, node_width: int) -> int:
    """Fit as many single-link days as possible into the available width."""

    return max(1, (total_width + 1) // (node_width + 1))


NAVIGATION_KEYS = frozenset(
    {
        curses.KEY_UP,
        curses.KEY_DOWN,
        curses.KEY_LEFT,
        curses.KEY_RIGHT,
        "h",
        "j",
        "k",
        "l",
        "[",
        "]",
    }
)
ESCAPE_KEYS = frozenset({27, "\x1b"})


class HabitChainApp:
    def __init__(
        self,
        tracker: Tracker,
        store: CSVStore,
        *,
        use_color: bool = True,
    ):
        self.tracker = tracker
        self.store = store
        self.use_color = use_color
        self.selected = 0
        self.scroll = 0
        self.cursor_date = date.today()
        self.view_end = date.today()
        self.message = ""
        self.stdscr: curses.window | None = None
        self._pending_key: str | int | None = None
        self._cache_through: date | None = None
        self._streak_cache: dict[str, tuple[int, int]] = {}
        self._weekly_symbol_cache: dict[
            str, tuple[tuple[date, ...], list[str]]
        ] = {}

    def run(self, stdscr: curses.window) -> None:
        self.stdscr = stdscr
        stdscr.keypad(True)
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self._init_colors()

        while True:
            self.draw()
            try:
                key = self._read_key()
            except curses.error:
                continue
            if not self.handle_key(key):
                return
            if key in NAVIGATION_KEYS and not self._drain_navigation_keys():
                return

    def _read_key(self) -> str | int:
        assert self.stdscr is not None
        if self._pending_key is not None:
            key = self._pending_key
            self._pending_key = None
            return key
        return self.stdscr.get_wch()

    def _drain_navigation_keys(self) -> bool:
        """Apply queued movement keys before performing the next redraw."""

        assert self.stdscr is not None
        self.stdscr.nodelay(True)
        try:
            for _ in range(256):
                try:
                    key = self.stdscr.get_wch()
                except curses.error:
                    break
                if key not in NAVIGATION_KEYS:
                    self._pending_key = key
                    break
                if not self.handle_key(key):
                    return False
        finally:
            self.stdscr.nodelay(False)
        return True

    def _init_colors(self) -> None:
        if not self.use_color or not curses.has_colors():
            self.use_color = False
            return
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_GREEN, -1)
            curses.init_pair(3, curses.COLOR_YELLOW, -1)
            curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(5, curses.COLOR_RED, -1)
        except curses.error:
            self.use_color = False

    def color(self, pair: int) -> int:
        return curses.color_pair(pair) if self.use_color else 0

    def _invalidate_history_cache(self) -> None:
        self._cache_through = None
        self._streak_cache.clear()
        self._weekly_symbol_cache.clear()

    def _prepare_history_cache(self, through: date) -> None:
        if self._cache_through != through:
            self._invalidate_history_cache()
            self._cache_through = through

    def _habit_streaks(
        self, habit: Habit, through: date
    ) -> tuple[int, int]:
        self._prepare_history_cache(through)
        if habit.id not in self._streak_cache:
            self._streak_cache[habit.id] = self.tracker.streaks(
                habit, through
            )
        return self._streak_cache[habit.id]

    def _best_chain(self, through: date) -> tuple[int, Habit | None]:
        best_days = 0
        winner: Habit | None = None
        winner_current = 0
        for habit in self.tracker.habits:
            current, best = self._habit_streaks(habit, through)
            if best > best_days or (
                best == best_days
                and winner is not None
                and current > winner_current
            ):
                best_days = best
                winner = habit
                winner_current = current
        return best_days, winner

    def _weekly_symbols(
        self, habit: Habit, dates: list[date], through: date
    ) -> list[str]:
        self._prepare_history_cache(through)
        date_key = tuple(dates)
        cached = self._weekly_symbol_cache.get(habit.id)
        if cached is None or cached[0] != date_key:
            cached = (
                date_key,
                self.tracker.weekly_chain_symbols(
                    habit, dates, through=through
                ),
            )
            self._weekly_symbol_cache[habit.id] = cached
        return cached[1]

    def add(self, y: int, x: int, text: str, attr: int = 0) -> None:
        assert self.stdscr is not None
        height, width = self.stdscr.getmaxyx()
        if y < 0 or y >= height or x >= width or not text:
            return
        if x < 0:
            text = text[-x:]
            x = 0
        try:
            self.stdscr.addnstr(y, x, text, max(0, width - x), attr)
        except curses.error:
            pass

    def draw(self) -> None:
        assert self.stdscr is not None
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()

        if height < 10 or width < 46:
            self.add(0, 0, "HABIT CHAIN", curses.A_BOLD)
            self.add(
                2,
                0,
                f"Terminal too small ({width}x{height}). Need at least 46x10.",
            )
            self.add(4, 0, "Resize the terminal, or press q to quit.")
            self.stdscr.refresh()
            return

        today = date.today()
        title = " HABIT CHAIN "
        file_note = f" CSV: {self.store.path.name} "
        self.add(0, 0, " " * width, curses.A_REVERSE)
        self.add(0, 0, title, curses.A_BOLD | curses.A_REVERSE)
        self.add(
            0,
            max(len(title), width - len(file_note)),
            file_note,
            curses.A_REVERSE,
        )

        best, winner = self._best_chain(today)
        day_word = "DAY" if best == 1 else "DAYS"
        winner_text = f"  {winner.name}" if winner is not None else ""
        self.add(
            1,
            1,
            f"BEST CHAIN  {best} {day_word}{winner_text}",
            curses.A_BOLD | self.color(1),
        )
        self.add(2, 0, "-" * width, curses.A_DIM)

        prefix_width, timeline_width, stats_width, node_width = self._geometry(
            width
        )
        day_count = day_count_for_width(timeline_width, node_width)
        self._keep_cursor_visible(day_count)
        dates = [
            self.view_end - timedelta(days=day_count - 1 - index)
            for index in range(day_count)
        ]

        blank_symbols = ["." for _ in dates]
        layout = chain_layout(blank_symbols, timeline_width, node_width)
        header = [" " for _ in range(timeline_width)]
        for part in layout:
            if part.kind != "node" or part.index is None:
                continue
            label = f"{dates[part.index].day:02d}"
            center = part.start + part.width // 2
            left = max(0, min(timeline_width - len(label), center - 1))
            guard_left = max(0, left - 1)
            guard_right = min(timeline_width, left + len(label) + 1)
            if all(
                character == " "
                for character in header[guard_left:guard_right]
            ):
                header[left : left + 2] = label

        self.add(3, 1, "HABIT")
        self.add(3, prefix_width, "".join(header), curses.A_DIM)
        stats_header = "NOW  BEST"
        self.add(
            3,
            width - stats_width,
            stats_header.rjust(stats_width - 1),
            curses.A_DIM,
        )

        first_row = 4
        last_row = height - 4
        visible_rows = max(1, last_row - first_row + 1)
        self._keep_selection_visible(visible_rows)

        if not self.tracker.habits:
            self.add(
                first_row + 1,
                2,
                "No habits yet. Press a to add your first one.",
                curses.A_BOLD,
            )
            self.add(
                first_row + 3,
                2,
                "Your chain will look like  .-X-X-X-.-X",
                self.color(2),
            )
        else:
            habits = self.tracker.habits[
                self.scroll : self.scroll + visible_rows
            ]
            for row_offset, habit in enumerate(habits):
                index = self.scroll + row_offset
                self._draw_habit_row(
                    first_row + row_offset,
                    width,
                    prefix_width,
                    timeline_width,
                    stats_width,
                    node_width,
                    dates,
                    habit,
                    index == self.selected,
                    today,
                )

        if self.scroll > 0:
            self.add(first_row, width - 1, "^", curses.A_BOLD)
        if self.scroll + visible_rows < len(self.tracker.habits):
            self.add(last_row, width - 1, "v", curses.A_BOLD)

        self.add(height - 3, 0, "-" * width, curses.A_DIM)
        self._draw_detail(height - 2, width)
        keys = (
            "Arrows/hjkl: move  Space: +1  Backspace: -1  e: set  "
            "a: add  c: change  d: delete  ?: help  q: quit"
        )
        self.add(height - 1, 0, keys[:width], curses.A_REVERSE)
        self.stdscr.refresh()

    def _geometry(self, width: int) -> tuple[int, int, int, int]:
        prefix_width = min(25, max(13, width // 5))
        stats_width = 12 if width >= 64 else 9
        largest_target = max(
            (habit.target for habit in self.tracker.habits), default=1
        )
        node_width = max(1, len(str(max(1, largest_target - 1))))
        available_width = width - prefix_width - stats_width
        day_count = day_count_for_width(available_width, node_width)
        timeline_width = day_count * node_width + day_count - 1
        # Give the one or two unused columns to the name area. The chain then
        # fills every column between the habit name and the right-edge stats.
        prefix_width = width - stats_width - timeline_width
        return prefix_width, timeline_width, stats_width, node_width

    def _draw_habit_row(
        self,
        y: int,
        width: int,
        prefix_width: int,
        timeline_width: int,
        stats_width: int,
        node_width: int,
        dates: list[date],
        habit: Habit,
        is_selected: bool,
        today: date,
    ) -> None:
        marker = ">" if is_selected else " "
        available_name = prefix_width - 3
        name = habit.name
        if len(name) > available_name:
            name = name[: max(1, available_name - 1)] + "~"
        name_attr = curses.A_BOLD if is_selected else 0
        self.add(y, 0, f"{marker} {name:<{available_name}} ", name_attr)

        if habit.schedule == WEEKLY:
            symbols = self._weekly_symbols(habit, dates, through=today)
            raw_counts = [
                self.tracker.raw_count(habit, on_date) for on_date in dates
            ]
        else:
            statuses = [
                self.tracker.status(habit, on_date) for on_date in dates
            ]
            symbols = [status.symbol for status in statuses]
            raw_counts = [status.raw_count for status in statuses]
        layout = chain_layout(symbols, timeline_width, node_width)
        timeline_x = prefix_width

        for part in layout:
            if part.kind == "link":
                assert part.index is None
                self.add(
                    y,
                    timeline_x + part.start,
                    part.text,
                    curses.A_DIM,
                )
                continue

            assert part.index is not None
            on_date = dates[part.index]
            display_symbol = symbols[part.index]
            if display_symbol in {"X", "-"}:
                attr = curses.A_BOLD | self.color(2)
            elif display_symbol == "*":
                attr = curses.A_BOLD | self.color(3)
            elif display_symbol != ".":
                attr = curses.A_BOLD | self.color(3)
            else:
                attr = curses.A_DIM
            if habit.schedule == WEEKLY and raw_counts[part.index]:
                attr |= curses.A_UNDERLINE | curses.A_BOLD
            if is_selected and on_date == self.cursor_date:
                attr = curses.A_REVERSE | curses.A_BOLD
            self.add(
                y,
                timeline_x + part.start,
                part.text,
                attr,
            )

        current, best = self._habit_streaks(habit, today)
        stats = f"{current:>4} {best:>5}"
        self.add(
            y,
            width - stats_width,
            stats[-stats_width:].rjust(stats_width),
            curses.A_BOLD if is_selected else 0,
        )

    def _draw_detail(self, y: int, width: int) -> None:
        if self.message:
            attr = self.color(5) if self.message.startswith("Error:") else 0
            self.add(y, 0, self.message[:width], attr)
            return
        habit = self.current_habit
        if habit is None:
            self.add(y, 0, f"Data is saved directly to {self.store.path}")
            return
        status = self.tracker.status(habit, self.cursor_date)
        when = self.cursor_date.strftime("%a %b %d, %Y")
        if habit.schedule == WEEKLY:
            detail = (
                f"{habit.name} | {when} | logged that day: {status.raw_count} | "
                f"rolling 7-day total: {status.progress}/{habit.target}"
            )
        else:
            detail = (
                f"{habit.name} | {when} | "
                f"day's count: {status.raw_count}/{habit.target}"
            )
        if status.complete:
            detail += " | complete"
        self.add(y, 0, detail[:width])

    @property
    def current_habit(self) -> Habit | None:
        if not self.tracker.habits:
            return None
        self.selected = min(self.selected, len(self.tracker.habits) - 1)
        return self.tracker.habits[self.selected]

    def _keep_selection_visible(self, visible_rows: int) -> None:
        if not self.tracker.habits:
            self.selected = 0
            self.scroll = 0
            return
        self.selected = max(0, min(self.selected, len(self.tracker.habits) - 1))
        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + visible_rows:
            self.scroll = self.selected - visible_rows + 1

    def _keep_cursor_visible(self, day_count: int) -> None:
        today = date.today()
        self.cursor_date = min(self.cursor_date, today)
        self.view_end = min(self.view_end, today)
        first = self.view_end - timedelta(days=day_count - 1)
        if self.cursor_date < first:
            self.view_end = min(
                today, self.cursor_date + timedelta(days=day_count - 1)
            )
        elif self.cursor_date > self.view_end:
            self.view_end = self.cursor_date

    def handle_key(self, key: str | int) -> bool:
        self.message = ""
        if key in ESCAPE_KEYS:
            self.message = "Cancelled."
            return True
        if key in ("q", "Q"):
            return False
        if key == curses.KEY_RESIZE:
            return True
        if key in (curses.KEY_UP, "k"):
            if self.tracker.habits:
                self.selected = max(0, self.selected - 1)
            return True
        if key in (curses.KEY_DOWN, "j"):
            if self.tracker.habits:
                self.selected = min(
                    len(self.tracker.habits) - 1, self.selected + 1
                )
            return True
        if key in (curses.KEY_LEFT, "h"):
            self.cursor_date -= timedelta(days=1)
            return True
        if key in (curses.KEY_RIGHT, "l"):
            self.cursor_date = min(
                date.today(), self.cursor_date + timedelta(days=1)
            )
            return True
        if key == "[":
            self.cursor_date -= timedelta(days=7)
            return True
        if key == "]":
            self.cursor_date = min(
                date.today(), self.cursor_date + timedelta(days=7)
            )
            return True
        if key in ("g", "G"):
            self.cursor_date = date.today()
            self.view_end = date.today()
            return True
        if key in (" ", "\n", "\r", curses.KEY_ENTER):
            self._increment()
            return True
        if key in (
            curses.KEY_BACKSPACE,
            "\b",
            "\x7f",
            "-",
        ):
            self._decrement()
            return True
        if key == "0":
            self._set_count(0)
            return True
        if key in ("e", "E"):
            self._edit_count()
            return True
        if key in ("a", "A"):
            self._add_habit()
            return True
        if key in ("c", "C"):
            self._configure_habit()
            return True
        if key in ("d", "D"):
            self._delete_habit()
            return True
        if key in ("s", "S"):
            self._save("Saved.")
            return True
        if key == "?":
            self._show_help()
            return True
        return True

    def _increment(self) -> None:
        habit = self.current_habit
        if habit is None:
            self.message = "Press a to add a habit first."
            return
        if self.tracker.increment(habit, self.cursor_date):
            self._save("Marked +1.")
        elif habit.schedule == WEEKLY:
            self.message = "That rolling habit is already marked for this day."
        else:
            self.message = (
                "That daily goal is already complete. "
                "Use e to set a different count."
            )

    def _decrement(self) -> None:
        habit = self.current_habit
        if habit is None:
            self.message = "Press a to add a habit first."
            return
        if self.tracker.decrement(habit, self.cursor_date):
            self._save("Marked -1.")
        else:
            self.message = "That day is already at zero."

    def _set_count(self, count: int) -> None:
        habit = self.current_habit
        if habit is None:
            self.message = "Press a to add a habit first."
            return
        self.tracker.set_count(habit, self.cursor_date, count)
        self._save("Day cleared." if count == 0 else f"Count set to {count}.")

    def _edit_count(self) -> None:
        habit = self.current_habit
        if habit is None:
            self.message = "Press a to add a habit first."
            return
        current = self.tracker.raw_count(habit, self.cursor_date)
        maximum = 1 if habit.schedule == WEEKLY else MAX_DAILY_COUNT
        answer = self.prompt(
            f"Set raw count for {self.cursor_date.isoformat()} "
            f"(0-{maximum}, current {current}): "
        )
        if answer is None or not answer.strip():
            return
        try:
            count = int(answer)
            if not 0 <= count <= maximum:
                raise ValueError(f"count must be between 0 and {maximum}")
            self._set_count(count)
        except ValueError as error:
            self.message = f"Error: {error}"

    def _add_habit(self) -> None:
        name = self.prompt("Habit name: ")
        if name is None or not name.strip():
            return
        schedule = self._ask_schedule()
        if schedule is None:
            return
        target = self._ask_target(schedule)
        if target is None:
            return
        try:
            self.tracker.add_habit(
                name=name,
                schedule=schedule,
                target=target,
                created_on=self.cursor_date,
            )
            self.selected = len(self.tracker.habits) - 1
            self._save(f"Added {name.strip()}.")
        except ValueError as error:
            self.message = f"Error: {error}"

    def _configure_habit(self) -> None:
        habit = self.current_habit
        if habit is None:
            self.message = "Press a to add a habit first."
            return
        name = self.prompt(f"Name [{habit.name}] (Enter keeps it): ")
        if name is None:
            return
        schedule = self._ask_schedule(default=habit.schedule)
        if schedule is None:
            return
        target = self._ask_target(schedule, default=habit.target)
        if target is None:
            return
        try:
            self.tracker.update_habit(
                habit,
                name=name.strip() or habit.name,
                schedule=schedule,
                target=target,
            )
            self._save(f"Updated {habit.name}.")
        except ValueError as error:
            self.message = f"Error: {error}"

    def _ask_schedule(self, default: str | None = None) -> str | None:
        default_hint = f", Enter keeps {default}" if default else ""
        answer = self.prompt(
            f"Schedule: d = per day, w = rolling 7 days{default_hint}: "
        )
        if answer is None:
            return None
        answer = answer.strip().lower()
        if not answer and default:
            return default
        if answer in {"d", "day", "daily"}:
            return DAILY
        if answer in {"w", "week", "weekly"}:
            return WEEKLY
        self.message = "Error: schedule must be d or w."
        return None

    def _ask_target(
        self, schedule: str, default: int | None = None
    ) -> int | None:
        unit = "each day" if schedule == DAILY else "in each rolling 7 days"
        maximum = MAX_TARGET if schedule == DAILY else MAX_WEEKLY_TARGET
        valid_default = (
            default if default is not None and 1 <= default <= maximum else None
        )
        default_hint = (
            f", Enter keeps {valid_default}"
            if valid_default is not None
            else ""
        )
        answer = self.prompt(
            f"Times to complete {unit} (1-{maximum}{default_hint}): "
        )
        if answer is None:
            return None
        answer = answer.strip()
        if not answer and valid_default is not None:
            return valid_default
        try:
            target = int(answer)
            if not 1 <= target <= maximum:
                raise ValueError
            return target
        except ValueError:
            self.message = f"Error: target must be 1-{maximum}."
            return None

    def _delete_habit(self) -> None:
        habit = self.current_habit
        if habit is None:
            return
        answer = self.prompt(
            f"Delete {habit.name!r} and all its history? Type y to confirm: "
        )
        if answer is None or answer.strip().lower() != "y":
            self.message = "Delete cancelled."
            return
        name = habit.name
        self.tracker.remove_habit(habit.id)
        self.selected = min(self.selected, len(self.tracker.habits) - 1)
        self._save(f"Deleted {name}.")

    def _save(self, success_message: str) -> None:
        self._invalidate_history_cache()
        try:
            self.store.save(self.tracker)
            self.message = success_message
        except StorageError as error:
            self.message = f"Error: could not save CSV: {error}"

    def prompt(self, label: str) -> str | None:
        assert self.stdscr is not None
        height, width = self.stdscr.getmaxyx()
        y = height - 1
        self.add(y, 0, " " * width, curses.A_REVERSE)
        self.add(y, 0, label[: max(0, width - 1)], curses.A_REVERSE)
        x = min(len(label), max(0, width - 1))
        capacity = max(0, width - x - 1)
        entered: list[str] = []
        try:
            curses.curs_set(1)
            while True:
                self.add(y, x, " " * capacity, curses.A_REVERSE)
                self.add(y, x, "".join(entered), curses.A_REVERSE)
                self.stdscr.move(y, x + len(entered))
                self.stdscr.refresh()
                key = self.stdscr.get_wch()

                if key in ESCAPE_KEYS:
                    self.message = "Cancelled."
                    return None
                if key in ("\n", "\r", curses.KEY_ENTER):
                    return "".join(entered)
                if key in (
                    curses.KEY_BACKSPACE,
                    "\b",
                    "\x7f",
                ):
                    if entered:
                        entered.pop()
                    continue
                if (
                    isinstance(key, str)
                    and key.isprintable()
                    and len(entered) < capacity
                ):
                    entered.append(key)
        except curses.error:
            self.message = "Input cancelled."
            return None
        finally:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def _show_help(self) -> None:
        assert self.stdscr is not None
        height, width = self.stdscr.getmaxyx()
        lines = [
            "KEYBOARD",
            "",
            "Up/Down or j/k     Choose a habit",
            "Left/Right or h/l  Choose a day",
            "[ and ]            Move one week",
            "g                  Return to today",
            "Space or Enter     Add one completion",
            "Backspace or -     Remove one completion",
            "e                  Set an exact count",
            "0                  Clear the chosen day",
            "a / c / d          Add / change / delete a habit",
            "s                  Save now (changes also autosave)",
            "Esc                Cancel the current input",
            "q                  Quit",
            "",
            "Weekly goals use the rolling 7 days ending on each date.",
            "Underlined weekly symbols are days with a logged completion.",
            "",
            "Press any key to return",
        ]
        box_width = min(width - 4, max(len(line) for line in lines) + 4)
        box_height = min(height - 2, len(lines) + 2)
        top = max(0, (height - box_height) // 2)
        left = max(0, (width - box_width) // 2)

        self.add(top, left, "+" + "-" * (box_width - 2) + "+", curses.A_BOLD)
        for offset in range(1, box_height - 1):
            self.add(
                top + offset,
                left,
                "|" + " " * (box_width - 2) + "|",
            )
        self.add(
            top + box_height - 1,
            left,
            "+" + "-" * (box_width - 2) + "+",
            curses.A_BOLD,
        )
        for offset, line in enumerate(lines[: box_height - 2], start=1):
            attr = curses.A_BOLD if offset == 1 else 0
            self.add(top + offset, left + 2, line[: box_width - 4], attr)
        self.stdscr.refresh()
        self.stdscr.get_wch()
