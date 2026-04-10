import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "safeset.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL,
            other_role TEXT,
            minor_name TEXT,
            minor_age INTEGER,
            guardian_name TEXT,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at TEXT,
            progress REAL NOT NULL DEFAULT 0,
            qr_code TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            location TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_id INTEGER NOT NULL,
            event_id INTEGER,
            checked_in_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (participant_id) REFERENCES participants (id),
            FOREIGN KEY (event_id) REFERENCES events (id)
        )
    """)

    # Add columns if upgrading an older database
    _add_column_if_missing(c, "participants", "progress", "REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(c, "participants", "completed_at", "TEXT")

    conn.commit()
    conn.close()


def _add_column_if_missing(cursor, table, column, col_type):
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    if column not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")
