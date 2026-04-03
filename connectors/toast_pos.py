import requests
import os
from datetime import datetime

TOAST_CLIENT_ID = os.environ.get("TOAST_CLIENT_ID")
TOAST_CLIENT_SECRET = os.environ.get("TOAST_CLIENT_SECRET")
TOAST_API_BASE = "https://ws-api.toasttab.com"


def _get_auth_token():
    resp = requests.post(
        f"{TOAST_API_BASE}/authentication/v1/authentication/login",
        json={
            "clientId": TOAST_CLIENT_ID,
            "clientSecret": TOAST_CLIENT_SECRET,
            "userAccessType": "TOAST_MACHINE_CLIENT",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("token", {}).get("accessToken", "")


def fetch_toast_menu(location_id):
    if not TOAST_CLIENT_ID or not TOAST_CLIENT_SECRET or not location_id:
        return _mock_menu()

    token = _get_auth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": location_id,
    }
    resp = requests.get(f"{TOAST_API_BASE}/menus/v2/menus", headers=headers)
    resp.raise_for_status()
    menus = resp.json()

    recipes = []
    for menu in menus:
        for group in menu.get("groups", []):
            for item in group.get("items", []):
                category = _classify_category(group.get("name", ""), item.get("name", ""))
                subcategory = group.get("name", "")
                recipe = {
                    "toast_recipe_id": item.get("guid", ""),
                    "name": item.get("name", ""),
                    "category": category,
                    "subcategory": subcategory,
                    "menu_price": float(item.get("price", 0) or 0),
                    "portion_size": item.get("portionSize", "1 serving"),
                    "ingredients": [],
                }
                for mod_group in item.get("modifierGroups", []):
                    for mod in mod_group.get("modifiers", []):
                        recipe["ingredients"].append({
                            "name": mod.get("name", ""),
                            "quantity": 1.0,
                            "unit": "each",
                            "unit_cost": float(mod.get("price", 0) or 0),
                        })
                recipes.append(recipe)

    return recipes


def _classify_category(group_name, item_name):
    beverage_keywords = [
        "drink", "cocktail", "beer", "wine", "spirit", "margarita",
        "beverage", "bar", "alcohol", "soda", "juice",
    ]
    combined = (group_name + " " + item_name).lower()
    for kw in beverage_keywords:
        if kw in combined:
            return "beverage"
    return "food"


def _mock_menu():
    return [
        # Food — Appetizers
        {
            "toast_recipe_id": "toast-app-001",
            "name": "Loaded Nachos",
            "category": "food",
            "subcategory": "Appetizers",
            "menu_price": 14.99,
            "portion_size": "1 plate",
            "ingredients": [
                {"name": "Tortilla Chips", "quantity": 8.0, "unit": "oz", "unit_cost": 0.12},
                {"name": "Cheddar Cheese", "quantity": 4.0, "unit": "oz", "unit_cost": 0.28},
                {"name": "Ground Beef", "quantity": 6.0, "unit": "oz", "unit_cost": 0.27},
                {"name": "Jalapeños", "quantity": 1.0, "unit": "oz", "unit_cost": 0.15},
                {"name": "Sour Cream", "quantity": 2.0, "unit": "oz", "unit_cost": 0.10},
                {"name": "Pico de Gallo", "quantity": 3.0, "unit": "oz", "unit_cost": 0.18},
            ],
        },
        {
            "toast_recipe_id": "toast-app-002",
            "name": "Wings (12pc)",
            "category": "food",
            "subcategory": "Appetizers",
            "menu_price": 16.99,
            "portion_size": "12 pieces",
            "ingredients": [
                {"name": "Chicken Wings", "quantity": 1.5, "unit": "lb", "unit_cost": 2.45},
                {"name": "Buffalo Sauce", "quantity": 3.0, "unit": "oz", "unit_cost": 0.15},
                {"name": "Fryer Oil", "quantity": 0.25, "unit": "lb", "unit_cost": 0.80},
                {"name": "Celery", "quantity": 2.0, "unit": "stalk", "unit_cost": 0.10},
                {"name": "Ranch Dressing", "quantity": 2.0, "unit": "oz", "unit_cost": 0.12},
            ],
        },
        # Food — Entrees
        {
            "toast_recipe_id": "toast-ent-001",
            "name": "Classic Smash Burger",
            "category": "food",
            "subcategory": "Entrees",
            "menu_price": 15.99,
            "portion_size": "1 burger",
            "ingredients": [
                {"name": "Ground Beef 80/20", "quantity": 8.0, "unit": "oz", "unit_cost": 0.27},
                {"name": "Burger Bun", "quantity": 1.0, "unit": "each", "unit_cost": 0.39},
                {"name": "Cheddar Cheese", "quantity": 2.0, "unit": "slice", "unit_cost": 0.18},
                {"name": "Romaine Lettuce", "quantity": 1.0, "unit": "leaf", "unit_cost": 0.08},
                {"name": "Tomato", "quantity": 2.0, "unit": "slice", "unit_cost": 0.10},
                {"name": "Pickle", "quantity": 3.0, "unit": "slice", "unit_cost": 0.04},
                {"name": "French Fries", "quantity": 6.0, "unit": "oz", "unit_cost": 0.15},
            ],
        },
        {
            "toast_recipe_id": "toast-ent-002",
            "name": "Grilled Salmon",
            "category": "food",
            "subcategory": "Entrees",
            "menu_price": 24.99,
            "portion_size": "1 plate",
            "ingredients": [
                {"name": "Salmon Fillet", "quantity": 8.0, "unit": "oz", "unit_cost": 0.70},
                {"name": "Lemon Butter Sauce", "quantity": 2.0, "unit": "oz", "unit_cost": 0.35},
                {"name": "Roasted Potatoes", "quantity": 6.0, "unit": "oz", "unit_cost": 0.06},
                {"name": "Asparagus", "quantity": 4.0, "unit": "spear", "unit_cost": 0.30},
            ],
        },
        {
            "toast_recipe_id": "toast-ent-003",
            "name": "Chicken Caesar Salad",
            "category": "food",
            "subcategory": "Entrees",
            "menu_price": 14.49,
            "portion_size": "1 bowl",
            "ingredients": [
                {"name": "Chicken Breast", "quantity": 6.0, "unit": "oz", "unit_cost": 0.22},
                {"name": "Romaine Lettuce", "quantity": 4.0, "unit": "oz", "unit_cost": 0.12},
                {"name": "Caesar Dressing", "quantity": 2.0, "unit": "oz", "unit_cost": 0.20},
                {"name": "Croutons", "quantity": 1.0, "unit": "oz", "unit_cost": 0.15},
                {"name": "Parmesan Cheese", "quantity": 1.0, "unit": "oz", "unit_cost": 0.40},
            ],
        },
        {
            "toast_recipe_id": "toast-ent-004",
            "name": "Fish Tacos",
            "category": "food",
            "subcategory": "Entrees",
            "menu_price": 16.49,
            "portion_size": "3 tacos",
            "ingredients": [
                {"name": "Cod Fillet", "quantity": 6.0, "unit": "oz", "unit_cost": 0.45},
                {"name": "Flour Tortilla", "quantity": 3.0, "unit": "each", "unit_cost": 0.12},
                {"name": "Cabbage Slaw", "quantity": 3.0, "unit": "oz", "unit_cost": 0.10},
                {"name": "Chipotle Aioli", "quantity": 1.5, "unit": "oz", "unit_cost": 0.25},
                {"name": "Lime", "quantity": 1.0, "unit": "wedge", "unit_cost": 0.08},
                {"name": "Cilantro", "quantity": 0.25, "unit": "oz", "unit_cost": 0.40},
            ],
        },
        # Beverage — Cocktails
        {
            "toast_recipe_id": "toast-ck-001",
            "name": "House Margarita",
            "category": "beverage",
            "subcategory": "Cocktails",
            "menu_price": 12.00,
            "portion_size": "1 drink",
            "ingredients": [
                {"name": "Tequila Silver", "quantity": 2.0, "unit": "oz", "unit_cost": 0.85},
                {"name": "Triple Sec", "quantity": 1.0, "unit": "oz", "unit_cost": 0.40},
                {"name": "Lime Juice", "quantity": 1.0, "unit": "oz", "unit_cost": 0.25},
                {"name": "Simple Syrup", "quantity": 0.5, "unit": "oz", "unit_cost": 0.05},
                {"name": "Salt Rim", "quantity": 1.0, "unit": "pinch", "unit_cost": 0.02},
            ],
        },
        {
            "toast_recipe_id": "toast-ck-002",
            "name": "Moscow Mule",
            "category": "beverage",
            "subcategory": "Cocktails",
            "menu_price": 13.00,
            "portion_size": "1 drink",
            "ingredients": [
                {"name": "Tito's Vodka", "quantity": 2.0, "unit": "oz", "unit_cost": 0.95},
                {"name": "Ginger Beer", "quantity": 4.0, "unit": "oz", "unit_cost": 0.30},
                {"name": "Lime Juice", "quantity": 0.75, "unit": "oz", "unit_cost": 0.25},
                {"name": "Lime Wedge", "quantity": 1.0, "unit": "each", "unit_cost": 0.08},
            ],
        },
        {
            "toast_recipe_id": "toast-ck-003",
            "name": "Old Fashioned",
            "category": "beverage",
            "subcategory": "Cocktails",
            "menu_price": 14.00,
            "portion_size": "1 drink",
            "ingredients": [
                {"name": "Bourbon", "quantity": 2.0, "unit": "oz", "unit_cost": 1.10},
                {"name": "Simple Syrup", "quantity": 0.25, "unit": "oz", "unit_cost": 0.05},
                {"name": "Angostura Bitters", "quantity": 2.0, "unit": "dash", "unit_cost": 0.10},
                {"name": "Orange Peel", "quantity": 1.0, "unit": "each", "unit_cost": 0.06},
                {"name": "Cherry", "quantity": 1.0, "unit": "each", "unit_cost": 0.20},
            ],
        },
        # Beverage — Beer
        {
            "toast_recipe_id": "toast-br-001",
            "name": "Modelo Especial Draft",
            "category": "beverage",
            "subcategory": "Beer",
            "menu_price": 7.00,
            "portion_size": "16oz pour",
            "ingredients": [
                {"name": "Modelo Especial Keg", "quantity": 16.0, "unit": "oz", "unit_cost": 0.11},
                {"name": "CO2", "quantity": 0.1, "unit": "oz", "unit_cost": 0.05},
            ],
        },
        # Beverage — Wine
        {
            "toast_recipe_id": "toast-wn-001",
            "name": "House Cabernet (Glass)",
            "category": "beverage",
            "subcategory": "Wine",
            "menu_price": 11.00,
            "portion_size": "6oz pour",
            "ingredients": [
                {"name": "House Cabernet", "quantity": 6.0, "unit": "oz", "unit_cost": 0.28},
            ],
        },
    ]
