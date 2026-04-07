"""Import main_summary.csv into the DB for restaurant_id=3 (Main Street Pub).

Replaces any existing recipes for the restaurant. The CSV has no ingredients
column, so RecipeIngredient rows are NOT created here.
"""
import csv
from app import app, db
from database import Recipe

RESTAURANT_ID = 3
SOURCE = "/root/restaurant-ops/data/recipes/main_summary.csv"

BEVERAGE_KEYWORDS = ("beer", "wine", "liquor", "cocktail", "bev", "marg", "mixer", "shots")
STATUS_MAP = {"COMPLETE": "active", "DRAFT": "draft"}


def classify(recipe_group: str) -> str:
    g = (recipe_group or "").lower()
    return "beverage" if any(k in g for k in BEVERAGE_KEYWORDS) else "food"


def normalize_status(raw: str) -> str:
    return STATUS_MAP.get((raw or "").strip().upper(), "draft")


def normalize_subcategory(raw: str) -> str:
    """ALL-CAPS -> Title Case; mixed/lowercase left as-is; blank/'--' -> 'Uncategorized'."""
    s = (raw or "").strip()
    if not s or s == "--":
        return "Uncategorized"
    if s.isupper():
        return s.title()
    return s


def to_float(raw: str) -> float:
    if raw is None:
        return 0.0
    s = raw.strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def main():
    with app.app_context():
        existing = Recipe.query.filter_by(restaurant_id=RESTAURANT_ID).all()
        for r in existing:
            db.session.delete(r)
        db.session.commit()
        print(f"Deleted {len(existing)} existing recipes for restaurant_id={RESTAURANT_ID}")

        per_category = {"food": 0, "beverage": 0}
        per_status = {}
        total = 0

        with open(SOURCE, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                category = classify(row["RecipeGroup"])
                status = normalize_status(row["Status"])
                recipe = Recipe(
                    restaurant_id=RESTAURANT_ID,
                    name=row["RecipeName"].strip(),
                    menu_price=to_float(row["MenuPrice"]),
                    food_cost=to_float(row["FoodCost"]),
                    food_cost_pct=to_float(row["FoodCostPercentage"]),
                    gross_margin=to_float(row["GrossMargin"]),
                    status=status,
                    category=category,
                    subcategory=normalize_subcategory(row["RecipeGroup"]),
                )
                db.session.add(recipe)
                per_category[category] += 1
                per_status[status] = per_status.get(status, 0) + 1
                total += 1

        db.session.commit()

        print(f"Imported {total} recipes from {SOURCE}")
        print(f"  by category: {per_category}")
        print(f"  by status:   {per_status}")


if __name__ == "__main__":
    main()
