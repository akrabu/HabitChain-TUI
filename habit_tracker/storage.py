# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.

"""Human-readable CSV/TSV persistence."""

from __future__ import annotations

import csv
from datetime import date
import io
import os
from pathlib import Path
import tempfile

from .model import DAILY, WEEKLY, Habit, Tracker

FIELDS = (
    "record_type",
    "habit_id",
    "habit_name",
    "schedule",
    "target",
    "date",
    "count",
    "created_on",
)


class StorageError(RuntimeError):
    """Raised when the data file cannot be read or validated."""


class CSVStore:
    def __init__(self, path: Path):
        self.path = path

    @property
    def delimiter(self) -> str:
        return "\t" if self.path.suffix.lower() == ".tsv" else ","

    def load(self) -> Tracker:
        if not self.path.exists():
            return Tracker()

        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise StorageError(str(error)) from error

        if not text.strip():
            return Tracker()

        delimiter = "\t" if "\t" in text.partition("\n")[0] else ","
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
            rows = list(reader)
        except csv.Error as error:
            raise StorageError(f"invalid CSV: {error}") from error

        missing = [field for field in FIELDS if field not in (reader.fieldnames or ())]
        if missing:
            raise StorageError("missing columns: " + ", ".join(missing))
        if not rows:
            return Tracker()

        habits: list[Habit] = []
        by_id: dict[str, Habit] = {}
        entry_rows: list[tuple[int, dict[str, str]]] = []

        for line_number, row in enumerate(rows, start=2):
            kind = (row.get("record_type") or "").strip().lower()
            if not kind:
                continue
            if kind == "entry":
                entry_rows.append((line_number, row))
                continue
            if kind != "habit":
                raise StorageError(
                    f"line {line_number}: record_type must be habit or entry"
                )

            habit_id = (row.get("habit_id") or "").strip()
            if not habit_id:
                raise StorageError(f"line {line_number}: missing habit_id")
            if habit_id in by_id:
                raise StorageError(
                    f"line {line_number}: duplicate habit_id {habit_id!r}"
                )
            try:
                schedule = (row.get("schedule") or "").strip().lower()
                if schedule in {"day", "daily"}:
                    schedule = DAILY
                elif schedule in {"week", "weekly"}:
                    schedule = WEEKLY
                habit = Habit(
                    id=habit_id,
                    name=row.get("habit_name") or "",
                    schedule=schedule,
                    target=int(row.get("target") or ""),
                    created_on=date.fromisoformat(row.get("created_on") or ""),
                )
            except (TypeError, ValueError) as error:
                raise StorageError(f"line {line_number}: {error}") from error
            habits.append(habit)
            by_id[habit_id] = habit

        tracker = Tracker(habits=habits)
        seen_entries: set[tuple[str, date]] = set()
        for line_number, row in entry_rows:
            habit_id = (row.get("habit_id") or "").strip()
            habit = by_id.get(habit_id)
            if habit is None:
                raise StorageError(
                    f"line {line_number}: entry refers to unknown habit_id "
                    f"{habit_id!r}"
                )
            try:
                on_date = date.fromisoformat(row.get("date") or "")
                count = int(row.get("count") or "")
                key = (habit_id, on_date)
                if key in seen_entries:
                    raise ValueError(
                        f"duplicate entry for {habit_id!r} on {on_date}"
                    )
                if count <= 0:
                    raise ValueError("entry count must be greater than zero")
                tracker.set_count(habit, on_date, count)
                seen_entries.add(key)
            except (TypeError, ValueError) as error:
                raise StorageError(f"line {line_number}: {error}") from error
        return tracker

    def save(self, tracker: Tracker) -> None:
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                writer = csv.DictWriter(
                    handle,
                    fieldnames=FIELDS,
                    delimiter=self.delimiter,
                    lineterminator="\n",
                )
                writer.writeheader()
                for habit in tracker.habits:
                    writer.writerow(
                        {
                            "record_type": "habit",
                            "habit_id": habit.id,
                            "habit_name": habit.name,
                            "schedule": habit.schedule,
                            "target": habit.target,
                            "date": "",
                            "count": "",
                            "created_on": habit.created_on.isoformat(),
                        }
                    )
                for habit, on_date, count in tracker.iter_entries():
                    writer.writerow(
                        {
                            "record_type": "entry",
                            "habit_id": habit.id,
                            "habit_name": "",
                            "schedule": "",
                            "target": "",
                            "date": on_date.isoformat(),
                            "count": count,
                            "created_on": "",
                        }
                    )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(self.path.parent, directory_flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as error:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise StorageError(str(error)) from error
