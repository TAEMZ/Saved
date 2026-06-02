"""One-off connection test for Supabase Postgres.
Run it, paste your full connection string when prompted (input is hidden),
and it will: connect, create all tables, and verify a round-trip.
The string is NOT written to disk or printed."""
import os
import getpass

url = getpass.getpass("Paste full Supabase connection string (hidden, then Enter): ").strip()
if not url or "[YOUR-PASSWORD]" in url:
    print("❌ That still has the [YOUR-PASSWORD] placeholder — paste the real one.")
    raise SystemExit(1)

os.environ["DATABASE_URL"] = url

# import AFTER setting the env var so database.py picks Postgres mode
import importlib
import database
importlib.reload(database)
import userlang
importlib.reload(userlang)

print("USE_PG:", database.USE_PG)
try:
    database.init_db()
    print("✅ Connected and tables created.")
    database.set_display_name(1, "ConnTest")
    print("✅ Write/read OK. display_name =", database.get_display_name(1))
    userlang.set_language(1, "en")
    print("✅ Language table OK. lang =", userlang.get_language(1))
    # clean up the test row
    with database.get_connection() as conn:
        database._exec(conn.cursor(), "DELETE FROM user_settings WHERE chat_id = ?", (1,))
        database._exec(conn.cursor(), "DELETE FROM user_language WHERE chat_id = ?", (1,))
        conn.commit()
    print("✅ Cleanup done. Supabase is ready.")
except Exception as e:
    print("❌ Connection/setup failed:")
    print("   ", repr(e))
    print("\nCommon causes:")
    print(" - wrong password")
    print(" - used the 'direct' (IPv6) string instead of the Session pooler (port 5432)")
    print(" - psycopg not installed: pip install --user 'psycopg[binary]'")
