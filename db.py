"""SQLite session log for golden-hour-forge."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "golden_hour.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    city TEXT,
    shoot_date TEXT,
    scene TEXT,
    score REAL,
    verdict TEXT,
    self_rating INTEGER,
    notes TEXT,
    payload TEXT NOT NULL
);
"""


def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute(SCHEMA)
        conn.commit()


def create_session(result, payload):
    title = "%s - %s" % (result["scene"]["label"], result["location"]["date"])
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sessions (created_at, title, city, shoot_date, scene, score, "
            "verdict, self_rating, notes, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                title,
                result["location"].get("city") or "",
                result["location"]["date"],
                result["scene"]["key"],
                result["score"],
                result["verdict"],
                None,
                "",
                json.dumps(result),
            ),
        )
        conn.commit()
        return cur.lastrowid


def list_sessions(limit=50):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, created_at, title, city, shoot_date, scene, score, verdict, "
            "self_rating, notes FROM sessions ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session(session_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (int(session_id),)).fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data["result"] = json.loads(data.pop("payload"))
    except Exception:
        data["result"] = {}
    return data


def update_session(session_id, self_rating=None, notes=None):
    fields = []
    values = []
    if self_rating is not None:
        try:
            rating = int(self_rating)
        except Exception:
            rating = None
        if rating is not None and 1 <= rating <= 5:
            fields.append("self_rating = ?")
            values.append(rating)
    if notes is not None:
        fields.append("notes = ?")
        values.append(str(notes))
    if not fields:
        return get_session(session_id)
    values.append(int(session_id))
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET " + ", ".join(fields) + " WHERE id = ?", values)
        conn.commit()
    return get_session(session_id)


def delete_session(session_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (int(session_id),))
        conn.commit()
