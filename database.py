import sqlite3
from datetime import datetime
import os
import config
import encryption

# Determine database type (SQLite vs PostgreSQL)
IS_POSTGRES = bool(config.DATABASE_URL and config.DATABASE_URL.startswith("postgres"))

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Map sqlite3.IntegrityError to psycopg2.IntegrityError so existing try/except blocks catch it
    sqlite3.IntegrityError = psycopg2.IntegrityError

class CompatibleCursor:
    def __init__(self, cursor, is_postgres):
        self.cursor = cursor
        self.is_postgres = is_postgres
        
    def execute(self, query, params=()):
        if self.is_postgres:
            # Convert SQLite ? placeholders to PostgreSQL %s
            query = query.replace('?', '%s')
            # Convert SQLite AUTOINCREMENT to PostgreSQL SERIAL
            if "INTEGER PRIMARY KEY AUTOINCREMENT" in query:
                query = query.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        return self.cursor.execute(query, params)
        
    def fetchone(self):
        row = self.cursor.fetchone()
        if row and self.is_postgres:
            return dict(row)
        return row

    def fetchall(self):
        rows = self.cursor.fetchall()
        if self.is_postgres:
            return [dict(r) for r in rows]
        return rows

    def __getattr__(self, name):
        return getattr(self.cursor, name)

class CompatibleConnection:
    def __init__(self, conn, is_postgres):
        self.conn = conn
        self.is_postgres = is_postgres

    def cursor(self, *args, **kwargs):
        if self.is_postgres:
            import psycopg2.extras
            kwargs['cursor_factory'] = psycopg2.extras.RealDictCursor
            return CompatibleCursor(self.conn.cursor(*args, **kwargs), True)
        else:
            return CompatibleCursor(self.conn.cursor(*args, **kwargs), False)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def __enter__(self):
        self.conn.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self.conn.__exit__(exc_type, exc_val, exc_tb)

def get_connection():
    """Returns a connection to the SQLite or PostgreSQL database. Automatically wraps the cursor."""
    if IS_POSTGRES:
        conn = psycopg2.connect(config.DATABASE_URL)
        return CompatibleConnection(conn, True)
    else:
        conn = sqlite3.connect(config.DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        return CompatibleConnection(conn, False)



def init_db():
    """Initializes the database schema if it doesn't exist."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Create saved_messages table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS saved_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                telegram_message_id INTEGER,
                text TEXT,
                media_type TEXT NOT NULL,
                media_file_id TEXT,
                created_at TEXT NOT NULL,
                reminder_time TEXT,
                is_reminded INTEGER DEFAULT 0,
                is_archived INTEGER DEFAULT 0
            )
        ''')
        
        # Create tags table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                tag_name TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES saved_messages (id) ON DELETE CASCADE,
                UNIQUE(message_id, tag_name)
            )
        ''')
        
        # Create user_settings table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                chat_id INTEGER PRIMARY KEY,
                timezone TEXT DEFAULT 'UTC'
            )
        ''')
        
        # Create sync_states table for on-demand history sync state tracking
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sync_states (
                chat_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                phone TEXT,
                phone_code_hash TEXT,
                session_string TEXT
            )
        ''')
        # Add session_string column if it doesn't exist (for existing databases)
        has_column = False
        if IS_POSTGRES:
            cursor.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'sync_states' AND column_name = 'session_string'"
            )
            has_column = bool(cursor.fetchone())
        else:
            cursor.execute("PRAGMA table_info(sync_states)")
            for col in cursor.fetchall():
                try:
                    col_name = col['name']
                except (TypeError, KeyError, IndexError):
                    col_name = col[1]
                if col_name == 'session_string':
                    has_column = True
                    break

        if not has_column:
            try:
                cursor.execute('ALTER TABLE sync_states ADD COLUMN session_string TEXT')
            except Exception:
                pass

        
        # Indexes for fast lookup
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_id ON saved_messages(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_reminder ON saved_messages(reminder_time, is_reminded)')
        
        conn.commit()

def set_user_timezone(chat_id, timezone_str):
    """Sets the timezone for a user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO user_settings (chat_id, timezone)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET timezone = excluded.timezone
        ''', (chat_id, timezone_str))
        conn.commit()

def get_user_timezone(chat_id):
    """Gets the timezone for a user, defaulting to 'UTC'."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT timezone FROM user_settings WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        return row['timezone'] if row else 'UTC'

def set_sync_state(chat_id, state, phone=None, phone_code_hash=None, session_string=None):
    """Saves or updates the temporary sync state for a user's on-demand history import."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
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
    """Retrieves the sync state record for a user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM sync_states WHERE chat_id = ?', (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def clear_sync_state(chat_id):
    """Clears the sync state record for a user when finished or aborted."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM sync_states WHERE chat_id = ?', (chat_id,))
        conn.commit()

def add_saved_message(chat_id, text, media_type, media_file_id=None, telegram_message_id=None):
    """Saves a new message in the database. Returns the local database id. Encrypts text content."""
    created_at = datetime.utcnow().isoformat()
    encrypted_text = encryption.encrypt_text(text)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO saved_messages (chat_id, telegram_message_id, text, media_type, media_file_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (chat_id, telegram_message_id, encrypted_text, media_type, media_file_id, created_at))
        conn.commit()
        return cursor.lastrowid

def set_reminder(message_id, reminder_time_dt):
    """Sets a reminder time (datetime object) for a specific message ID."""
    reminder_time_str = reminder_time_dt.isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE saved_messages
            SET reminder_time = ?, is_reminded = 0
            WHERE id = ?
        ''', (reminder_time_str, message_id))
        conn.commit()

def add_tag(message_id, tag_name):
    """Associates a hashtag with a message. Removes hash prefix and normalizes to lower case."""
    tag_name = tag_name.lstrip('#').strip().lower()
    if not tag_name:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO tags (message_id, tag_name)
                VALUES (?, ?)
            ''', (message_id, tag_name))
            conn.commit()
        except sqlite3.IntegrityError:
            pass

def get_message_tags(message_id):
    """Returns a list of tags associated with a message."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT tag_name FROM tags WHERE message_id = ?', (message_id,))
        return [row['tag_name'] for row in cursor.fetchall()]

def get_active_messages(chat_id, limit=50):
    """Returns list of active (unarchived) messages for a user, decrypting their text content."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM saved_messages
            WHERE chat_id = ? AND is_archived = 0
            ORDER BY created_at DESC
            LIMIT ?
        ''', (chat_id, limit))
        
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            results.append(d)
        return results

def get_messages_by_tag(chat_id, tag_name, limit=50):
    """Returns list of active messages containing a specific tag, decrypting text content."""
    tag_name = tag_name.lstrip('#').strip().lower()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sm.* FROM saved_messages sm
            JOIN tags t ON sm.id = t.message_id
            WHERE sm.chat_id = ? AND t.tag_name = ? AND sm.is_archived = 0
            ORDER BY sm.created_at DESC
            LIMIT ?
        ''', (chat_id, tag_name, limit))
        
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            results.append(d)
        return results

def get_all_tags(chat_id):
    """Returns all unique tags used by a user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT DISTINCT t.tag_name FROM tags t
            JOIN saved_messages sm ON t.message_id = sm.id
            WHERE sm.chat_id = ?
            ORDER BY t.tag_name ASC
        ''', (chat_id,))
        return [row['tag_name'] for row in cursor.fetchall()]

def get_due_reminders():
    """Gets all messages that are due for a reminder, decrypting their text content."""
    now_str = datetime.utcnow().isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM saved_messages
            WHERE reminder_time IS NOT NULL AND reminder_time <= ? AND is_reminded = 0 AND is_archived = 0
        ''', (now_str,))
        
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            results.append(d)
        return results

def mark_as_reminded(message_id):
    """Marks a message as reminded."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE saved_messages SET is_reminded = 1 WHERE id = ?', (message_id,))
        conn.commit()

def mark_as_archived(message_id):
    """Archives a message so it doesn't show in active list or trigger reminders."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE saved_messages SET is_archived = 1 WHERE id = ?', (message_id,))
        conn.commit()

def get_message_details(message_id):
    """Returns details of a single message, decrypting its text."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM saved_messages WHERE id = ?', (message_id,))
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d['text'] = encryption.decrypt_text(d['text'])
            return d
        return None

def delete_message(message_id):
    """Deletes a message and its tags from the database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tags WHERE message_id = ?', (message_id,))
        cursor.execute('DELETE FROM saved_messages WHERE id = ?', (message_id,))
        conn.commit()

def search_messages(chat_id, query_str, limit=50):
    """Performs a text search in memory to support searching encrypted content."""
    # Fetch all active messages (up to a large limit)
    messages = get_active_messages(chat_id, limit=1000)
    
    query_lower = query_str.lower().strip()
    results = []
    
    for msg in messages:
        # Check text match
        text_content = msg['text'] or ""
        text_match = query_lower in text_content.lower()
        
        # Check tags match
        tags = get_message_tags(msg['id'])
        tag_match = any(query_lower in tag.lower() for tag in tags)
        
        if text_match or tag_match:
            results.append(msg)
            if len(results) >= limit:
                break
                
    return results
