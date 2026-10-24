# HabitChain-TUI

A small, keyboard-driven Python habit tracker for the terminal. It uses
the "don't break the chain" method and stores everything directly in a
human-readable CSV file. This repository contains the second-generation app.

## Run it

```bash
python3 habit_chain.py
```

The first run creates `habits.csv` beside the app. To keep the data somewhere
else, or to use TSV, pass a filename:

```bash
python3 habit_chain.py --data /path/to/my-habits.csv
python3 habit_chain.py --data /path/to/my-habits.tsv
```

Requires Python 3.11 or newer on Linux or macOS. There are no third-party
dependencies. The app uses Python's built-in `curses` module. It starts with
an empty tracker; add your own habits with `a`. No habit history is bundled.

## Keys

- `Up` / `Down` or `j` / `k`: choose a habit
- `Left` / `Right` or `h` / `l`: choose a date
- `[` / `]`: move one week
- `g`: return to today
- `Space` or `Enter`: add one completion
- `Backspace` or `-`: remove one completion
- `e`: enter an exact count for the selected date
- `0`: clear the selected date
- `a`: add a habit
- `c`: change a habit
- `d`: delete a habit and its history
- `s`: save now (all changes already autosave)
- `Esc`: cancel the current input
- `?`: show help
- `q`: quit

## How goals work

For a once-daily habit, an unfinished day is `.` and a finished day is `X`.
For a multiple-times-per-day habit, the symbol progresses through `1`, `2`,
and so on, then becomes `X` when the target is reached.

A weekly habit uses a rolling seven-day window ending on each displayed date.
Its target can be from one to seven completions because a weekly habit can be
marked at most once per day.
Days before a chain starts, the current open spot, and days after a break are
shown as `.`. Elapsed gaps inside an attempt are shown as a colored `*`.
Pressing Space on logged days grows an attempt through `1`, `2`, and so on.
Each weekly habit can be marked at most once on a given day; pressing Space
again on the same day does not add another completion.
When the target is reached within seven days, that attempt's numbered marks
become `X`, and the `*` gaps linked between them become `-`, such as
`1-*-2-*-*-.` becoming `X---X-----X`. Logged marks remain `X` while the rolling
target stays complete. Trailing `*` symbols show the still-possible portion;
they become linked `-` symbols when another successful mark closes that
portion. If a past day falls below the rolling target, the chain breaks and
the next logged mark starts again at `1`. An underlined weekly symbol means
that the specific day contains one or more logged completions.

The current streak shown at the end of each line does not treat an unfinished
today as broken; yesterday's chain remains active until today is over. The best
historical chain is shown beside it and the best chain across all habits is
shown at the top.

## CSV format

The file has one `habit` row per configured habit and one `entry` row per date
with a non-zero count:

```csv
record_type,habit_id,habit_name,schedule,target,date,count,created_on
habit,a1b2c3d4e5f6,Exercise,weekly,3,,,2026-07-01
entry,a1b2c3d4e5f6,,,,2026-07-03,1,
```

Writes are atomic: the app writes a complete temporary file and then replaces
the CSV, which reduces the chance of a partial file if the app is interrupted.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests use temporary files and invented habits. User CSV/TSV data is
ignored by Git. Data is stored locally as plain text, without encryption.

## License

MIT. See [LICENSE](LICENSE).
