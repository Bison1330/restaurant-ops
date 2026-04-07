"""Import all_recipes.csv into the DB for restaurant_id=1.

Replaces any existing recipes for that restaurant. The source CSV has no
ingredients column, so RecipeIngredient rows are NOT created here — those
will need to come from a separate source (e.g. hale_street_cantina_recipes.json).
"""
import csv
import re
from app import app, db
from database import Recipe

RESTAURANT_ID = 1
SOURCE = "/root/restaurant-ops/data/recipes/all_recipes.csv"

BEVERAGE_KEYWORDS = ("beer", "wine", "liquor", "cocktail", "bev", "marg", "mixer")
STATUS_MAP = {"COMPLETE": "active", "DRAFT": "draft"}


def classify(recipe_group: str) -> str:
    g = (recipe_group or "").lower()
    return "beverage" if any(k in g for k in BEVERAGE_KEYWORDS) else "food"


def normalize_status(raw: str) -> str:
    return STATUS_MAP.get((raw or "").strip().upper(), "draft")


def parse_money(raw: str) -> float:
    """Strip $, %, commas, whitespace and return float. Empty -> 0.0."""
    if raw is None:
        return 0.0
    s = re.sub(r"[$,%\s]", "", raw)
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
                category = classify(row["recipe_group"])
                status = normalize_status(row["status"])
                menu_price = parse_money(row["menu_price"])
                food_cost = parse_money(row["food_cost"])
                food_cost_pct = parse_money(row["food_cost_pct"])
                gross_margin = menu_price - food_cost

                recipe = Recipe(
                    restaurant_id=RESTAURANT_ID,
                    name=row["recipe_name"],
                    menu_price=menu_price,
                    food_cost=food_cost,
                    food_cost_pct=food_cost_pct,
                    gross_margin=gross_margin,
                    status=status,
                    category=category,
                    subcategory=row["recipe_group"],
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
