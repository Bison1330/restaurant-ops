"""Add cross-system ID columns to recipes/inventory_items and create item_maps.

Idempotent: skips columns that already exist; uses CREATE TABLE IF NOT EXISTS
via SQLAlchemy create_all() for the new ItemMap table. Safe to re-run.
"""
from sqlalchemy import inspect, text
from app import app, db
from database import ItemMap  # noqa: F401  (import so create_all sees it)


RECIPE_COLUMNS = [
    ("toast_guid", "VARCHAR(100)"),
    ("pos_id", "VARCHAR(100)"),
]

INVENTORY_COLUMNS = [
    ("toast_guid", "VARCHAR(100)"),
    ("gfs_sku", "VARCHAR(50)"),
    ("fintech_code", "VARCHAR(50)"),
    ("xtra_chef_id", "VARCHAR(100)"),
]


def add_columns(table: str, columns):
    insp = inspect(db.engine)
    existing = {c["name"] for c in insp.get_columns(table)}
    added = []
    skipped = []
    with db.engine.begin() as conn:
        for name, ddl in columns:
            if name in existing:
                skipped.append(name)
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
            added.append(name)
    print(f"{table}: added {added or '[]'}, skipped existing {skipped or '[]'}")


def main():
    with app.app_context():
        add_columns("recipes", RECIPE_COLUMNS)
        add_columns("inventory_items", INVENTORY_COLUMNS)

        # Create item_maps table (and any indexes) if missing.
        db.create_all()
        insp = inspect(db.engine)
        if "item_maps" in insp.get_table_names():
            print("item_maps table: present")
        else:
            print("item_maps table: MISSING (create_all failed?)")


if __name__ == "__main__":
    main()
