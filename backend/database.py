import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet

_IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> str:
    """Return current IST time as an ISO string (timezone-aware)."""
    return datetime.now(_IST).isoformat()

# ── Fernet encryption ─────────────────────────────────────────────────────────

_raw_key = os.getenv("SESSION_ENCRYPTION_KEY", "")
if _raw_key:
    _key_bytes = _raw_key.encode() if isinstance(_raw_key, str) else _raw_key
    _key_bytes += b"=" * (-len(_key_bytes) % 4)
    _fernet = Fernet(_key_bytes)
else:
    import base64, hashlib
    _seed = os.getenv("TELEGRAM_API_HASH", "fallback-key-change-me")
    _fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(_seed.encode()).digest()))


def encrypt_session(s: str) -> str:
    return _fernet.encrypt(s.encode()).decode() if s else ""


def decrypt_session(s: str) -> str:
    if not s:
        return ""
    try:
        return _fernet.decrypt(s.encode()).decode()
    except Exception:
        return s  # legacy plaintext


# ── Backend detection ─────────────────────────────────────────────────────────

_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
USE_POSTGRES = _DATABASE_URL.startswith("postgres")

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    _PG_DSN = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print("[db] Backend: PostgreSQL")
else:
    _DB_PATH = _DATABASE_URL.replace("sqlite:///./", "").replace("sqlite:///", "")
    os.makedirs(os.path.dirname(os.path.abspath(_DB_PATH)), exist_ok=True)
    print(f"[db] Backend: SQLite at {_DB_PATH}")


# ── Schema statements (each runs independently) ───────────────────────────────

_TABLES = [
    """CREATE TABLE IF NOT EXISTS projects (
        id {serial} PRIMARY KEY,
        name TEXT NOT NULL,
        tone TEXT DEFAULT 'casual',
        context TEXT DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS accounts (
        id {serial} PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id),
        phone TEXT NOT NULL UNIQUE,
        session_string TEXT DEFAULT '',
        status TEXT DEFAULT 'pending',
        personality TEXT DEFAULT '',
        job_description TEXT DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS chats (
        id {serial} PRIMARY KEY,
        account_id INTEGER REFERENCES accounts(id),
        chat_id TEXT NOT NULL,
        chat_name TEXT DEFAULT '',
        type TEXT DEFAULT 'dm',
        last_message TEXT DEFAULT '',
        unread_count INTEGER DEFAULT 0,
        monitored INTEGER DEFAULT 1,
        UNIQUE(account_id, chat_id)
    )""",
    """CREATE TABLE IF NOT EXISTS messages (
        id {serial} PRIMARY KEY,
        chat_id INTEGER REFERENCES chats(id),
        sender TEXT NOT NULL,
        text TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        is_outgoing INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS ai_drafts (
        id {serial} PRIMARY KEY,
        message_id INTEGER REFERENCES messages(id),
        draft_text TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        urgency TEXT DEFAULT 'medium',
        was_used INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS away_log (
        id {serial} PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id),
        account_id INTEGER REFERENCES accounts(id),
        chat_id TEXT NOT NULL,
        chat_name TEXT DEFAULT '',
        incoming_text TEXT NOT NULL,
        reply_text TEXT NOT NULL,
        category TEXT DEFAULT 'general',
        urgency TEXT DEFAULT 'medium',
        replied_at TEXT NOT NULL,
        reviewed INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS away_sessions (
        id {serial} PRIMARY KEY,
        project_id INTEGER UNIQUE REFERENCES projects(id),
        away_until TEXT NOT NULL,
        enabled_at TEXT NOT NULL,
        target_mode TEXT DEFAULT 'all',
        target_chat_ids TEXT DEFAULT '[]'
    )""",
    """CREATE TABLE IF NOT EXISTS suggested_groups (
        id {serial} PRIMARY KEY,
        group_id TEXT NOT NULL UNIQUE,
        username TEXT DEFAULT '',
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        members INTEGER DEFAULT 0,
        online_members INTEGER DEFAULT 0,
        category TEXT DEFAULT 'general',
        discovered_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS project_groups (
        id {serial} PRIMARY KEY,
        project_id INTEGER REFERENCES projects(id),
        account_id INTEGER,
        group_id TEXT NOT NULL,
        group_name TEXT DEFAULT '',
        username TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        monitored INTEGER DEFAULT 1,
        joined_at TEXT NOT NULL,
        UNIQUE(project_id, group_id)
    )""",
    """CREATE TABLE IF NOT EXISTS group_draft_cache (
        id {serial} PRIMARY KEY,
        project_id INTEGER NOT NULL,
        chat_id TEXT NOT NULL,
        draft_text TEXT NOT NULL,
        cached_at TEXT NOT NULL,
        UNIQUE(project_id, chat_id)
    )""",
]


def init_db():
    """Create all tables. Each statement runs in its own transaction so one
    failure never blocks the rest."""
    if USE_POSTGRES:
        serial = "SERIAL"
        seed_sql = """INSERT INTO projects (id, name, tone, context)
                      VALUES (1, 'Default Project', 'casual', 'General team communication project')
                      ON CONFLICT (id) DO NOTHING"""
    else:
        serial = "INTEGER"
        seed_sql = """INSERT OR IGNORE INTO projects (id, name, tone, context)
                      VALUES (1, 'Default Project', 'casual', 'General team communication project')"""

    for tpl in _TABLES:
        sql = tpl.replace("{serial}", serial)
        try:
            with get_conn() as conn:
                conn.execute(sql)
        except Exception as e:
            print(f"[db] init warning: {e}")

    try:
        with get_conn() as conn:
            conn.execute(seed_sql)
    except Exception as e:
        print(f"[db] seed warning: {e}")

    # Add new columns to existing tables (safe to re-run)
    _migrate_columns()

    # Backfill project_groups from existing chats so old joins aren't lost
    _backfill_project_groups()

    # One-time: clear ALL messages/drafts to free disk (accounts/groups preserved)
    _clear_messages_once()

    # Prune messages older than 24h on startup
    prune_messages()

    # Log account count so we know the DB is alive
    try:
        with get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) as n FROM accounts").fetchone()["n"]
            print(f"[db] init complete — {n} accounts in database")
    except Exception as e:
        print(f"[db] count check failed: {e}")


def _migrate_columns():
    """Add new columns introduced after initial deploy. Safe to re-run — errors are suppressed."""
    migrations = [
        "ALTER TABLE projects ADD COLUMN system_prompt TEXT DEFAULT ''",
        "ALTER TABLE chats ADD COLUMN write_restricted INTEGER DEFAULT 0",
        "ALTER TABLE project_groups ADD COLUMN write_restricted INTEGER DEFAULT 0",
        "ALTER TABLE project_groups ADD COLUMN auto_joined INTEGER DEFAULT 0",
        "ALTER TABLE project_groups ADD COLUMN human_score REAL DEFAULT 0.5",
        "ALTER TABLE project_groups ADD COLUMN left_at TEXT",
    ]
    for sql in migrations:
        try:
            with get_conn() as conn:
                conn.execute(sql)
        except Exception:
            pass  # column already exists — fine


def _clear_messages_once():
    """One-time migration: wipe all messages + ai_drafts and physically shrink the DB.

    Strategy for a full volume (503MB / 500MB):
      1. journal_mode=MEMORY  → journal lives in RAM, so DELETE works even at 0 free bytes
      2. VACUUM INTO /tmp     → writes compact DB to ephemeral FS (plenty of space there)
      3. Copy /tmp back       → open(original, 'wb') truncates it first, freeing 500 MB,
                                 then writes the compact ~few-MB file back
    """
    import shutil as _shutil, os as _os
    if USE_POSTGRES:
        return
    tmp_path = "/tmp/_app_compact.db"
    try:
        conn2 = sqlite3.connect(_DB_PATH)
        # Journal in RAM — DELETE runs even on a 100%-full volume
        conn2.execute("PRAGMA journal_mode=MEMORY")
        conn2.execute(
            "CREATE TABLE IF NOT EXISTS applied_migrations (name TEXT PRIMARY KEY)"
        )
        conn2.commit()
        row = conn2.execute(
            "SELECT 1 FROM applied_migrations WHERE name='clear_messages_v1'"
        ).fetchone()
        if row:
            conn2.close()
            return
        conn2.execute("DELETE FROM ai_drafts")
        conn2.execute("DELETE FROM messages")
        conn2.execute(
            "INSERT OR IGNORE INTO applied_migrations (name) VALUES ('clear_messages_v1')"
        )
        conn2.commit()
        print("[db] deleted all messages + ai_drafts")

        # Write compact copy to /tmp (ephemeral disk — not the mounted volume)
        if _os.path.exists(tmp_path):
            _os.unlink(tmp_path)
        try:
            conn2.execute(f"VACUUM INTO '{tmp_path}'")
            conn2.close()
            # Overwrite original: open(...,'wb') truncates to 0 first,
            # instantly freeing 500 MB from the volume, then writes the small file
            with open(tmp_path, "rb") as src, open(_DB_PATH, "wb") as dst:
                _shutil.copyfileobj(src, dst)
            _os.unlink(tmp_path)
            print("[db] compacted DB written back — volume space reclaimed")
        except Exception as ve:
            conn2.close()
            print(f"[db] compact step failed (DB still cleared): {ve}")
    except Exception as e:
        print(f"[db] clear_messages_once warning: {e}")


def prune_messages(keep_per_chat: int = 20):
    """Delete messages older than 24 hours and cap at keep_per_chat per chat.
    Also removes orphaned ai_drafts and runs VACUUM to reclaim disk space."""
    if USE_POSTGRES:
        return
    import datetime as _dt
    cutoff = (_dt.datetime.now(_IST) - _dt.timedelta(hours=24)).isoformat()
    try:
        with get_conn() as conn:
            # Drop anything older than 24 hours
            conn.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
            # Also cap per-chat to keep_per_chat most recent (belt-and-suspenders)
            conn.execute(
                """DELETE FROM messages WHERE id NOT IN (
                       SELECT id FROM (
                           SELECT id, ROW_NUMBER() OVER (
                               PARTITION BY chat_id ORDER BY id DESC
                           ) AS rn FROM messages
                       ) WHERE rn <= ?
                   )""",
                (keep_per_chat,),
            )
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM ai_drafts WHERE message_id NOT IN (SELECT id FROM messages)"
            )
        conn2 = sqlite3.connect(_DB_PATH)
        conn2.execute("VACUUM")
        conn2.close()
        print(f"[db] pruned messages older than 24h (cap {keep_per_chat}/chat); vacuumed disk")
    except Exception as e:
        print(f"[db] prune warning: {e}")


def _backfill_project_groups():
    """One-time migration: copy any chats (type=group) not yet in project_groups."""
    now = now_ist()
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT c.chat_id, c.chat_name, c.account_id, c.monitored, a.project_id
                   FROM chats c
                   JOIN accounts a ON c.account_id = a.id
                   WHERE c.type = 'group'"""
            ).fetchall()
        if not rows:
            return
        with get_conn() as conn:
            for r in rows:
                try:
                    conn.execute(
                        """INSERT INTO project_groups
                               (project_id, account_id, group_id, group_name, monitored, joined_at)
                           VALUES (?,?,?,?,?,?)
                           ON CONFLICT(project_id, group_id) DO NOTHING""",
                        (r["project_id"], r["account_id"], r["chat_id"],
                         r["chat_name"], r["monitored"], now),
                    )
                except Exception:
                    pass
        print(f"[db] backfilled {len(rows)} group(s) into project_groups")
    except Exception as e:
        print(f"[db] backfill warning: {e}")


# ── PostgreSQL row wrapper (makes psycopg2 rows behave like sqlite3.Row) ──────

class _PGConn:
    def __init__(self):
        self._conn = psycopg2.connect(_PG_DSN)
        self._conn.autocommit = False
        self._cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql: str, params=()):
        sql = sql.replace("?", "%s")
        self._cur.execute(sql, params)
        return self

    def fetchone(self):
        try:
            return self._cur.fetchone()
        except Exception:
            return None

    def fetchall(self):
        try:
            return self._cur.fetchall()
        except Exception:
            return []

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._cur.close()
            self._conn.close()
        except Exception:
            pass


# ── Connection context manager ────────────────────────────────────────────────

@contextmanager
def get_conn():
    if USE_POSTGRES:
        conn = _PGConn()
    else:
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(r) for r in rows]


def get_cached_group_draft(project_id: int, chat_id: str, max_age_hours: int = 4) -> str | None:
    """Return cached away-reply draft for this group if newer than max_age_hours."""
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT draft_text, cached_at FROM group_draft_cache WHERE project_id=? AND chat_id=?",
                (project_id, chat_id),
            ).fetchone()
        if not row:
            return None
        cached_at = datetime.fromisoformat(row["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=_IST)
        age_hours = (datetime.now(_IST) - cached_at).total_seconds() / 3600
        return row["draft_text"] if age_hours < max_age_hours else None
    except Exception:
        return None


def set_cached_group_draft(project_id: int, chat_id: str, draft_text: str):
    """Store or refresh cached away-reply draft for this group."""
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO group_draft_cache (project_id, chat_id, draft_text, cached_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(project_id, chat_id) DO UPDATE SET
                     draft_text=excluded.draft_text,
                     cached_at=excluded.cached_at""",
                (project_id, chat_id, draft_text, now_ist()),
            )
        print(f"[cache] stored draft for {chat_id}: {draft_text[:60]}")
    except Exception as e:
        print(f"[cache] set_cached_group_draft failed: {e}")
