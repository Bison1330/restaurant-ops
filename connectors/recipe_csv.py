import csv
import io


def parse_recipe_csv(file_content):
    """
    Parse an xtra chef recipe CSV export into structured recipe dicts.

    Supports two common CSV formats:

    Format 1 — One row per ingredient:
        recipe_name, category, subcategory, menu_price, ingredient, quantity, unit, unit_cost
        Classic Burger, food, Entrees, 15.99, Ground Beef, 8, oz, 0.27
        Classic Burger, food, Entrees, 15.99, Burger Bun, 1, each, 0.39
        ...

    Format 2 — Recipe header + ingredient rows:
        [Recipe] Classic Burger, food, Entrees, 15.99
        Ground Beef, 8, oz, 0.27
        Burger Bun, 1, each, 0.39
        ...

    Returns list of recipe dicts with keys:
        name, category, subcategory, menu_price, ingredients (list of dicts)
    """
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8")

    lines = file_content.strip().splitlines()
    if not lines:
        return []

    # Detect format by checking first non-header line
    first_line = lines[0].strip()
    if first_line.lower().startswith("recipe_name") or first_line.lower().startswith("recipe name"):
        return _parse_flat_format(file_content)
    elif first_line.startswith("[Recipe]") or first_line.startswith("[recipe]"):
        return _parse_block_format(lines)
    else:
        # Try flat format as default
        return _parse_flat_format(file_content)


def _parse_flat_format(file_content):
    """One row per ingredient, recipe info repeated on each row."""
    reader = csv.reader(io.StringIO(file_content))
    header = None
    recipe_map = {}

    for row in reader:
        row = [c.strip() for c in row]
        if not row or len(row) < 6:
            continue

        # Detect and skip header row
        if row[0].lower() in ("recipe_name", "recipe name", "name"):
            header = [h.lower().replace(" ", "_") for h in row]
            continue

        if header:
            data = dict(zip(header, row))
            rname = data.get("recipe_name") or data.get("name", "")
            cat = data.get("category", "food")
            subcat = data.get("subcategory", "")
            price = _to_float(data.get("menu_price", 0))
            ing_name = data.get("ingredient") or data.get("ingredient_name", "")
            qty = _to_float(data.get("quantity", 0))
            unit = data.get("unit", "")
            cost = _to_float(data.get("unit_cost", 0))
        else:
            # No header — positional: recipe_name, category, subcategory, menu_price, ingredient, quantity, unit, unit_cost
            rname = row[0]
            cat = row[1] if len(row) > 1 else "food"
            subcat = row[2] if len(row) > 2 else ""
            price = _to_float(row[3]) if len(row) > 3 else 0
            ing_name = row[4] if len(row) > 4 else ""
            qty = _to_float(row[5]) if len(row) > 5 else 0
            unit = row[6] if len(row) > 6 else ""
            cost = _to_float(row[7]) if len(row) > 7 else 0

        if not rname:
            continue

        if rname not in recipe_map:
            recipe_map[rname] = {
                "name": rname,
                "category": cat.lower() if cat else "food",
                "subcategory": subcat,
                "menu_price": price,
                "ingredients": [],
            }

        if ing_name:
            recipe_map[rname]["ingredients"].append({
                "name": ing_name,
                "quantity": qty,
                "unit": unit,
                "unit_cost": cost,
            })

    return list(recipe_map.values())


def _parse_block_format(lines):
    """[Recipe] header lines followed by ingredient rows."""
    recipes = []
    current = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.lower().startswith("[recipe]"):
            if current:
                recipes.append(current)
            parts = [p.strip() for p in line[len("[Recipe]"):].split(",")]
            current = {
                "name": parts[0] if len(parts) > 0 else "",
                "category": (parts[1].lower() if len(parts) > 1 else "food"),
                "subcategory": parts[2] if len(parts) > 2 else "",
                "menu_price": _to_float(parts[3]) if len(parts) > 3 else 0,
                "ingredients": [],
            }
        elif current:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                current["ingredients"].append({
                    "name": parts[0],
                    "quantity": _to_float(parts[1]),
                    "unit": parts[2],
                    "unit_cost": _to_float(parts[3]),
                })

    if current:
        recipes.append(current)

    return recipes


def _to_float(val):
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0
