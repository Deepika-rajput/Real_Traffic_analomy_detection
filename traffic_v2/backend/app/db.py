import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source TEXT NOT NULL,              -- file path, rtsp:// url, or webcam index
    kind TEXT NOT NULL DEFAULT 'stream',   -- stream | upload
    lat REAL, lng REAL,
    road_type TEXT DEFAULT 'highway',
    enabled INTEGER NOT NULL DEFAULT 1,
    loop INTEGER NOT NULL DEFAULT 0,       -- replay a file forever (demo "live" camera)
    realtime INTEGER NOT NULL DEFAULT 1,   -- pace file playback at real speed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authorities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,                -- police | hospital | traffic_control | fire
    lat REAL NOT NULL, lng REAL NOT NULL,
    email TEXT NOT NULL,
    phone TEXT,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | pending_review | confirmed | dismissed
    severity TEXT NOT NULL DEFAULT 'low',   -- low | medium | high
    started_at TEXT NOT NULL,
    ended_at TEXT,
    video_t_start REAL, video_t_end REAL,
    peak_prob REAL,
    clip_path TEXT, snapshot_path TEXT,
    clip_duration_s REAL, clip_offset_s REAL,
    merged_count INTEGER NOT NULL DEFAULT 0,
    duplicate_of INTEGER,
    reviewer TEXT, review_note TEXT, dismiss_reason TEXT, reviewed_at TEXT,
    exported INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_cam ON events(camera_id, started_at);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    authority_id INTEGER NOT NULL REFERENCES authorities(id),
    to_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafted',  -- drafted | sent | dry_run | failed
    error TEXT,
    ack_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT, acked_at TEXT,
    escalated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_event ON alerts(event_id);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    """Tiny thread-safe sqlite wrapper (workers, API and escalation loop all share it)."""

    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def all(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def run(self, sql, args=()):
        """Execute a write; returns lastrowid."""
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def update(self, sql, args=()):
        """Execute a write; returns number of rows changed."""
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.rowcount

    def update_fields(self, table, row_id, **fields):
        if not fields:
            return 0
        cols = ", ".join(f"{k}=?" for k in fields)
        return self.update(f"UPDATE {table} SET {cols} WHERE id=?", (*fields.values(), row_id))

    def close(self):
        with self.lock:
            self.conn.close()
