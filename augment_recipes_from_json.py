"""Augment existing recipes (restaurant_id=1) with ingredient data from
hale_street_cantina_recipes.json.

Strategy:
- Match by case-insensitive name (whitespace-trimmed)
- Skip JSON entries whose status is null
- Add RecipeIngredient rows from each match
- Populate Recipe.xtra_chef_id from the JSON 'id' field
- Populate Recipe.pos_id and Recipe.toast_guid from sizes[0] (posId / guid)
  when the recipe has size variants in the source JSON
- Existing ingredients are NOT touched (none should exist for the 620
  CSV-imported recipes, but we don't delete just in case)
"""
import json
from app import app, db
from database import Recipe, RecipeIngredient

RESTAURANT_ID = 1
SOURCE = "/root/restaurant-ops/data/recipes/hale_street_cantina_recipes.json"


def normkey(name: str) -> str:
    return (name or "").strip().lower()


def main():
    with open(SOURCE) as f:
        json_recipes = json.load(f)

    # Build lookup, skipping null-status records. If duplicate names exist,
    # keep the first (we'll report duplicates).
    by_name = {}
    skipped_null_status = 0
    duplicate_names = 0
    for jr in json_recipes:
        if jr.get("status") is None:
            skipped_null_status += 1
            continue
        key = normkey(jr.get("name"))
        if not key:
            continue
        if key in by_name:
            duplicate_names += 1
            continue
        by_name[key] = jr

    print(f"JSON recipes loaded: {len(json_recipes)}")
    print(f"  skipped (null status):  {skipped_null_status}")
    print(f"  duplicate names dropped: {duplicate_names}")
    print(f"  usable lookup entries:   {len(by_name)}")

    with app.app_context():
        recipes = Recipe.query.filter_by(restaurant_id=RESTAURANT_ID).all()
        print(f"DB recipes for restaurant_id={RESTAURANT_ID}: {len(recipes)}")

        matched = 0
        unmatched = 0
        ingredients_added = 0
        unmatched_examples = []

        for r in recipes:
            jr = by_name.get(normkey(r.name))
            if not jr:
                unmatched += 1
                if len(unmatched_examples) < 10:
                    unmatched_examples.append(r.name)
                continue

            matched += 1
            xc_id = jr.get("id")
            if xc_id is not None:
                r.xtra_chef_id = str(xc_id)

            sizes = jr.get("sizes") or []
            if sizes:
                first = sizes[0] or {}
                if first.get("posId"):
                    r.pos_id = str(first["posId"])
                if first.get("guid"):
                    r.toast_guid = str(first["guid"])

            for ing in jr.get("ingredients", []):
                name = (ing.get("name") or "").strip()
                if not name:
                    continue
                qty = ing.get("quantity")
                cost = ing.get("cost") or 0
                yield_pct = ing.get("yieldPercent")
                if qty is None or qty == 0:
                    quantity = 0.0
                    unit_cost = float(cost)  # store line cost as fallback
                else:
                    quantity = float(qty)
                    unit_cost = float(cost) / quantity if quantity else 0.0
                db.session.add(RecipeIngredient(
                    recipe_id=r.id,
                    name=name,
                    quantity=quantity,
                    unit=(ing.get("uom") or "").strip(),
                    unit_cost=unit_cost,
                    yield_percent=float(yield_pct) if yield_pct is not None else 100.0,
                ))
                ingredients_added += 1

        db.session.commit()

        print()
        print("=== Augment summary ===")
        print(f"Recipes matched:      {matched}")
        print(f"Recipes unmatched:    {unmatched}")
        print(f"Ingredients added:    {ingredients_added}")
        if unmatched_examples:
            print(f"Sample unmatched names ({len(unmatched_examples)} of {unmatched}):")
            for n in unmatched_examples:
                print(f"  - {n}")


if __name__ == "__main__":
    main()
