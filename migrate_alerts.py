"""Add the alerts table and restaurants.last_toast_sync column.

Idempotent: skips columns/tables that already exist. Uses raw sqlite3 because
importing app.py would touch the new model before the schema exists.
"""
import sqlite3

DB_PATH = "/root/restaurant-ops/data/restaurant_ops.db"


def main():
    with sqlite3.connect(DB_PATH) as conn:
        # restaurants.last_toast_sync
        cols = {row[1] for row in conn.execute("PRAGMA table_info(restaurants)")}
        if "last_toast_sync" not in cols:
            conn.execute("ALTER TABLE restaurants ADD COLUMN last_toast_sync DATETIME")
            print("restaurants: added last_toast_sync")
        else:
            print("restaurants: last_toast_sync already present")

        # alerts table
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "alerts" not in existing:
            conn.execute("""
                CREATE TABLE alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    restaurant_id INTEGER REFERENCES restaurants(id),
                    alert_type VARCHAR(50),
                    severity VARCHAR(20),
                    message VARCHAR(500),
                    resolved BOOLEAN DEFAULT 0,
                    created_at DATETIME,
                    resolved_at DATETIME
                )
            """)
            conn.execute("CREATE INDEX ix_alerts_restaurant_id ON alerts(restaurant_id)")
            conn.execute("CREATE INDEX ix_alerts_resolved ON alerts(resolved)")
            print("alerts: table created")
        else:
            print("alerts: table already present")

        conn.commit()


if __name__ == "__main__":
    main()
