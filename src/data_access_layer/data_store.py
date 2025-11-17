# data_access_layer/data_store.py
"""All data persistence goes through this interface. This implementation uses a local SQL DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import List, Optional, Iterable
from datetime import datetime, date, time

from data_object_model.application_state import Schedule, Entry, DateRange

# --- DB bootstrap ----------------------------------------------------------------

_DB_DIR = Path("db")
_DB_PATH = _DB_DIR / "app.sqlite3"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NULL,
    entry_date TEXT NOT NULL,      -- ISO date: YYYY-MM-DD
    start_time TEXT NOT NULL,      -- ISO time: HH:MM:SS
    end_time   TEXT NOT NULL,      -- ISO time: HH:MM:SS
    title      TEXT NOT NULL,
    provider   TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL       -- ISO datetime (UTC)
);

CREATE INDEX IF NOT EXISTS idx_entries_user_date
    ON entries(user_id, entry_date);

CREATE INDEX IF NOT EXISTS idx_entries_date
    ON entries(entry_date);
"""


def _ensure_db() -> None:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as con:
        con.executescript(_SCHEMA_SQL)
        con.commit()


_ensure_db()


@contextmanager
def _conn():
    con = sqlite3.connect(_DB_PATH)
    try:
        yield con
        con.commit()
    finally:
        con.close()


# --- Helpers ---------------------------------------------------------------------


def _to_iso_date(d: date) -> str:
    return d.isoformat()


def _to_iso_time(t: time) -> str:
    return t.strftime("%H:%M:%S")


def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_time(s: str) -> time:
    try:
        return time.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s, "%H:%M").time()


def _entry_from_row(row: tuple) -> Entry:
    """
    Convert a DB row (with full projection) into an Entry object.

    Expected row layout:
        (id, user_id, entry_date, start_time, end_time, title, provider, note, created_at)
    """
    entry_id, _user_id, entry_date, start_time, end_time, title, provider, note, _created_at = row
    return Entry(
        entry_id=entry_id,
        entry_date=entry_date,
        start_time=start_time,
        end_time=end_time,
        title=title,
        provider=provider,
        note=note or "",
    )


# --- Public API ------------------------------------------------------------------


def get_schedule(user_id: int, daterange: DateRange) -> Schedule:
    start_d = daterange.date_from.date()
    end_d = daterange.date_to.date()

    with _conn() as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT id,
                   entry_date,
                   start_time,
                   end_time,
                   title,
                   provider,
                   note
            FROM entries
            WHERE (user_id = ? OR user_id IS NULL)
              AND entry_date BETWEEN ? AND ?
            ORDER BY entry_date, start_time, id
            """,
            (user_id, _to_iso_date(start_d), _to_iso_date(end_d)),
        )
        rows = cur.fetchall()

        entries: List[Entry] = []

        for row in rows:
            entry_id, entry_date, start_time, end_time, title, provider, note = row
            entries.append(
                Entry(
                    entry_id=entry_id,
                    entry_date=entry_date,
                    start_time=start_time,
                    end_time=end_time,
                    title=title,
                    provider=provider,
                    note=note,
                )
            )

    print(
        f"Entries queried for user_id {user_id}, "
        f"from/to dates {_to_iso_date(start_d), _to_iso_date(end_d)}: {entries}"
    )
    return Schedule(daterange, entries=entries)


def get_entries_by_ids(entry_ids: Iterable[int]) -> List[Entry]:
    ids = list(entry_ids)
    if not ids:
        return []

    placeholders = ",".join("?" for _ in ids)
    with _conn() as con:
        cur = con.cursor()
        cur.execute(
            f"""
            SELECT id, user_id, entry_date, start_time, end_time, title, provider, note, created_at
            FROM entries
            WHERE id IN ({placeholders})
            ORDER BY entry_date, start_time, id
            """,
            tuple(ids),
        )
        rows = cur.fetchall()

    return [_entry_from_row(r) for r in rows]


def get_entries(
    user_id: Optional[int], date_from: datetime, date_to: datetime
) -> List[Entry]:
    start_d = date_from.date()
    end_d = date_to.date()

    with _conn() as con:
        cur = con.cursor()
        if user_id is None:
            cur.execute(
                """
                SELECT id, user_id, entry_date, start_time, end_time, title, provider, note, created_at
                FROM entries
                WHERE entry_date BETWEEN ? AND ?
                ORDER BY entry_date, start_time, id
                """,
                (_to_iso_date(start_d), _to_iso_date(end_d)),
            )
        else:
            cur.execute(
                """
                SELECT id, user_id, entry_date, start_time, end_time, title, provider, note, created_at
                FROM entries
                WHERE (user_id = ? OR user_id IS NULL)
                  AND entry_date BETWEEN ? AND ?
                ORDER BY entry_date, start_time, id
                """,
                (user_id, _to_iso_date(start_d), _to_iso_date(end_d)),
            )
        rows = cur.fetchall()

    return [_entry_from_row(r) for r in rows]


def add_entry(entry: Entry, user_id: Optional[int] = None) -> int:
    with _conn() as con:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO entries (user_id, entry_date, start_time, end_time, title, provider, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                _to_iso_date(entry.entry_date),
                _to_iso_time(entry.start_time),
                _to_iso_time(entry.end_time),
                entry.title,
                entry.provider,
                entry.note or "",
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        entry.entry_id = cur.lastrowid
        return entry.entry_id


def update_entry(entry: Entry, user_id: Optional[int] = None) -> int:
    with _conn() as con:
        cur = con.cursor()
        if user_id is None:
            cur.execute(
                """
                UPDATE entries
                SET entry_date = ?, start_time = ?, end_time = ?, title = ?, provider = ?, note = ?
                WHERE id = ?
                """,
                (
                    _to_iso_date(entry.entry_date),
                    _to_iso_time(entry.start_time),
                    _to_iso_time(entry.end_time),
                    entry.title,
                    entry.provider,
                    entry.note or "",
                    entry.entry_id,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE entries
                SET entry_date = ?, start_time = ?, end_time = ?, title = ?, provider = ?, note = ?
                WHERE id = ? AND (user_id = ? OR user_id IS NULL)
                """,
                (
                    _to_iso_date(entry.entry_date),
                    _to_iso_time(entry.start_time),
                    _to_iso_time(entry.end_time),
                    entry.title,
                    entry.provider,
                    entry.note or "",
                    entry.entry_id,
                    user_id,
                ),
            )
        return cur.rowcount


def remove_entry(entry: Entry, user_id: Optional[int] = None) -> int:
    with _conn() as con:
        cur = con.cursor()
        if user_id is None:
            cur.execute("DELETE FROM entries WHERE id = ?", (entry.entry_id,))
        else:
            cur.execute(
                "DELETE FROM entries WHERE id = ? AND (user_id = ? OR user_id IS NULL)",
                (entry.entry_id, user_id),
            )
        return cur.rowcount
