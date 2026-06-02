# -*- coding: utf-8 -*-
"""Per-user language preference. Delegates to the shared database layer so it
works identically on SQLite (local) and Postgres (Render/Supabase)."""
import database


def init():
    # The user_language table is created in database.init_db().
    database.init_db()


def get_language(chat_id):
    with database.get_connection() as conn:
        cur = conn.cursor()
        database._exec(cur, "SELECT lang FROM user_language WHERE chat_id = ?", (chat_id,))
        row = cur.fetchone()
        return row['lang'] if row and row['lang'] else None


def set_language(chat_id, lang):
    with database.get_connection() as conn:
        database._exec(conn.cursor(),
                       """INSERT INTO user_language (chat_id, lang) VALUES (?, ?)
                          ON CONFLICT(chat_id) DO UPDATE SET lang = excluded.lang""",
                       (chat_id, lang))
        conn.commit()
