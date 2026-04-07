"""Add toast_client_id and toast_client_secret columns to restaurants.

Idempotent: skips columns that already exist. Safe to re-run. Uses raw sqlite3
rather than importing app.py, because app.py boots a SQLAlchemy model that
already references the new columns — which would error before the migration
could run.
"""
import sqlite3

DB_PATH = "/root/restaurant-ops/data/restaurant_ops.db"

RESTAURANT_COLUMNS = [
    ("toast_client_id", "VARCHAR(100)"),
    ("toast_client_secret", "VARCHAR(200)"),
]


def add_columns(conn, table, columns):
    cur = conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    added = []
    skipped = []
    for name, ddl in columns:
        if name in existing:
            skipped.append(name)
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        added.append(name)
    print(f"{table}: added {added or '[]'}, skipped existing {skipped or '[]'}")


def main():
    with sqlite3.connect(DB_PATH) as conn:
        add_columns(conn, "restaurants", RESTAURANT_COLUMNS)
        conn.commit()


if __name__ == "__main__":
    main()
