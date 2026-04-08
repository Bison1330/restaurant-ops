"""Create the menu_item_sales table for the PMIX product-mix system.

Idempotent — safe to re-run. Uses SQLAlchemy's create_all() which only creates
tables that don't already exist, and verifies the table is present afterward.
"""

from app import app, db
from database import MenuItemSale
from sqlalchemy import inspect


def main():
    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        if "menu_item_sales" in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns("menu_item_sales")]
            print(f"[migrate_pmix] menu_item_sales OK ({len(cols)} columns): {cols}")
        else:
            print("[migrate_pmix] FAILED — menu_item_sales not found after create_all()")


if __name__ == "__main__":
    main()
