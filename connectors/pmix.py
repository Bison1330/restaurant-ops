"""Toast PMIX (product mix) connector.

Pulls every check selection from Toast `ordersBulk` for the given window and
aggregates by item GUID + display name. Returns a list of dicts sorted by
quantity sold descending.

Each result has the shape:
    {
        "toast_item_guid": str | None,
        "item_name": str,
        "category": str | None,
        "quantity": int,
        "unit_price": float,
        "total_revenue": float,
    }
"""

import requests
from datetime import datetime

from .toast_pos import TOAST_API_BASE, _auth_headers


def _fmt(d):
    """Toast's ordersBulk requires `%Y-%m-%dT%H:%M:%S.000%z` (no sub-second)."""
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%dT%H:%M:%S.000%z")
    return d


def fetch_pmix(restaurant, start_date, end_date):
    """Fetch product mix between start_date and end_date.

    Iterates Toast `/orders/v2/ordersBulk` paged at 100/page, walks
    checks → selections, and aggregates by `(toast_item_guid, item_name)`.
    Voided checks are excluded from quantity and revenue.

    Returns: list[dict] sorted by `quantity` descending.
    """
    start_date = _fmt(start_date)
    end_date = _fmt(end_date)

    page = 1
    page_size = 100
    # key -> aggregated dict
    bucket = {}

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
        batch = resp.json() or []
        if not batch:
            break

        for order in batch:
            for check in order.get("checks") or []:
                if check.get("voided"):
                    continue
                for sel in check.get("selections") or []:
                    if sel.get("voided"):
                        continue
                    guid = (sel.get("item") or {}).get("guid") or sel.get("itemGuid")
                    name = sel.get("displayName") or sel.get("name") or "(unnamed)"
                    qty = float(sel.get("quantity") or 0)
                    price = float(sel.get("price") or 0)  # line total in Toast
                    # Category: try selection.salesCategory.name, fall back to
                    # any nested itemGroup name we can find.
                    cat = None
                    sales_cat = sel.get("salesCategory") or {}
                    if isinstance(sales_cat, dict):
                        cat = sales_cat.get("name")
                    if not cat:
                        ig = sel.get("itemGroup") or {}
                        if isinstance(ig, dict):
                            cat = ig.get("name")

                    key = (guid, name)
                    row = bucket.get(key)
                    if row is None:
                        row = {
                            "toast_item_guid": guid,
                            "item_name": name,
                            "category": cat,
                            "quantity": 0,
                            "total_revenue": 0.0,
                        }
                        bucket[key] = row
                    row["quantity"] += int(qty) if qty.is_integer() else qty
                    row["total_revenue"] += price
                    if cat and not row["category"]:
                        row["category"] = cat

        if len(batch) < page_size:
            break
        page += 1

    results = []
    for row in bucket.values():
        qty = row["quantity"] or 0
        rev = row["total_revenue"] or 0.0
        row["unit_price"] = round(rev / qty, 2) if qty else 0.0
        row["total_revenue"] = round(rev, 2)
        results.append(row)

    results.sort(key=lambda r: r["quantity"], reverse=True)
    return results
