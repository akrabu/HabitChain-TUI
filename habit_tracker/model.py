# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.

"""Data model and chain calculations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable
from uuid import uuid4

DAILY = "daily"
WEEKLY = "weekly"
SCHEDULES = {DAILY, WEEKLY}
MAX_TARGET = 99
MAX_WEEKLY_TARGET = 7
MAX_DAILY_COUNT = 999


@dataclass(slots=True)
class Habit:
    id: str
    name: str
    schedule: str
    target: int
    created_on: date

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("A habit needs a name.")
        if self.schedule not in SCHEDULES:
            raise ValueError(f"Unknown schedule: {self.schedule!r}")
        if not 1 <= self.target <= MAX_TARGET:
            raise ValueError(f"Target must be between 1 and {MAX_TARGET}.")
        if self.schedule == WEEKLY and self.target > MAX_WEEKLY_TARGET:
            raise ValueError(
                f"A weekly target cannot exceed {MAX_WEEKLY_TARGET}."
            )

    @property
    def goal_label(self) -> str:
        if self.schedule == WEEKLY:
            return f"{self.target}x / rolling 7 days"
        if self.target == 1:
            return "once / day"
        return f"{self.target}x / day"


@dataclass(frozen=True, slots=True)
class DayStatus:
    """The displayed state of one day in a chain."""

    raw_count: int
    progress: int
    target: int
    complete: bool
    symbol: str


@dataclass(slots=True)
class Tracker:
    habits: list[Habit] = field(default_factory=list)
    entries: dict[tuple[str, date], int] = field(default_factory=dict)
    _entries_by_habit: dict[str, dict[date, int]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        for (habit_id, on_date), count in self.entries.items():
            if count > 0:
                self._entries_by_habit.setdefault(habit_id, {})[
                    on_date
                ] = count

    def add_habit(
        self,
        name: str,
        schedule: str,
        target: int,
        created_on: date | None = None,
    ) -> Habit:
        habit = Habit(
            id=uuid4().hex[:12],
            name=name,
            schedule=schedule,
            target=target,
            created_on=created_on or date.today(),
        )
        self.habits.append(habit)
        return habit

    def habit_by_id(self, habit_id: str) -> Habit | None:
        return next((habit for habit in self.habits if habit.id == habit_id), None)

    def update_habit(
        self,
        habit: Habit,
        *,
        name: str,
        schedule: str,
        target: int,
    ) -> None:
        """Validate and update a habit without leaving a partial mutation."""

        updated = Habit(
            id=habit.id,
            name=name,
            schedule=schedule,
            target=target,
            created_on=habit.created_on,
        )
        habit.name = updated.name
        habit.schedule = updated.schedule
        habit.target = updated.target

        if habit.schedule == WEEKLY:
            for on_date, count in list(
                self._entries_by_habit.get(habit.id, {}).items()
            ):
                if count > 1:
                    self.set_count(habit, on_date, 1)

    def remove_habit(self, habit_id: str) -> None:
        self.habits = [habit for habit in self.habits if habit.id != habit_id]
        self.entries = {
            key: count
            for key, count in self.entries.items()
            if key[0] != habit_id
        }
        self._entries_by_habit.pop(habit_id, None)

    def raw_count(self, habit: Habit, on_date: date) -> int:
        return self.entries.get((habit.id, on_date), 0)

    def set_count(self, habit: Habit, on_date: date, count: int) -> None:
        if count < 0 or count > MAX_DAILY_COUNT:
            raise ValueError(
                f"A day's count must be between 0 and {MAX_DAILY_COUNT}."
            )
        if habit.schedule == WEEKLY:
            count = min(count, 1)
        key = (habit.id, on_date)
        if count:
            self.entries[key] = count
            self._entries_by_habit.setdefault(habit.id, {})[on_date] = count
            if on_date < habit.created_on:
                habit.created_on = on_date
        else:
            self.entries.pop(key, None)
            habit_entries = self._entries_by_habit.get(habit.id)
            if habit_entries is not None:
                habit_entries.pop(on_date, None)
                if not habit_entries:
                    self._entries_by_habit.pop(habit.id, None)

    def increment(self, habit: Habit, on_date: date) -> bool:
        current = self.raw_count(habit, on_date)
        if habit.schedule == WEEKLY and current >= 1:
            return False
        if habit.schedule == DAILY and current >= habit.target:
            return False
        self.set_count(habit, on_date, current + 1)
        return True

    def decrement(self, habit: Habit, on_date: date) -> bool:
        current = self.raw_count(habit, on_date)
        if current == 0:
            return False
        self.set_count(habit, on_date, current - 1)
        return True

    def rolling_count(self, habit: Habit, on_date: date) -> int:
        lookback = min(6, (on_date - date.min).days)
        first = on_date - timedelta(days=lookback)
        return sum(
            self.raw_count(habit, first + timedelta(days=offset))
            for offset in range(lookback + 1)
        )

    def weekly_chain_symbols(
        self,
        habit: Habit,
        dates: Iterable[date],
        through: date | None = None,
    ) -> list[str]:
        """Return weekly attempt symbols for the requested dates.

        A new attempt shows cumulative numbers on logged days and stars on
        elapsed gaps. Reaching the target within seven days converts that
        attempt's numbers to X. Afterward, logged days remain X until a past
        day falls below the rolling target, which starts the next attempt over.
        """

        if habit.schedule != WEEKLY:
            raise ValueError("Weekly chain symbols require a weekly habit.")

        requested = list(dates)
        if not requested:
            return []
        through = through or date.today()
        relevant = sorted(
            {
                on_date
                for on_date in requested
                if habit.created_on <= on_date <= through
            }
        )
        if not relevant:
            return ["." for _ in requested]

        by_date: dict[date, str] = {}
        cluster: list[date] = []
        for on_date in relevant:
            if cluster and (on_date - cluster[-1]).days > 14:
                self._fill_weekly_symbol_cluster(
                    habit, cluster, through, by_date
                )
                cluster = []
            cluster.append(on_date)
        self._fill_weekly_symbol_cluster(habit, cluster, through, by_date)
        return [by_date.get(on_date, ".") for on_date in requested]

    def _fill_weekly_symbol_cluster(
        self,
        habit: Habit,
        dates: list[date],
        through: date,
        destination: dict[date, str],
    ) -> None:
        """Calculate one nearby group without scanning unrelated history."""

        history_start = dates[0]
        remaining_days = (through - dates[-1]).days
        history_through = (
            through
            if remaining_days <= 7
            else dates[-1] + timedelta(days=7)
        )
        _, history = self._build_weekly_chain_history(
            habit,
            history_start,
            history_through,
            open_day=through,
        )
        for on_date in dates:
            destination[on_date] = history[(on_date - history_start).days]

    def weekly_chain_history(
        self,
        habit: Habit,
        through: date | None = None,
    ) -> tuple[date, list[str]]:
        """Build one contiguous weekly display history in a single pass."""

        if habit.schedule != WEEKLY:
            raise ValueError("Weekly chain history requires a weekly habit.")

        through = through or date.today()
        history_start = habit.created_on
        if through < history_start:
            return history_start, []
        return self._build_weekly_chain_history(
            habit, history_start, through, open_day=through
        )

    def _build_weekly_chain_history(
        self,
        habit: Habit,
        history_start: date,
        through: date,
        *,
        open_day: date,
    ) -> tuple[date, list[str]]:
        """Build display state for a range from its sparse prior state."""

        symbols: list[str] = []
        (
            phase,
            attempt_start,
            attempt_count,
            rolling,
        ) = self._weekly_state_before(habit, history_start)
        attempt_entries = [-1] if phase == "building" else []
        active_last_entry = -1 if phase == "active" else None
        habit_entries = self._entries_by_habit.get(habit.id, {})

        cursor = history_start
        while cursor <= through:
            raw = habit_entries.get(cursor, 0)
            rolling += raw
            if (cursor - habit.created_on).days >= 7:
                expired = cursor - timedelta(days=7)
                rolling -= habit_entries.get(expired, 0)
            is_open_day = cursor == open_day

            if (
                phase == "building"
                and attempt_start is not None
                and (cursor - attempt_start).days > 6
            ):
                if attempt_entries:
                    for index in range(
                        max(0, attempt_entries[0]), len(symbols)
                    ):
                        if symbols[index] == "*":
                            symbols[index] = "."
                phase = "idle"
                attempt_start = None
                attempt_count = 0
                attempt_entries = []

            if (
                phase == "active"
                and not is_open_day
                and rolling < habit.target
            ):
                if active_last_entry is not None:
                    for index in range(active_last_entry + 1, len(symbols)):
                        if symbols[index] == "*":
                            symbols[index] = "."
                phase = "idle"
                attempt_start = None
                attempt_count = 0
                attempt_entries = []
                active_last_entry = None

            symbol = "."
            if phase == "idle":
                if raw:
                    phase = "building"
                    attempt_start = cursor
                    attempt_count = raw
                    attempt_entries = [len(symbols)]
                    symbol = str(attempt_count)
            elif phase == "building":
                if raw:
                    attempt_count += raw
                    attempt_entries.append(len(symbols))
                    symbol = str(attempt_count)
                else:
                    symbol = "." if is_open_day else "*"
            else:
                if raw:
                    if active_last_entry is not None:
                        for index in range(
                            active_last_entry + 1, len(symbols)
                        ):
                            if symbols[index] == "*":
                                symbols[index] = "-"
                    active_last_entry = len(symbols)
                    symbol = "X"
                else:
                    symbol = "." if is_open_day else "*"

            symbols.append(symbol)
            if phase == "building" and attempt_count >= habit.target:
                for entry_index in attempt_entries:
                    if entry_index >= 0:
                        symbols[entry_index] = "X"
                for index in range(
                    max(0, attempt_entries[0]),
                    attempt_entries[-1] + 1,
                ):
                    if symbols[index] == "*":
                        symbols[index] = "-"
                active_last_entry = attempt_entries[-1]
                phase = "active"

            if cursor == through:
                break
            cursor += timedelta(days=1)

        return history_start, symbols

    def _weekly_state_before(
        self, habit: Habit, before: date
    ) -> tuple[str, date | None, int, int]:
        """Derive weekly state from sparse entry and expiration events."""

        if before <= habit.created_on:
            return "idle", None, 0, 0

        habit_entries = self._entries_by_habit.get(habit.id, {})
        entry_dates = [
            on_date
            for on_date, count in habit_entries.items()
            if count > 0 and habit.created_on <= on_date < before
        ]
        change_dates = set(entry_dates)
        change_dates.update(
            on_date + timedelta(days=7)
            for on_date in entry_dates
            if (before - on_date).days > 7
        )

        phase = "idle"
        attempt_start: date | None = None
        attempt_count = 0
        rolling = 0
        for cursor in sorted(change_dates):
            raw = habit_entries.get(cursor, 0)
            rolling += raw
            if (cursor - habit.created_on).days >= 7:
                rolling -= habit_entries.get(
                    cursor - timedelta(days=7), 0
                )

            if (
                phase == "building"
                and attempt_start is not None
                and (cursor - attempt_start).days > 6
            ):
                phase = "idle"
                attempt_start = None
                attempt_count = 0

            if phase == "active" and rolling < habit.target:
                phase = "idle"
                attempt_start = None
                attempt_count = 0

            if phase == "idle":
                if raw:
                    phase = "building"
                    attempt_start = cursor
                    attempt_count = raw
            elif phase == "building" and raw:
                attempt_count += raw

            if phase == "building" and attempt_count >= habit.target:
                phase = "active"

        return phase, attempt_start, attempt_count, rolling

    def status(self, habit: Habit, on_date: date) -> DayStatus:
        raw = self.raw_count(habit, on_date)
        progress = (
            self.rolling_count(habit, on_date)
            if habit.schedule == WEEKLY
            else raw
        )
        complete = progress >= habit.target
        if habit.schedule == WEEKLY:
            symbol = (
                "X"
                if complete and raw
                else str(progress)
                if raw
                else "*"
                if progress
                else "."
            )
        else:
            symbol = "X" if complete else (str(progress) if progress else ".")
        return DayStatus(raw, progress, habit.target, complete, symbol)

    def streaks(
        self, habit: Habit, through: date | None = None
    ) -> tuple[int, int]:
        """Return the current and best completed-day streaks.

        An unfinished current day does not break yesterday's active chain.
        """

        through = through or date.today()
        if through < habit.created_on:
            return (0, 0)

        intervals = self._completion_intervals(habit, through)
        best = max(
            ((end - start).days + 1 for start, end in intervals),
            default=0,
        )

        current = 0
        for start, end in reversed(intervals):
            if start <= through <= end:
                current = (through - start).days + 1
                break
            if through > date.min:
                yesterday = through - timedelta(days=1)
                if start <= yesterday <= end:
                    current = (yesterday - start).days + 1
                    break
                if end < yesterday:
                    break
        return current, best

    def _completion_intervals(
        self, habit: Habit, through: date
    ) -> list[tuple[date, date]]:
        """Return merged date ranges on which the habit was complete."""

        counts = self._entries_by_habit.get(habit.id, {})
        if habit.schedule == DAILY:
            completed_dates = sorted(
                on_date
                for on_date, count in counts.items()
                if habit.created_on <= on_date <= through
                and count >= habit.target
            )
            intervals: list[tuple[date, date]] = []
            for on_date in completed_dates:
                self._merge_interval(intervals, on_date, on_date)
            return intervals

        entry_dates = sorted(
            on_date
            for on_date, count in counts.items()
            if count > 0 and habit.created_on <= on_date <= through
        )
        intervals = []
        for index in range(len(entry_dates) - habit.target + 1):
            first = entry_dates[index]
            last = entry_dates[index + habit.target - 1]
            if (last - first).days > 6:
                continue
            remaining_days = (through - first).days
            interval_end = (
                through
                if remaining_days <= 6
                else first + timedelta(days=6)
            )
            self._merge_interval(
                intervals,
                last,
                interval_end,
            )
        return intervals

    @staticmethod
    def _merge_interval(
        intervals: list[tuple[date, date]], start: date, end: date
    ) -> None:
        if intervals and (start - intervals[-1][1]).days <= 1:
            previous_start, previous_end = intervals[-1]
            intervals[-1] = (previous_start, max(previous_end, end))
        else:
            intervals.append((start, end))

    def overall_best(
        self, through: date | None = None
    ) -> tuple[int, Habit | None]:
        through = through or date.today()
        winner: Habit | None = None
        winner_current = 0
        best_days = 0
        for habit in self.habits:
            current, best = self.streaks(habit, through)
            if best > best_days:
                winner = habit
                winner_current = current
                best_days = best
            elif best == best_days and winner is not None:
                if current > winner_current:
                    winner = habit
                    winner_current = current
        return best_days, winner

    def iter_entries(self) -> Iterable[tuple[Habit, date, int]]:
        habits = {habit.id: habit for habit in self.habits}
        for (habit_id, on_date), count in sorted(
            self.entries.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            habit = habits.get(habit_id)
            if habit is not None and count > 0:
                yield habit, on_date, count
