"""
Inventory variance calculation engine.

Calculates expected inventory for each item:
    Expected = Last Count + Purchases (invoices) - Usage (estimated from sales/recipes)

Without Toast sales data, usage is estimated from the difference between
beginning inventory + purchases and what's expected to be on hand.
Once Toast sales data is connected, usage = sum(recipe_ingredient.quantity * items_sold).
"""

from datetime import datetime, timedelta
from database import (
    db, InventoryItem, Invoice, InvoiceLine, CountSession, CountEntry,
    StorageZone, InventoryItemZone,
)


def calculate_expected_counts(restaurant_id, count_date, previous_session_id=None):
    """
    Calculate expected inventory for each item based on:
    - Last count (from previous session, or current_stock as baseline)
    - Purchases since last count (from invoice lines)
    - Usage estimate (placeholder until Toast sales data is connected)

    Returns dict: { inventory_item_id: { 'expected': float, 'beginning': float,
                     'purchased': float, 'estimated_usage': float } }
    """
    items = InventoryItem.query.filter_by(restaurant_id=restaurant_id).all()
    results = {}

    # Get previous count date for purchase window
    if previous_session_id:
        prev_session = CountSession.query.get(previous_session_id)
        prev_date = prev_session.count_date if prev_session else None
    else:
        prev_session = (
            CountSession.query
            .filter_by(restaurant_id=restaurant_id)
            .filter(CountSession.status.in_(["submitted", "reviewed"]))
            .order_by(CountSession.count_date.desc())
            .first()
        )
        prev_date = prev_session.count_date if prev_session else None

    for item in items:
        # Beginning inventory: last count or current_stock
        beginning = item.current_stock or 0
        if prev_session:
            prev_entry = CountEntry.query.filter_by(
                session_id=prev_session.id,
                inventory_item_id=item.id,
            ).first()
            if prev_entry:
                beginning = prev_entry.actual_count

        # Purchases since last count
        purchased = _get_purchases_since(item.id, prev_date, count_date)

        # Estimated usage (placeholder — will use Toast sales × recipe quantities)
        # For now, estimate based on typical depletion rate from par level
        estimated_usage = _estimate_usage(item, prev_date, count_date)

        expected = beginning + purchased - estimated_usage

        results[item.id] = {
            "expected": round(max(expected, 0), 2),
            "beginning": round(beginning, 2),
            "purchased": round(purchased, 2),
            "estimated_usage": round(estimated_usage, 2),
        }

    return results


def _get_purchases_since(inventory_item_id, since_date, until_date):
    """Sum invoice line quantities for an item between two dates."""
    query = (
        db.session.query(db.func.sum(InvoiceLine.quantity))
        .join(Invoice, InvoiceLine.invoice_id == Invoice.id)
        .filter(InvoiceLine.inventory_item_id == inventory_item_id)
    )
    if since_date:
        query = query.filter(Invoice.invoice_date >= since_date)
    if until_date:
        query = query.filter(Invoice.invoice_date <= until_date)
    result = query.scalar()
    return float(result) if result else 0.0


def _estimate_usage(item, since_date, until_date):
    """
    Estimate usage for an item over a period.

    TODO: Replace with actual sales data from Toast:
        usage = sum(recipe_ingredient.quantity * toast_sales_count)
        for each recipe containing this item

    For now, use a simple heuristic based on par level as a proxy
    for weekly consumption rate.
    """
    if not since_date or not until_date:
        # Default to ~1 week of estimated usage
        days = 7
    else:
        days = (until_date - since_date).days

    if days <= 0:
        return 0

    # Rough estimate: par level represents ~1 week of stock
    weekly_rate = (item.par_level or 0) * 0.7  # assume ~70% of par is weekly usage
    daily_rate = weekly_rate / 7
    return round(daily_rate * days, 2)


def generate_variance_report(session_id):
    """
    Generate a variance report for a completed count session.
    Returns list of dicts with item details, expected, actual, variance info.
    """
    session = CountSession.query.get(session_id)
    if not session:
        return []

    report = []
    total_expected_value = 0
    total_actual_value = 0

    for entry in session.entries:
        item = entry.inventory_item
        expected_val = entry.expected_count * entry.unit_cost
        actual_val = entry.actual_count * entry.unit_cost
        variance_val = entry.variance_value
        total_expected_value += expected_val
        total_actual_value += actual_val

        flagged = abs(entry.variance_percent) > 10 if entry.expected_count > 0 else False

        report.append({
            "item_id": item.id,
            "item_name": item.name,
            "category": item.category,
            "zone": entry.storage_zone.name if entry.storage_zone else "Unassigned",
            "unit": item.unit,
            "unit_cost": entry.unit_cost,
            "expected": entry.expected_count,
            "actual": entry.actual_count,
            "variance": entry.variance,
            "variance_value": round(variance_val, 2),
            "variance_percent": round(entry.variance_percent, 1),
            "flagged": flagged,
            "notes": entry.notes or "",
        })

    # Sort: flagged items first, then by absolute variance value
    report.sort(key=lambda x: (-x["flagged"], -abs(x["variance_value"])))

    return {
        "session": session,
        "entries": report,
        "total_expected_value": round(total_expected_value, 2),
        "total_actual_value": round(total_actual_value, 2),
        "total_variance": round(total_actual_value - total_expected_value, 2),
        "flagged_count": sum(1 for r in report if r["flagged"]),
    }
