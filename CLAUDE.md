# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-page Streamlit app ("7기 출결 계산기" — a cohort attendance calculator) for tracking daily
attendance status (정상출석/지각/조퇴/외출/결석/공가) against a 2026 program schedule (May–Dec), and
computing whether attendance stays above required thresholds. All UI copy and domain labels are in Korean.

## Commands

Install dependencies:
```
pip install -r requirements.txt
```

Run the app locally:
```
streamlit run app.py
```

There is no test suite, linter, or build step in this repo.

## Architecture

Two files:

- `attendance.py` — pure calculation module. `calculate_attendance_tool()` takes a month (5–12) plus
  absence/tardy/early-leave/out counts and returns totals, attendance rate, and thresholds. Has no
  Streamlit or I/O dependency; `MONTH_TOTAL_DAYS` is the hardcoded class-day count per month. This is
  where attendance-policy math changes should go.
- `app.py` — the Streamlit UI and all state/persistence logic. Key pieces:
  - **Persistence**: attendance records (`st.session_state.daily_records`, keyed by `"YYYY-MM-DD"` date
    string) are synced to/from a GitHub Gist (file `attendance_data.json`) via `load_from_gist()` /
    `save_to_gist()`, using `GITHUB_TOKEN` and `GIST_ID` read from `st.secrets`. There is no local
    database — the Gist is the only persistent store, and every save/delete round-trips through it.
  - **Attendance rules encoded in app.py** (not in `attendance.py`): every 3 tardies/early-leaves/outs
    converts into 1 additional absence (`// 3` division, applied twice — once for the live dashboard via
    `count_attendance_vectorized()`, once identically for the simulator section). `HOLIDAYS_2026` and
    weekend dates disable input for that day. 공가(official leave) is capped at `max_official_leave`
    (20% of the month's total days from `attendance.py`) and enforced at save time.
  - **Page sections in order**: month selector → status dashboard (remaining safe absences, attendance
    rate, official-leave usage, tardy/early/out "chances" remaining) → single-date record entry
    (save/delete, backed by the Gist) → a what-if simulator (same math, not persisted) → full list of the
    selected month's saved records with per-record delete.
  - `st.secrets` (`GITHUB_TOKEN`, `GIST_ID`) must be present in `.streamlit/secrets.toml` (not committed)
    for persistence to work; without them, `load_from_gist`/`save_to_gist` silently no-op and the app
    runs with in-memory-only state for that session.

If you change the tardy/early/out → absence conversion logic or the official-leave cap, update it in
both the dashboard aggregation and the simulator in `app.py` — they are currently two separate
implementations of the same rule, not a shared helper.
