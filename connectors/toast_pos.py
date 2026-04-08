import requests
import os
import time
from datetime import datetime, timezone

TOAST_API_BASE = "https://ws-api.toasttab.com"

# Per-client_id token cache: { client_id: {"token": str, "expires_at": float} }
_TOKEN_CACHE = {}
_TOKEN_TTL_SECONDS = 23 * 60 * 60  # 23 hours


def _resolve_credentials(restaurant):
    """Pull client_id, client_secret, location_id from a Restaurant object,
    falling back to env vars if the DB columns are NULL."""
    client_id = getattr(restaurant, "toast_client_id", None) or os.environ.get("TOAST_CLIENT_ID")
    client_secret = getattr(restaurant, "toast_client_secret", None) or os.environ.get("TOAST_CLIENT_SECRET")
    location_id = getattr(restaurant, "toast_location_id", None)
    if not client_id or not client_secret or not location_id:
        raise ValueError(
            f"Missing Toast credentials for restaurant id={getattr(restaurant, 'id', '?')}: "
            f"client_id={'set' if client_id else 'MISSING'}, "
            f"client_secret={'set' if client_secret else 'MISSING'}, "
            f"location_id={'set' if location_id else 'MISSING'}"
        )
    return client_id, client_secret, location_id


def get_toast_token(restaurant):
    """Authenticate against Toast for the given restaurant and return a bearer
    token, cached for 23h per client_id so multiple restaurants can hold
    independent tokens at once."""
    client_id, client_secret, _ = _resolve_credentials(restaurant)
    now = time.time()
    cached = _TOKEN_CACHE.get(client_id)
    if cached and cached["expires_at"] > now:
        return cached["token"]

    resp = requests.post(
        f"{TOAST_API_BASE}/authentication/v1/authentication/login",
        json={
            "clientId": client_id,
            "clientSecret": client_secret,
            "userAccessType": "TOAST_MACHINE_CLIENT",
        },
    )
    resp.raise_for_status()
    token = resp.json().get("token", {}).get("accessToken", "")
    _TOKEN_CACHE[client_id] = {"token": token, "expires_at": now + _TOKEN_TTL_SECONDS}
    return token


def _auth_headers(restaurant):
    _, _, location_id = _resolve_credentials(restaurant)
    return {
        "Authorization": f"Bearer {get_toast_token(restaurant)}",
        "Toast-Restaurant-External-ID": location_id,
    }


def _job_lookup(restaurant):
    """Fetch jobs for a restaurant and return {job_guid: title}."""
    resp = requests.get(
        f"{TOAST_API_BASE}/labor/v1/jobs",
        headers=_auth_headers(restaurant),
    )
    resp.raise_for_status()
    return {j.get("guid"): j.get("title", "") for j in resp.json()}


def _mark_synced(restaurant):
    """Stamp restaurant.last_toast_sync. The caller's existing commit picks
    up the change because restaurant is a SQLAlchemy ORM object."""
    try:
        restaurant.last_toast_sync = datetime.utcnow()
    except Exception:
        pass


def fetch_employees(restaurant):
    """Return a list of employee dicts for the given Restaurant.

    Each dict: {guid, first_name, last_name, email, wage, job_title}.
    Skips employees flagged deleted.
    """
    resp = requests.get(
        f"{TOAST_API_BASE}/labor/v1/employees",
        headers=_auth_headers(restaurant),
    )
    resp.raise_for_status()
    raw = resp.json()
    _mark_synced(restaurant)

    jobs = _job_lookup(restaurant)
    employees = []
    for e in raw:
        if e.get("deleted"):
            continue
        wage_overrides = e.get("wageOverrides") or []
        raw_wage = float(wage_overrides[0]["wage"]) if wage_overrides else 0.0

        # Toast returns either an hourly rate or an annual salary in the same
        # `wage` field. Anything > $500 is almost certainly an annual figure
        # (max plausible hourly is ~$200 even for senior staff). Convert
        # annuals to an hourly equivalent using a 2080-hour standard year.
        if raw_wage > 500:
            pay_type = "salary"
            pay_rate = round(raw_wage / 2080.0, 2)
        else:
            pay_type = "hourly"
            pay_rate = raw_wage

        job_refs = e.get("jobReferences") or []
        job_title = jobs.get(job_refs[0]["guid"], "") if job_refs else ""
        employees.append({
            "guid": e.get("guid"),
            "first_name": e.get("firstName") or "",
            "last_name": e.get("lastName") or "",
            "email": e.get("email") or "",
            "wage": pay_rate,
            "pay_type": pay_type,
            "annual_salary": raw_wage if pay_type == "salary" else None,
            "job_title": job_title,
        })
    return employees


def fetch_timesheets(restaurant, start_date, end_date):
    """Fetch time entries between start_date and end_date.

    Accepts either datetime objects or pre-formatted ISO-8601 strings. Datetimes
    are normalized to `%Y-%m-%dT%H:%M:%S.000%z` because Toast's labor endpoint
    rejects the space-separated form Python's default str(datetime) produces and
    also rejects sub-second precision.

    Returns list of {employee_guid, in_date, out_date, hours, job_guid}.
    """
    def _fmt(d):
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%dT%H:%M:%S.000%z")
        return d
    params = {"startDate": _fmt(start_date), "endDate": _fmt(end_date)}
    resp = requests.get(
        f"{TOAST_API_BASE}/labor/v1/timeEntries",
        headers=_auth_headers(restaurant),
        params=params,
    )
    resp.raise_for_status()
    entries = []
    for t in resp.json():
        emp_ref = t.get("employeeReference") or {}
        job_ref = t.get("jobReference") or {}
        in_date = t.get("inDate")
        out_date = t.get("outDate")
        hours = 0.0
        fmt = "%Y-%m-%dT%H:%M:%S.%f%z"
        if in_date:
            try:
                in_dt = datetime.strptime(in_date, fmt)
                # If the shift is still open (no outDate), accrue against now —
                # callers expect labor cost to reflect on-the-clock employees,
                # not just completed shifts. Use UTC since inDate carries an offset.
                end_dt = datetime.strptime(out_date, fmt) if out_date else datetime.now(timezone.utc)
                hours = (end_dt - in_dt).total_seconds() / 3600.0
                if hours < 0:
                    hours = 0.0
            except ValueError:
                hours = 0.0
        entries.append({
            "employee_guid": emp_ref.get("guid"),
            "in_date": in_date,
            "out_date": out_date,
            "hours": round(hours, 2),
            "job_guid": job_ref.get("guid"),
        })
    return entries


def fetch_menu(restaurant):
    """Fetch the published menu and flatten to a list of items.

    The /menus/v2/menus response is a dict containing a `menus` array. Each menu
    has `menuGroups`, which can be nested recursively, and leaf groups expose
    items in a `menuItems` array. We walk the tree and return a flat list:
    {toast_guid, name, group_name, menu_name, price}.
    """
    resp = requests.get(
        f"{TOAST_API_BASE}/menus/v2/menus",
        headers=_auth_headers(restaurant),
    )
    resp.raise_for_status()
    _mark_synced(restaurant)
    payload = resp.json()
    items = []

    def walk_group(group, menu_name):
        group_name = group.get("name", "")
        for item in group.get("menuItems") or []:
            items.append({
                "toast_guid": item.get("guid", ""),
                "name": item.get("name", ""),
                "group_name": group_name,
                "menu_name": menu_name,
                "price": float(item.get("price", 0) or 0),
            })
        for sub in group.get("menuGroups") or []:
            walk_group(sub, menu_name)

    for menu in payload.get("menus", []):
        menu_name = menu.get("name", "")
        for group in menu.get("menuGroups", []) or []:
            walk_group(group, menu_name)
    return items


def fetch_orders(restaurant, start_date, end_date):
    """Fetch orders between start_date and end_date.

    Accepts either datetime objects or pre-formatted ISO-8601 strings. Datetimes
    are normalized to `%Y-%m-%dT%H:%M:%S.000%z` because Toast's ordersBulk
    endpoint rejects the space-separated form Python's default str(datetime)
    produces and also rejects sub-second precision.

    Returns list of {guid, opened_date, total, items: [{name, qty, price}]}.
    Pages through ordersBulk until an empty page is returned.
    """
    def _fmt(d):
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%dT%H:%M:%S.000%z")
        return d
    start_date = _fmt(start_date)
    end_date = _fmt(end_date)
    page = 1
    page_size = 100
    summaries = []
    while True:
        params = {
            "startDate": start_date,
            "endDate": end_date,
            "page": page,
            "pageSize": page_size,
        }
        resp = requests.get(
            f"{TOAST_API_BASE}/orders/v2/ordersBulk",
            headers=_auth_headers(restaurant),
            params=params,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        for order in batch:
            items_sold = []
            all_checks = order.get("checks") or []
            # Split checks into live vs voided. `total` and `net_sales` only
            # count live checks; voided ones are tracked separately in
            # `void_total` so the dashboard can surface lost revenue.
            live_checks = [c for c in all_checks if not c.get("voided")]
            voided_checks = [c for c in all_checks if c.get("voided")]
            for check in live_checks:
                for sel in check.get("selections", []) or []:
                    items_sold.append({
                        "name": sel.get("displayName") or sel.get("name") or "",
                        "qty": float(sel.get("quantity", 0) or 0),
                        "price": float(sel.get("price", 0) or 0),
                    })
            # Discounts: applied to live checks only. Voided check discounts
            # would be double-counting since the whole check is already lost.
            discount_total = 0.0
            for c in live_checks:
                for d in c.get("appliedDiscounts", []) or []:
                    discount_total += float(d.get("discountAmount", 0) or 0)
            summaries.append({
                "guid": order.get("guid"),
                "opened_date": order.get("openedDate"),
                # `total` = customer-paid (food + tax + tip). Matches what
                # operators see on the POS as "money in the door".
                "total": sum(float(c.get("totalAmount", 0) or 0) for c in live_checks),
                # `net_sales` = post-discount, pre-tax, pre-tip. The industry-
                # standard denominator for labor% and food cost%. Comes straight
                # from `check.amount`, which is already post-discount in Toast.
                "net_sales": sum(float(c.get("amount", 0) or 0) for c in live_checks),
                # Lost revenue tracking — surfaced separately so the dashboard
                # can show "discounts" and "voids" as two cards.
                "discount_total": discount_total,
                "void_total": sum(float(c.get("totalAmount", 0) or 0) for c in voided_checks),
                "items": items_sold,
            })
        if len(batch) < page_size:
            break
        page += 1
    return summaries


def fetch_toast_menu(restaurant):
    """Legacy shape used by older callers — wraps fetch_menu().

    Returns a list of recipe dicts: {toast_recipe_id, name, category,
    subcategory, menu_price, portion_size, ingredients}. Falls back to
    _mock_menu() when credentials are missing for the restaurant.
    """
    try:
        items = fetch_menu(restaurant)
    except (ValueError, requests.HTTPError):
        return _mock_menu()

    return [
        {
            "toast_recipe_id": it["toast_guid"],
            "name": it["name"],
            "category": _classify_category(it["group_name"], it["name"]),
            "subcategory": it["group_name"],
            "menu_price": it["price"],
            "portion_size": "1 serving",
            "ingredients": [],
        }
        for it in items
    ]


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


def fetch_employees_full(restaurant):
    """
    Pull full employee data from Toast including:
    - Multiple jobs (jobReferences)
    - Per-job wage overrides (wageOverrides)
    - Email, phone, preferred name

    Updates Employee, EmployeeJob, and EmployeeProfile records.
    Does NOT overwrite manually-set hire_date or profile notes.
    """
    import sys, os
    sys.path.insert(0, '/root/restaurant-ops')

    from database import db, Employee, EmployeeJob, EmployeeProfile
    from flask import current_app

    creds = _get_credentials(restaurant)
    if not creds:
        raise Exception(f"No Toast credentials for {restaurant.name}")

    token = _get_token(creds)
    headers = {
        "Authorization": f"Bearer {token}",
        "Toast-Restaurant-External-ID": creds["restaurant_guid"],
        "Content-Type": "application/json",
    }

    # Pull jobs list first so we can map job GUID → job name
    jobs_url = f"{TOAST_BASE}/labor/v1/jobs"
    jobs_resp = requests.get(jobs_url, headers=headers, timeout=30)
    job_map = {}  # guid → title
    if jobs_resp.status_code == 200:
        for job in jobs_resp.json():
            guid = job.get("guid", "")
            title = job.get("title", "")
            if guid and title:
                job_map[guid] = title

    # Pull employees
    emp_url = f"{TOAST_BASE}/labor/v1/employees"
    resp = requests.get(emp_url, headers=headers, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"Toast employees API returned {resp.status_code}")

    toast_employees = resp.json()
    updated = 0
    jobs_updated = 0

    for te in toast_employees:
        if te.get("deleted"):
            continue

        toast_guid = te.get("guid", "")
        if not toast_guid:
            continue

        emp = Employee.query.filter_by(
            restaurant_id=restaurant.id,
            toast_employee_id=toast_guid
        ).first()
        if not emp:
            continue

        # Update basic fields from Toast
        emp.first_name = te.get("firstName", emp.first_name)
        emp.last_name = te.get("lastName", emp.last_name)

        # Update or create profile with contact info
        profile = EmployeeProfile.query.filter_by(employee_id=emp.id).first()
        if not profile:
            profile = EmployeeProfile(employee_id=emp.id)
            db.session.add(profile)

        if te.get("email") and not profile.email:
            profile.email = te["email"]
        if te.get("phoneNumber") and not profile.phone:
            profile.phone = te["phoneNumber"]
        if te.get("chosenName") and not profile.preferred_name:
            profile.preferred_name = te["chosenName"]

        # Build wage override map: job_guid → wage
        wage_map = {}
        for wo in te.get("wageOverrides", []):
            job_guid = wo.get("jobReference", {}).get("guid", "")
            wage = wo.get("wage", 0)
            if job_guid:
                wage_map[job_guid] = wage

        # Update job records
        job_refs = te.get("jobReferences", [])
        if job_refs:
            # Clear existing job records for clean sync
            EmployeeJob.query.filter_by(employee_id=emp.id).delete()

            for i, jr in enumerate(job_refs):
                job_guid = jr.get("guid", "")
                job_name = job_map.get(job_guid, "")
                if not job_name:
                    continue
                wage = wage_map.get(job_guid, 0)
                is_primary = (i == 0)

                db.session.add(EmployeeJob(
                    employee_id=emp.id,
                    restaurant_id=restaurant.id,
                    toast_job_guid=job_guid,
                    job_name=job_name,
                    wage=wage,
                    is_primary=is_primary,
                ))
                jobs_updated += 1

                # Update employee's primary role and pay_rate
                if is_primary:
                    emp.role = job_name
                    emp.pay_rate = wage

        updated += 1

    db.session.commit()
    return {"updated": updated, "jobs_updated": jobs_updated}
