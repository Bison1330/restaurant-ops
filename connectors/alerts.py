"""Alert generation rules.

run_alerts(restaurant_id) inspects current state and writes Alert rows for any
new conditions that aren't already represented by an unresolved alert. The
function is idempotent — re-running won't create duplicate active alerts for
the same condition.
"""
from datetime import datetime, timedelta

from database import (
    db, Alert, Invoice, InventoryItem, Recipe, InvoiceLine, Restaurant,
)


def _has_open_alert(restaurant_id, alert_type, message):
    """Avoid duplicating an unresolved alert with the same type+message."""
    return db.session.query(Alert.id).filter_by(
        restaurant_id=restaurant_id,
        alert_type=alert_type,
        message=message,
        resolved=False,
    ).first() is not None


def _add(restaurant_id, alert_type, severity, message):
    if _has_open_alert(restaurant_id, alert_type, message):
        return False
    db.session.add(Alert(
        restaurant_id=restaurant_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        resolved=False,
        created_at=datetime.utcnow(),
    ))
    return True


def _resolve_stale(restaurant_id, alert_type, current_messages):
    """Mark unresolved alerts of `alert_type` as resolved when their message
    is no longer in `current_messages` (i.e. the underlying condition has
    cleared, or the alert text has been superseded). Returns count resolved."""
    q = Alert.query.filter(
        Alert.restaurant_id == restaurant_id,
        Alert.alert_type == alert_type,
        Alert.resolved == False,  # noqa: E712
    )
    if current_messages:
        q = q.filter(Alert.message.notin_(current_messages))
    stale = q.all()
    now = datetime.utcnow()
    for a in stale:
        a.resolved = True
        a.resolved_at = now
    return len(stale)


def run_alerts(restaurant_id):
    """Run all checks for the given restaurant. Returns count of new alerts created."""
    created = 0
    today = datetime.utcnow().date()

    # Track the messages each check produces this run, so we can resolve any
    # previously-open alert of the same type whose condition no longer holds
    # (or whose text has been superseded by a new message).
    current = {
        "invoice_overdue": [],
        "low_stock": [],
        "zero_cost_recipe": [],
        "unmapped_invoice_line": [],
        "stale_toast_sync": [],
    }

    # a) Invoices overdue > 7 days (critical)
    cutoff = today - timedelta(days=7)
    overdue = Invoice.query.filter(
        Invoice.restaurant_id == restaurant_id,
        Invoice.status.in_(["pending", "approved"]),
        Invoice.due_date.isnot(None),
        Invoice.due_date < cutoff,
    ).all()
    for inv in overdue:
        days_late = (today - inv.due_date).days
        msg = f"Invoice {inv.invoice_number} is {days_late} days overdue (${inv.total_amount:,.2f})"
        current["invoice_overdue"].append(msg)
        if _add(restaurant_id, "invoice_overdue", "critical", msg):
            created += 1

    # b) Inventory items below par level (warning)
    low_stock = InventoryItem.query.filter(
        InventoryItem.restaurant_id == restaurant_id,
        InventoryItem.par_level > 0,
        InventoryItem.current_stock < InventoryItem.par_level,
    ).all()
    for item in low_stock:
        msg = f"{item.name}: {item.current_stock} {item.unit or ''} (par {item.par_level})"
        current["low_stock"].append(msg)
        if _add(restaurant_id, "low_stock", "warning", msg):
            created += 1

    # c) Active recipes with food_cost = 0 (warning).
    # Only flag recipes that have an xtra_chef_id — those came through with
    # ingredient data and should have a real cost. CSV-only recipes (no
    # xtra_chef_id) are intentionally cost-less and not actionable.
    zero_cost = Recipe.query.filter(
        Recipe.restaurant_id == restaurant_id,
        Recipe.status == "active",
        Recipe.food_cost == 0,
        Recipe.xtra_chef_id.isnot(None),
    ).all()
    if zero_cost:
        msg = f"{len(zero_cost)} active recipe(s) with xtraCHEF ID have food_cost = 0"
        current["zero_cost_recipe"].append(msg)
        if _add(restaurant_id, "zero_cost_recipe", "warning", msg):
            created += 1

    # d) Invoice lines with no inventory_item_id (info — unmapped)
    unmapped = (
        db.session.query(db.func.count(InvoiceLine.id))
        .join(Invoice, InvoiceLine.invoice_id == Invoice.id)
        .filter(Invoice.restaurant_id == restaurant_id, InvoiceLine.inventory_item_id.is_(None))
        .scalar()
        or 0
    )
    if unmapped > 0:
        msg = f"{unmapped} invoice line(s) have no inventory match"
        current["unmapped_invoice_line"].append(msg)
        if _add(restaurant_id, "unmapped_invoice_line", "info", msg):
            created += 1

    # e) Toast sync not run in 24 hours (warning)
    r = db.session.get(Restaurant, restaurant_id)
    if r and r.toast_client_id:  # only complain if Toast is configured
        last = r.last_toast_sync
        if not last or (datetime.utcnow() - last) > timedelta(hours=24):
            stale_for = "never" if not last else f"{(datetime.utcnow() - last).total_seconds() / 3600:.1f}h ago"
            msg = f"Toast sync stale (last: {stale_for})"
            current["stale_toast_sync"].append(msg)
            if _add(restaurant_id, "stale_toast_sync", "warning", msg):
                created += 1

    # Auto-resolve any open alerts whose underlying condition cleared.
    # Note: stale_toast_sync is only auto-resolved if Toast is still configured —
    # otherwise an unconfigured restaurant would never clear its old alert.
    for alert_type, msgs in current.items():
        if alert_type == "stale_toast_sync" and not (r and r.toast_client_id):
            continue
        _resolve_stale(restaurant_id, alert_type, msgs)

    db.session.commit()
    return created


def run_alerts_all():
    """Run alerts for every restaurant. Used by the scheduler job."""
    total = 0
    for r in Restaurant.query.all():
        total += run_alerts(r.id)
    return total
