#!/usr/bin/env python3
# Copyright (C) 2026 akrabu
# SPDX-License-Identifier: MIT
# See LICENSE for the full license text.
"""Habit Chain: a small, keyboard-driven habit tracker."""

from __future__ import annotations

import argparse
import curses
from pathlib import Path
import sys

from habit_tracker.storage import CSVStore, StorageError
from habit_tracker.ui import HabitChainApp


def parse_args() -> argparse.Namespace:
    default_data = Path(__file__).resolve().with_name("habits.csv")
    parser = argparse.ArgumentParser(
        description="A full-screen don't-break-the-chain habit tracker."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=default_data,
        help=f"CSV or TSV data file (default: {default_data})",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Use terminal attributes without color.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = CSVStore(args.data.expanduser().resolve())

    try:
        tracker = store.load()
        if not store.path.exists():
            store.save(tracker)
    except StorageError as error:
        print(f"Could not open habit data: {error}", file=sys.stderr)
        return 1

    app = HabitChainApp(tracker, store, use_color=not args.no_color)
    try:
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        return 130
    except curses.error as error:
        print(
            f"Could not start the full-screen terminal interface: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
