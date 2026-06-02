"""Data layer. Uses PostgreSQL when DATABASE_URL is set (e.g. Render + Supabase),
and falls back to a local SQLite file otherwise (local development/testing).

Both backends share the same SQL thanks to a tiny placeholder translation and
ON CONFLICT upserts that work on SQLite 3.24+ and Postgres alike."""
import os
from datetime import datetime

import config
import encryption

DATABASE_URL = os.getenv("DATABASE_URL")
USE_PG = bool(DATABASE_URL)

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

    def _normalized_url():
        url = DATABASE_URL
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"
        return url
else:
    import sqlite3


def get_connection():
    if USE_PG:
        return psycopg.connect(_normalized_url(), row_factory=dict_row)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _s(sql):
    """Translate '?' placeholders to '%s' for psycopg; no-op for SQLite."""
    return sql.replace("?", "%s") if USE_PG else sql


def _exec(cursor, sql, params=()):
    cursor.execute(_s(sql), params)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def init_db():
    with get_connection() as conn:
        cur = conn.cursor()
        if USE_PG:
            pk = "SERIAL PRIMARY KEY"
            big = "BIGINT"
        else:
            pk = "INTEGER PRIMARY KEY AUTOINCREMENT"
            big = "INTEGER"

        cur.execute(f'''
            CREATE TABLE IF NOT EXISTS saved_messages (
                id {pk},
                chat_id {big} NOT NULL,
                telegram_message_id {big},
                text TEXT,
                media_type TEXT NOT NULL,
                media_file_id TEXT,
                created_at TEXT NOT NULL,
                reminder_time TEXT,
                is_reminded INTEGER DEFAULT 0,
                is_archived INTEGER DEFAULT 0,
                last_seen TEXT,
                nudge_count INTEGER DEFAULT 0
            )
        ''')
        cur.execute(f'''
            CREATE TABLE IF NOT EXISTS tags (
                id {pk},
                message_id INTEGER NOT NULL,
                tag_name TEXT NOT NULL,
                UNIQUE(message_id, tag_name)
            )
        ''')
        cur.execute(f'''
            CREATE TABLE IF NOT EXISTS user_settings (
                chat_id {big} PRIMARY KEY,
                timezone TEXT DEFAULT 'UTC',
                display_name TEXT,
                digest_enabled INTEGER DEFAULT 1
            )
        ''')
        cur.execute(f'''
            CREATE TABLE IF NOT EXISTS sync_states (
                chat_id {big} PRIMARY KEY,
                state TEXT NOT NULL,
                phone TEXT,
                phone_code_hash TEXT,
                session_string TEXT
            )
        ''')
        cur.execute(f'''
            CREATE TABLE IF NOT EXISTS user_language (
                chat_id {big} PRIMARY KEY,
                lang TEXT
            )
        ''')

        # Idempotent column migrations (for pre-existing databases).
        if USE_PG:
            migs = [
                "ALTER TABLE saved_messages ADD COLUMN IF NOT EXISTS last_seen TEXT",
                "ALTER TABLE saved_messages ADD COLUMN IF NOT EXISTS nudge_count INTEGER DEFAULT 0",
                "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS display_name TEXT",
                "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS digest_enabled INTEGER DEFAULT 1",
                "ALTER TABLE sync_states ADD COLUMN IF NOT EXISTS session_string TEXT",
            ]
            for m in migs:
                cur.execute(m)
        else:
            for m in (
                "ALTER TABLE saved_messages ADD COLUMN last_seen TEXT",
                "ALTER TABLE saved_messages ADD COLUMN nudge_count INTEGER DEFAULT 0",
                "ALTER TABLE user_settings ADD COLUMN display_name TEXT",
                "ALTER TABLE user_settings ADD COLUMN digest_enabled INTEGER DEFAULT 1",
                "ALTER TABLE sync_states ADD COLUMN session_string TEXT",
            ):
                try:
                    cur.execute(m)
                except Exception:
                    pass

        cur.execute("UPDATE saved_messages SET last_seen = created_at WHERE last_seen IS NULL")
        cur.execute('CREATE INDEX IF NOT EXISTS idx_chat_id ON saved_messages(chat_id)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_reminder ON saved_messages(reminder_time, is_reminded)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_tags_msg ON tags(message_id)')
        conn.commit()


# ---------------------------------------------------------------------------
# User settings / timezone
# ---------------------------------------------------------------------------
def set_user_timezone(chat_id, timezone_str):
    with get_connection() as conn:
        _exec(conn.cursor(),
              '''INSERT INTO user_settings (chat_id, timezone) VALUES (?, ?)
                 ON CONFLICT(chat_id) DO UPDATE SET timezone = excluded.timezone''',
              (chat_id, timezone_str))
        conn.commit()


def get_user_timezone(chat_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'SELECT timezone FROM user_settings WHERE chat_id = ?', (chat_id,))
        row = cur.fetchone()
        return row['timezone'] if row and row['timezone'] else 'UTC'


def set_display_name(chat_id, name):
    if not name:
        return
    with get_connection() as conn:
        _exec(conn.cursor(),
              '''INSERT INTO user_settings (chat_id, display_name) VALUES (?, ?)
                 ON CONFLICT(chat_id) DO UPDATE SET display_name = excluded.display_name''',
              (chat_id, name))
        conn.commit()


def get_display_name(chat_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'SELECT display_name FROM user_settings WHERE chat_id = ?', (chat_id,))
        row = cur.fetchone()
        return row['display_name'] if row and row['display_name'] else None


def get_digest_enabled(chat_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'SELECT digest_enabled FROM user_settings WHERE chat_id = ?', (chat_id,))
        row = cur.fetchone()
        return True if not row or row['digest_enabled'] is None else bool(row['digest_enabled'])


def set_digest_enabled(chat_id, enabled):
    with get_connection() as conn:
        _exec(conn.cursor(),
              '''INSERT INTO user_settings (chat_id, digest_enabled) VALUES (?, ?)
                 ON CONFLICT(chat_id) DO UPDATE SET digest_enabled = excluded.digest_enabled''',
              (chat_id, 1 if enabled else 0))
        conn.commit()


# ---------------------------------------------------------------------------
# Sync state
# ---------------------------------------------------------------------------
def set_sync_state(chat_id, state, phone=None, phone_code_hash=None, session_string=None):
    with get_connection() as conn:
        _exec(conn.cursor(), '''
            INSERT INTO sync_states (chat_id, state, phone, phone_code_hash, session_string)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                state = excluded.state,
                phone = COALESCE(excluded.phone, sync_states.phone),
                phone_code_hash = COALESCE(excluded.phone_code_hash, sync_states.phone_code_hash),
                session_string = COALESCE(excluded.session_string, sync_states.session_string)
        ''', (chat_id, state, phone, phone_code_hash, session_string))
        conn.commit()


def get_sync_state(chat_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'SELECT * FROM sync_states WHERE chat_id = ?', (chat_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def clear_sync_state(chat_id):
    with get_connection() as conn:
        _exec(conn.cursor(), 'DELETE FROM sync_states WHERE chat_id = ?', (chat_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Saved messages
# ---------------------------------------------------------------------------
def add_saved_message(chat_id, text, media_type, media_file_id=None, telegram_message_id=None):
    created_at = datetime.utcnow().isoformat()
    encrypted_text = encryption.encrypt_text(text)
    with get_connection() as conn:
        cur = conn.cursor()
        if USE_PG:
            _exec(cur, '''
                INSERT INTO saved_messages
                    (chat_id, telegram_message_id, text, media_type, media_file_id, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
            ''', (chat_id, telegram_message_id, encrypted_text, media_type,
                  media_file_id, created_at, created_at))
            new_id = cur.fetchone()['id']
        else:
            _exec(cur, '''
                INSERT INTO saved_messages
                    (chat_id, telegram_message_id, text, media_type, media_file_id, created_at, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (chat_id, telegram_message_id, encrypted_text, media_type,
                  media_file_id, created_at, created_at))
            new_id = cur.lastrowid
        conn.commit()
        return new_id


def set_reminder(message_id, reminder_time_dt):
    rt = reminder_time_dt.isoformat()
    with get_connection() as conn:
        _exec(conn.cursor(),
              'UPDATE saved_messages SET reminder_time = ?, is_reminded = 0 WHERE id = ?',
              (rt, message_id))
        conn.commit()


def add_tag(message_id, tag_name):
    tag_name = tag_name.lstrip('#').strip().lower()
    if not tag_name:
        return
    with get_connection() as conn:
        _exec(conn.cursor(),
              '''INSERT INTO tags (message_id, tag_name) VALUES (?, ?)
                 ON CONFLICT(message_id, tag_name) DO NOTHING''',
              (message_id, tag_name))
        conn.commit()


def get_message_tags(message_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'SELECT tag_name FROM tags WHERE message_id = ?', (message_id,))
        return [row['tag_name'] for row in cur.fetchall()]


def get_active_messages(chat_id, limit=50):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, '''
            SELECT * FROM saved_messages
            WHERE chat_id = ? AND is_archived = 0
            ORDER BY created_at DESC LIMIT ?
        ''', (chat_id, limit))
        out = []
        for row in cur.fetchall():
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            out.append(d)
        return out


def get_messages_by_tag(chat_id, tag_name, limit=50):
    tag_name = tag_name.lstrip('#').strip().lower()
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, '''
            SELECT sm.* FROM saved_messages sm
            JOIN tags t ON sm.id = t.message_id
            WHERE sm.chat_id = ? AND t.tag_name = ? AND sm.is_archived = 0
            ORDER BY sm.created_at DESC LIMIT ?
        ''', (chat_id, tag_name, limit))
        out = []
        for row in cur.fetchall():
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            out.append(d)
        return out


def get_all_tags(chat_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, '''
            SELECT DISTINCT t.tag_name FROM tags t
            JOIN saved_messages sm ON t.message_id = sm.id
            WHERE sm.chat_id = ?
            ORDER BY t.tag_name ASC
        ''', (chat_id,))
        return [row['tag_name'] for row in cur.fetchall()]


def get_all_chat_ids():
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT chat_id FROM saved_messages')
        return [row['chat_id'] for row in cur.fetchall()]


def get_due_reminders():
    now_str = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, '''
            SELECT * FROM saved_messages
            WHERE reminder_time IS NOT NULL AND reminder_time <= ?
              AND is_reminded = 0 AND is_archived = 0
        ''', (now_str,))
        out = []
        for row in cur.fetchall():
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            out.append(d)
        return out


def mark_as_reminded(message_id):
    with get_connection() as conn:
        _exec(conn.cursor(), 'UPDATE saved_messages SET is_reminded = 1 WHERE id = ?', (message_id,))
        conn.commit()


def mark_as_archived(message_id):
    with get_connection() as conn:
        _exec(conn.cursor(), 'UPDATE saved_messages SET is_archived = 1 WHERE id = ?', (message_id,))
        conn.commit()


def mark_seen(message_id):
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        _exec(conn.cursor(),
              'UPDATE saved_messages SET last_seen = ?, nudge_count = 0 WHERE id = ?',
              (now, message_id))
        conn.commit()


def bump_nudge(message_id):
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        _exec(conn.cursor(),
              'UPDATE saved_messages SET last_seen = ?, nudge_count = nudge_count + 1 WHERE id = ?',
              (now, message_id))
        conn.commit()


def get_message_details(message_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'SELECT * FROM saved_messages WHERE id = ?', (message_id,))
        row = cur.fetchone()
        if row:
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            return d
        return None


def delete_message(message_id):
    with get_connection() as conn:
        cur = conn.cursor()
        _exec(cur, 'DELETE FROM tags WHERE message_id = ?', (message_id,))
        _exec(cur, 'DELETE FROM saved_messages WHERE id = ?', (message_id,))
        conn.commit()


def search_messages(chat_id, query_str, limit=50):
    """In-memory search so we can match against decrypted content."""
    messages = get_active_messages(chat_id, limit=1000)
    q = query_str.lower().strip()
    out = []
    for msg in messages:
        text_content = msg['text'] or ""
        if q in text_content.lower() or any(q in tg.lower() for tg in get_message_tags(msg['id'])):
            out.append(msg)
            if len(out) >= limit:
                break
    return out
