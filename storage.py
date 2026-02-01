import os
import sqlite3
from datetime import datetime
from typing import Iterable, Optional

from models import Reminder


def _ensure_db_dir(db_path: str) -> None:
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _connect(db_path: str) -> sqlite3.Connection:
    _ensure_db_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_owner_column(conn: sqlite3.Connection) -> None:
    columns = conn.execute("PRAGMA table_info(reminders)").fetchall()
    column_names = {row["name"] for row in columns}
    if "owner_user_id" not in column_names:
        conn.execute(
            "ALTER TABLE reminders ADD COLUMN owner_user_id INTEGER NOT NULL DEFAULT 0"
        )


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                next_run TEXT NOT NULL,
                period TEXT NOT NULL,
                chat_ref TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_sent_at TEXT
            )
            """
        )
        _ensure_owner_column(conn)
        conn.commit()


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        owner_user_id=row["owner_user_id"],
        text=row["text"],
        next_run=datetime.fromisoformat(row["next_run"]),
        period=row["period"],
        chat_ref=row["chat_ref"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        last_sent_at=datetime.fromisoformat(row["last_sent_at"])
        if row["last_sent_at"]
        else None,
    )


def add_reminder(
    db_path: str,
    owner_user_id: int,
    text: str,
    next_run: datetime,
    period: str,
    chat_ref: str,
) -> int:
    now = datetime.utcnow().isoformat()
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (owner_user_id, text, next_run, period, chat_ref, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (owner_user_id, text, next_run.isoformat(), period, chat_ref, now, now),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_active_reminders(db_path: str, owner_user_id: int) -> Iterable[Reminder]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE status = 'active'
              AND owner_user_id = ?
            ORDER BY next_run ASC, id ASC
            """,
            (owner_user_id,),
        ).fetchall()
        return [_row_to_reminder(row) for row in rows]


def list_all_active_reminders(db_path: str) -> Iterable[Reminder]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE status = 'active'
            ORDER BY next_run ASC, id ASC
            """
        ).fetchall()
        return [_row_to_reminder(row) for row in rows]


def get_reminder(db_path: str, reminder_id: int) -> Optional[Reminder]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
        return _row_to_reminder(row) if row else None


def update_reminder(
    db_path: str,
    reminder_id: int,
    *,
    text: Optional[str] = None,
    next_run: Optional[datetime] = None,
    period: Optional[str] = None,
    chat_ref: Optional[str] = None,
    last_sent_at: Optional[datetime] = None,
) -> None:
    fields = []
    params = []
    if text is not None:
        fields.append("text = ?")
        params.append(text)
    if next_run is not None:
        fields.append("next_run = ?")
        params.append(next_run.isoformat())
    if period is not None:
        fields.append("period = ?")
        params.append(period)
    if chat_ref is not None:
        fields.append("chat_ref = ?")
        params.append(chat_ref)
    if last_sent_at is not None:
        fields.append("last_sent_at = ?")
        params.append(last_sent_at.isoformat())
    if not fields:
        return
    fields.append("updated_at = ?")
    params.append(datetime.utcnow().isoformat())
    params.append(reminder_id)

    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE reminders SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        conn.commit()


def deactivate_reminder(db_path: str, reminder_id: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            UPDATE reminders
            SET status = 'inactive', updated_at = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(), reminder_id),
        )
        conn.commit()
