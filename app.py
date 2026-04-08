import os
import uuid
from datetime import datetime, timedelta

import pytz

CENTRAL_TZ = pytz.timezone("US/Central")

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, send_file, jsonify, make_response
)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename

from database import (
    db, Restaurant, Vendor, InventoryItem, Invoice, InvoiceLine,
    PayrollRun, Employee, Recipe, RecipeIngredient,
    ItemAlias, PriceHistory, UnmatchedItem,
    StorageZone, InventoryItemZone, CountSession, CountEntry,
    Alert, MenuItemSale, Shift, User, Position, RestaurantSettings, ManagerPreference,
    PTOPolicy, PTOBalance, PTORequest, ScheduleWeek, ShiftTemplate, ShiftTemplateEntry,
    OpenShift, ProjectedSales, EmployeeAvailability,
)
from mock_data import seed_mock_data
from connectors.gfs_sftp import fetch_gfs_invoices
from connectors.fintech_api import fetch_fintech_invoices
from connectors.invoice_ocr import extract_invoice_from_image
from connectors.email_ingestion import poll_invoice_email
from connectors.qb_export import export_invoices_iif, export_payroll_iif
from connectors.toast_pos import fetch_toast_menu, fetch_orders, fetch_timesheets
from connectors.alerts import run_alerts, run_alerts_all
from connectors.pmix import fetch_pmix
from connectors.recipe_csv import parse_recipe_csv
from connectors.item_matcher import (
    match_item, update_price, confirm_match, create_new_from_unmatched,
    dismiss_unmatched, get_pending_unmatched, get_suggestions_for_unmatched,
    auto_link_recipe_ingredients,
)
from connectors.inventory_calc import calculate_expected_counts, generate_variance_report

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-in-production")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:////root/restaurant-ops/data/restaurant_ops.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

UPLOAD_FOLDER = "/root/restaurant-ops/data/uploads"
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access Bison Stockyard.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def require_login():
    # Auth disabled during development — re-enable before manager rollout
    pass

with app.app_context():
    db.create_all()
    seed_mock_data(app)


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_selected_restaurant():
    # Owners can switch between restaurants via cookie/session
    # Managers are locked to their assigned restaurant
    if current_user.is_authenticated and not current_user.is_owner:
        if current_user.restaurant_id:
            r = Restaurant.query.get(current_user.restaurant_id)
            if r:
                return r
    restaurant_id = request.cookies.get("restaurant_id") or session.get("restaurant_id")
    if restaurant_id:
        r = Restaurant.query.get(int(restaurant_id))
        if r:
            return r
    return Restaurant.query.first()


def _save_invoice_to_db(invoice_data, restaurant_id):
    vendor_name = invoice_data.get("vendor_name", "")
    vendor = Vendor.query.filter_by(name=vendor_name).first() if vendor_name else None

    inv_date = invoice_data.get("invoice_date", "")
    if isinstance(inv_date, str) and inv_date:
        try:
            inv_date = datetime.strptime(inv_date, "%Y-%m-%d").date()
        except ValueError:
            inv_date = datetime.now(CENTRAL_TZ).date()
    elif not inv_date:
        inv_date = datetime.now(CENTRAL_TZ).date()

    invoice = Invoice(
        restaurant_id=restaurant_id,
        vendor_id=vendor.id if vendor else None,
        invoice_number=invoice_data.get("invoice_number", f"IMP-{uuid.uuid4().hex[:8].upper()}"),
        invoice_date=inv_date,
        due_date=inv_date + timedelta(days=30),
        total_amount=float(invoice_data.get("total_amount", 0)),
        status="pending",
        source=invoice_data.get("source", "manual"),
        imported_at=datetime.utcnow(),
    )
    db.session.add(invoice)
    db.session.flush()

    for line in invoice_data.get("lines", []):
        inv_line = InvoiceLine(
            invoice_id=invoice.id,
            description=line.get("description", ""),
            vendor_sku=line.get("vendor_sku", ""),
            quantity=float(line.get("quantity", 0)),
            unit=line.get("unit", ""),
            unit_cost=float(line.get("unit_cost", 0)),
            line_total=float(line.get("line_total", 0)),
        )
        db.session.add(inv_line)
        db.session.flush()

        # Match line item to inventory via matching engine
        source = invoice_data.get("source", "manual")
        sku = line.get("vendor_sku", "")
        desc = line.get("description", "")
        line_cost = float(line.get("unit_cost", 0))

        result = match_item(
            restaurant_id=restaurant_id,
            sku=sku,
            name=desc,
            source=source,
            unit=line.get("unit", ""),
            cost=line_cost,
            invoice_id=invoice.id,
        )

        if result["item"]:
            inv_line.inventory_item_id = result["item"].id
            if line_cost > 0:
                update_price(result["item"], line_cost, source, invoice.id)

    db.session.commit()
    return invoice


@app.context_processor
def inject_restaurants():
    restaurants = Restaurant.query.all()
    selected = _get_selected_restaurant()
    unmatched_count = UnmatchedItem.query.filter_by(
        restaurant_id=selected.id, status="pending"
    ).count() if selected else 0

    alert_critical = alert_warning = alert_info = 0
    if selected:
        alert_critical = Alert.query.filter_by(
            restaurant_id=selected.id, resolved=False, severity="critical"
        ).count()
        alert_warning = Alert.query.filter_by(
            restaurant_id=selected.id, resolved=False, severity="warning"
        ).count()
        alert_info = Alert.query.filter_by(
            restaurant_id=selected.id, resolved=False, severity="info"
        ).count()
    return dict(
        restaurants=restaurants,
        selected_restaurant=selected,
        unmatched_count=unmatched_count,
        alert_critical=alert_critical,
        alert_warning=alert_warning,
        alert_info=alert_info,
        alert_total=alert_critical + alert_warning + alert_info,
    )


def _resolve_range(range_name, custom_start=None, custom_end=None):
    """Convert a range name to (start, end, prior_start, prior_end) datetime
    tuples in Central Time. The 'prior' window mirrors the same length
    immediately before the main window so today vs yesterday, this_week vs
    last_week, etc all work uniformly.
    """
    now = datetime.now(CENTRAL_TZ)
    today_midnight = CENTRAL_TZ.localize(datetime(now.year, now.month, now.day))

    if range_name == "today":
        start = today_midnight
        end = now
    elif range_name == "yesterday":
        start = today_midnight - timedelta(days=1)
        end = today_midnight
    elif range_name == "week":  # this week (last 7 days, rolling)
        start = today_midnight - timedelta(days=6)
        end = now
    elif range_name == "last_week":
        start = today_midnight - timedelta(days=13)
        end = today_midnight - timedelta(days=6)
    elif range_name == "month":  # this month, 1st to now
        start = CENTRAL_TZ.localize(datetime(now.year, now.month, 1))
        end = now
    elif range_name == "custom" and custom_start and custom_end:
        try:
            start = CENTRAL_TZ.localize(datetime.strptime(custom_start, "%Y-%m-%d"))
            end = CENTRAL_TZ.localize(datetime.strptime(custom_end, "%Y-%m-%d")) + timedelta(days=1)
        except ValueError:
            start = today_midnight
            end = now
    else:
        # default fallback: today
        start = today_midnight
        end = now

    span = end - start
    prior_end = start
    prior_start = start - span
    return start, end, prior_start, prior_end


def _fetch_orders_for_range(r, start_utc, end_utc):
    """Best-effort wrapper around fetch_orders. Returns ([], False) on failure."""
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S.000-0000")
    try:
        return fetch_orders(r, fmt(start_utc), fmt(end_utc)), True
    except Exception as e:
        print(f"[sales] fetch_orders failed for {r.name}: {e}")
        return [], False


def _build_sales_summary(r, range_name, custom_start=None, custom_end=None, compare=False):
    """Returns the full sales-summary payload used by /api/sales-summary."""
    start_ct, end_ct, prior_start_ct, prior_end_ct = _resolve_range(
        range_name, custom_start, custom_end
    )
    start_utc = start_ct.astimezone(pytz.UTC)
    end_utc = end_ct.astimezone(pytz.UTC)

    payload = {
        "range": range_name,
        "start": start_ct.isoformat(),
        "end": end_ct.isoformat(),
        "sales": None,
        "net_sales": None,
        "discount_total": None,
        "void_total": None,
        "prior_sales": None,
        "delta_amount": None,
        "delta_pct": None,
        "labor_pct": None,
        "labor_pct_suspicious": False,
        "food_cost_pct": None,
        "check_count": None,
        "avg_check": None,
        "daily": [],
    }

    # Food cost % from active recipes — DB only
    avg_fc = db.session.query(db.func.avg(Recipe.food_cost_pct)).filter(
        Recipe.restaurant_id == r.id,
        Recipe.status == "active",
        Recipe.food_cost_pct > 0,
    ).scalar()
    if avg_fc:
        payload["food_cost_pct"] = round(float(avg_fc), 1)

    if not r.toast_client_id or not r.toast_location_id:
        return payload

    orders, ok = _fetch_orders_for_range(r, start_utc, end_utc)
    if not ok:
        return payload

    sales_total = sum(o.get("total", 0) for o in orders)
    # net_sales (post-discount, pre-tax, pre-tip) is the industry-correct
    # denominator for cost percentages. `sales` stays as customer-paid total
    # so the headline number matches what operators see on Toast.
    net_sales_total = sum(o.get("net_sales", 0) for o in orders)
    discount_total = sum(o.get("discount_total", 0) for o in orders)
    void_total = sum(o.get("void_total", 0) for o in orders)
    payload["sales"] = round(sales_total, 2)
    payload["net_sales"] = round(net_sales_total, 2)
    payload["discount_total"] = round(discount_total, 2)
    payload["void_total"] = round(void_total, 2)
    payload["check_count"] = len(orders)
    if orders:
        payload["avg_check"] = round(sales_total / len(orders), 2)

    # Daily breakdown for trend chart (always computes 14 days for context)
    chart_start_ct = end_ct - timedelta(days=13)
    chart_start_utc = chart_start_ct.astimezone(pytz.UTC)
    chart_orders, _ = _fetch_orders_for_range(r, chart_start_utc, end_utc)
    daily_map = {}
    for o in chart_orders:
        opened = o.get("opened_date") or ""
        try:
            dt_utc = datetime.strptime(opened, "%Y-%m-%dT%H:%M:%S.%f%z")
            dt_ct = dt_utc.astimezone(CENTRAL_TZ)
            day_key = dt_ct.strftime("%Y-%m-%d")
        except ValueError:
            continue
        daily_map.setdefault(day_key, 0.0)
        daily_map[day_key] += o.get("total", 0)
    for i in range(14):
        d = (chart_start_ct + timedelta(days=i)).strftime("%Y-%m-%d")
        payload["daily"].append({"date": d, "sales": round(daily_map.get(d, 0.0), 2)})

    # Labor cost
    try:
        ts = fetch_timesheets(
            r,
            start_utc.strftime("%Y-%m-%dT%H:%M:%S.000-0000"),
            end_utc.strftime("%Y-%m-%dT%H:%M:%S.000-0000"),
        )
        # Effective rate per employee: manual override (set by managers via the
        # employees page, e.g. for staff whose Toast wage is missing) wins over
        # the Toast-synced pay_rate. The < $100/hr guard still applies — it
        # catches legacy rows that stored an annual figure in pay_rate.
        emp_wage = {}
        for e in Employee.query.filter_by(restaurant_id=r.id).all():
            rate = e.manual_pay_rate if e.manual_pay_rate is not None else (e.pay_rate or 0)
            if 0 < rate < 100:
                emp_wage[e.toast_employee_id] = rate
        labor_cost = sum((t.get("hours") or 0) * emp_wage.get(t.get("employee_guid"), 0) for t in ts)
        # Denominator: prefer net_sales (post-discount, pre-tax, pre-tip).
        # Falls back to sales_total if for some reason net_sales is 0 — mostly
        # a defense against old cached payloads or non-Toast data sources.
        denom = net_sales_total if net_sales_total > 0 else sales_total
        if denom > 0:
            raw_pct = (labor_cost / denom) * 100
            payload["labor_pct_suspicious"] = raw_pct > 80
            payload["labor_pct"] = round(min(raw_pct, 100.0), 1)
    except Exception as e:
        print(f"[sales] timesheets failed for {r.name}: {e}")

    # Compare to prior period
    if compare:
        prior_start_utc = prior_start_ct.astimezone(pytz.UTC)
        prior_end_utc = prior_end_ct.astimezone(pytz.UTC)
        prior_orders, prior_ok = _fetch_orders_for_range(r, prior_start_utc, prior_end_utc)
        if prior_ok:
            prior_total = round(sum(o.get("total", 0) for o in prior_orders), 2)
            payload["prior_sales"] = prior_total
            payload["delta_amount"] = round(sales_total - prior_total, 2)
            if prior_total > 0:
                payload["delta_pct"] = round(((sales_total - prior_total) / prior_total) * 100, 1)

    return payload


def _toast_sales_summary(r):
    """Pull today + this week's sales from Toast and compute labor/food cost %.

    Returns a dict of {today_sales, week_sales, labor_pct, labor_pct_suspicious,
    food_cost_pct}. Labor cost only counts hourly employees with rates under
    $100/hr to defend against salaried employees whose annual figure is stored
    in pay_rate. labor_pct is capped at 100; labor_pct_suspicious is True when
    the raw computed value exceeds 80% (likely a data issue).
    Best-effort: any failure returns Nones so the dashboard still renders.
    """
    summary = {
        "today_sales": None,
        "week_sales": None,
        "labor_pct": None,
        "labor_pct_suspicious": False,
        "food_cost_pct": None,
    }

    # Average food cost % from active recipes — DB only, always cheap
    avg_fc = db.session.query(db.func.avg(Recipe.food_cost_pct)).filter(
        Recipe.restaurant_id == r.id,
        Recipe.status == "active",
        Recipe.food_cost_pct > 0,
    ).scalar()
    if avg_fc:
        summary["food_cost_pct"] = round(float(avg_fc), 1)

    if not r.toast_client_id or not r.toast_location_id:
        return summary

    try:
        # All "today" math is local to US/Central — restaurants live in that
        # timezone, not UTC. We compute today's window in Central, then convert
        # the bounds to UTC for the Toast API.
        now_central = datetime.now(CENTRAL_TZ)
        today_start_central = CENTRAL_TZ.localize(
            datetime(now_central.year, now_central.month, now_central.day)
        )
        week_start_central = today_start_central - timedelta(days=7)
        end_central = now_central

        today_start_utc = today_start_central.astimezone(pytz.UTC)
        week_start_utc = week_start_central.astimezone(pytz.UTC)
        end_utc = end_central.astimezone(pytz.UTC)

        def fmt(d_utc):
            # Toast expects ISO-8601 with millisecond precision and a UTC offset
            return d_utc.strftime("%Y-%m-%dT%H:%M:%S.000-0000")

        print(f"[dashboard] {r.name} fetching orders {fmt(week_start_utc)} -> {fmt(end_utc)} (today starts at {fmt(today_start_utc)})")

        week_orders = fetch_orders(r, fmt(week_start_utc), fmt(end_utc))
        today_total = 0.0
        week_total = 0.0
        week_net = 0.0
        for o in week_orders:
            opened = o.get("opened_date") or ""
            try:
                opened_dt = datetime.strptime(opened, "%Y-%m-%dT%H:%M:%S.%f%z")
            except ValueError:
                opened_dt = None
            week_total += o.get("total", 0)
            week_net += o.get("net_sales", 0)
            if opened_dt and opened_dt >= today_start_utc:
                today_total += o.get("total", 0)

        summary["today_sales"] = round(today_total, 2)
        summary["week_sales"] = round(week_total, 2)

        # Labor cost = sum(hours * wage) for last 7 days / net_sales.
        # Both hourly and salary employees count — for salaried staff, fetch_employees
        # has already converted the annual figure to an hourly equivalent (annual / 2080).
        # Manager-set manual_pay_rate wins over the Toast-synced pay_rate.
        # The < $100/hr guard catches any remaining bad data (e.g. legacy rows where
        # an annual was stored without conversion).
        ts = fetch_timesheets(r, fmt(week_start_utc), fmt(end_utc))
        emp_wage = {}
        for e in Employee.query.filter_by(restaurant_id=r.id).all():
            rate = e.manual_pay_rate if e.manual_pay_rate is not None else (e.pay_rate or 0)
            if 0 < rate < 100:
                emp_wage[e.toast_employee_id] = rate
        labor_cost = sum((t.get("hours") or 0) * emp_wage.get(t.get("employee_guid"), 0) for t in ts)
        denom = week_net if week_net > 0 else week_total
        if denom > 0:
            raw_pct = (labor_cost / denom) * 100
            summary["labor_pct_suspicious"] = raw_pct > 80
            summary["labor_pct"] = round(min(raw_pct, 100.0), 1)
    except Exception as e:
        print(f"[dashboard] toast sales fetch failed for {r.name}: {e}")

    return summary


def _price_tracker_top(restaurant_id, limit=10):
    """Top N inventory items with biggest recent price moves, pulled from
    price_history. Returns list of dicts with item, current, previous, change_pct,
    delta_amount."""
    rows = (
        db.session.query(PriceHistory, InventoryItem)
        .join(InventoryItem, PriceHistory.inventory_item_id == InventoryItem.id)
        .filter(InventoryItem.restaurant_id == restaurant_id)
        .order_by(PriceHistory.recorded_at.desc())
        .limit(500)
        .all()
    )
    # Keep only the most-recent change per item
    seen = {}
    for ph, item in rows:
        if item.id in seen:
            continue
        seen[item.id] = (ph, item)
    deduped = list(seen.values())
    # Sort by absolute % change, biggest moves first
    deduped.sort(key=lambda x: abs(x[0].change_percent or 0), reverse=True)
    out = []
    for ph, item in deduped[:limit]:
        out.append({
            "name": item.name,
            "unit": item.unit,
            "current": ph.new_cost,
            "previous": ph.old_cost,
            "change_pct": ph.change_percent,
            "delta_amount": (ph.new_cost or 0) - (ph.old_cost or 0),
            "recorded_at": ph.recorded_at,
        })
    return out


@app.route("/")
def dashboard():
    r = _get_selected_restaurant()
    if not r:
        return render_template(
            "dashboard.html",
            stats={}, recent_invoices=[], pending_invoices=[],
            top_alerts=[], price_changes=[], selected_range="today", compare=False,
        )

    now = datetime.now(CENTRAL_TZ).date()
    selected_range = request.args.get("range", "today")
    custom_start = request.args.get("start_date")
    custom_end = request.args.get("end_date")
    compare = request.args.get("compare") == "1"

    pending_count = Invoice.query.filter_by(restaurant_id=r.id, status="pending").count()
    overdue_count = Invoice.query.filter(
        Invoice.restaurant_id == r.id,
        Invoice.status.in_(["pending", "approved"]),
        Invoice.due_date < now,
    ).count()
    low_stock_count = InventoryItem.query.filter(
        InventoryItem.restaurant_id == r.id,
        InventoryItem.current_stock < InventoryItem.par_level,
    ).count()
    thirty_days_ago = now - timedelta(days=30)
    spend_result = db.session.query(db.func.sum(Invoice.total_amount)).filter(
        Invoice.restaurant_id == r.id,
        Invoice.invoice_date >= thirty_days_ago,
    ).scalar() or 0

    recent_invoices = Invoice.query.filter_by(restaurant_id=r.id).order_by(Invoice.imported_at.desc()).limit(5).all()
    pending_invoices = (
        Invoice.query.filter_by(restaurant_id=r.id, status="pending")
        .order_by(Invoice.due_date.asc())
        .limit(5)
        .all()
    )

    # Top 5 unresolved alerts, severity-prioritized
    top_alerts = (
        Alert.query.filter_by(restaurant_id=r.id, resolved=False)
        .order_by(
            db.case({"critical": 0, "warning": 1, "info": 2}, value=Alert.severity, else_=3),
            Alert.created_at.desc(),
        )
        .limit(5)
        .all()
    )

    price_changes = _price_tracker_top(r.id, limit=10)

    # Food cost % is cheap (DB only) — render server-side so the card doesn't
    # flash. All Toast-dependent metrics start as None and JS populates them.
    avg_fc = db.session.query(db.func.avg(Recipe.food_cost_pct)).filter(
        Recipe.restaurant_id == r.id,
        Recipe.status == "active",
        Recipe.food_cost_pct > 0,
    ).scalar()

    stats = {
        "pending_count": pending_count,
        "overdue_count": overdue_count,
        "low_stock_count": low_stock_count,
        "thirty_day_spend": round(spend_result, 2),
        "food_cost_pct": round(float(avg_fc), 1) if avg_fc else None,
    }
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_invoices=recent_invoices,
        pending_invoices=pending_invoices,
        top_alerts=top_alerts,
        price_changes=price_changes,
        selected_range=selected_range,
        custom_start=custom_start or "",
        custom_end=custom_end or "",
        compare=compare,
    )


@app.route("/api/sales-summary")
def api_sales_summary():
    rid = int(request.args.get("restaurant_id", 0))
    range_name = request.args.get("range", "today")
    custom_start = request.args.get("start_date")
    custom_end = request.args.get("end_date")
    compare = request.args.get("compare") == "1"
    r = db.session.get(Restaurant, rid) if rid else _get_selected_restaurant()
    if not r:
        return jsonify({"error": "no restaurant"}), 400
    return jsonify(_build_sales_summary(r, range_name, custom_start, custom_end, compare))


# ---------------------------------------------------------------------------
# Product Mix (PMIX) — Toast-driven menu item sales analytics
# ---------------------------------------------------------------------------

def _pmix_resolve_window(range_name, custom_start=None, custom_end=None):
    """Map a range name to (start_dt, end_dt) in Central time, ISO formatted."""
    today = datetime.now(CENTRAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_name == "yesterday":
        start = today - timedelta(days=1)
        end = today
    elif range_name == "week":
        start = today - timedelta(days=today.weekday())
        end = today + timedelta(days=1)
    elif range_name == "last_week":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
    elif range_name == "month":
        start = today.replace(day=1)
        end = today + timedelta(days=1)
    elif range_name == "custom" and custom_start and custom_end:
        start = CENTRAL_TZ.localize(datetime.strptime(custom_start, "%Y-%m-%d"))
        end = CENTRAL_TZ.localize(datetime.strptime(custom_end, "%Y-%m-%d")) + timedelta(days=1)
    else:  # today
        start = today
        end = today + timedelta(days=1)
    return start, end


def _pmix_persist(restaurant, items, sale_date):
    """Replace any existing PMIX rows for (restaurant, sale_date) with `items`.

    `sale_date` is a date — we store it as midnight datetime so the column can
    stay DateTime. We delete + insert because Toast may revise historic sales
    and the cleanest behavior is "the snapshot for that day is whatever Toast
    says now".
    """
    if not items:
        return
    midnight = datetime.combine(sale_date, datetime.min.time())
    MenuItemSale.query.filter_by(
        restaurant_id=restaurant.id, sale_date=midnight
    ).delete()
    # Build a quick GUID -> recipe_id index so each PMIX row links straight to
    # the matching recipe via its toast_guid (or toast_recipe_id as a fallback).
    recipe_index = {}
    for r in Recipe.query.filter_by(restaurant_id=restaurant.id).all():
        if r.toast_guid:
            recipe_index[r.toast_guid] = r.id
        if r.toast_recipe_id:
            recipe_index.setdefault(r.toast_recipe_id, r.id)
    for it in items:
        guid = it.get("toast_item_guid")
        db.session.add(MenuItemSale(
            restaurant_id=restaurant.id,
            sale_date=midnight,
            toast_item_guid=guid,
            item_name=it.get("item_name"),
            category=it.get("category"),
            quantity=int(it.get("quantity") or 0),
            unit_price=float(it.get("unit_price") or 0),
            total_revenue=float(it.get("total_revenue") or 0),
            recipe_id=recipe_index.get(guid),
        ))
    db.session.commit()


def _pmix_with_recipes(restaurant, items):
    """Decorate PMIX rows with linked recipe cost data."""
    if not items:
        return []
    recipe_by_guid = {}
    for r in Recipe.query.filter_by(restaurant_id=restaurant.id).all():
        if r.toast_guid:
            recipe_by_guid[r.toast_guid] = r
        if r.toast_recipe_id:
            recipe_by_guid.setdefault(r.toast_recipe_id, r)
    out = []
    for it in items:
        guid = it.get("toast_item_guid")
        rec = recipe_by_guid.get(guid)
        recipe_id = rec.id if rec else None
        cost_pct = round(rec.cost_percent, 1) if rec and rec.menu_price else None
        food_cost = round(rec.total_cost, 2) if rec else None
        margin = None
        if rec and rec.menu_price:
            margin = round((rec.menu_price - rec.total_cost) * (it.get("quantity") or 0), 2)
        out.append({
            **it,
            "recipe_id": recipe_id,
            "recipe_name": rec.name if rec else None,
            "food_cost": food_cost,
            "cost_pct": cost_pct,
            "margin": margin,
        })
    return out


def _pmix_for_restaurant(restaurant, range_name, custom_start, custom_end):
    """Try Toast first; on failure, fall back to whatever's already cached in
    `menu_item_sales` for the window."""
    start_dt, end_dt = _pmix_resolve_window(range_name, custom_start, custom_end)
    items = []
    used_cache = False
    error = None
    try:
        items = fetch_pmix(restaurant, start_dt, end_dt)
        if items:
            # Persist as a single snapshot keyed on the start day
            _pmix_persist(restaurant, items, start_dt.date())
    except Exception as e:
        error = str(e)
        print(f"[pmix] Toast fetch failed for restaurant {restaurant.id}: {e}")
        # Fall back to whatever we already have stored for the window
        rows = (
            MenuItemSale.query.filter(
                MenuItemSale.restaurant_id == restaurant.id,
                MenuItemSale.sale_date >= start_dt.replace(tzinfo=None),
                MenuItemSale.sale_date < end_dt.replace(tzinfo=None),
            )
            .order_by(MenuItemSale.quantity.desc())
            .all()
        )
        # Re-aggregate the cached rows in case the window spans multiple days
        bucket = {}
        for r in rows:
            key = (r.toast_item_guid, r.item_name)
            cur = bucket.get(key)
            if cur is None:
                bucket[key] = {
                    "toast_item_guid": r.toast_item_guid,
                    "item_name": r.item_name,
                    "category": r.category,
                    "quantity": r.quantity or 0,
                    "total_revenue": r.total_revenue or 0.0,
                }
            else:
                cur["quantity"] += r.quantity or 0
                cur["total_revenue"] += r.total_revenue or 0.0
        items = sorted(bucket.values(), key=lambda x: x["quantity"], reverse=True)
        for it in items:
            qty = it["quantity"] or 0
            it["unit_price"] = round(it["total_revenue"] / qty, 2) if qty else 0.0
            it["total_revenue"] = round(it["total_revenue"], 2)
        used_cache = True
    return _pmix_with_recipes(restaurant, items), {
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "used_cache": used_cache,
        "error": error,
    }


@app.route("/api/pmix")
def api_pmix():
    rid = int(request.args.get("restaurant_id", 0) or 0)
    range_name = request.args.get("range", "today")
    custom_start = request.args.get("start_date")
    custom_end = request.args.get("end_date")
    r = db.session.get(Restaurant, rid) if rid else _get_selected_restaurant()
    if not r:
        return jsonify({"error": "no restaurant"}), 400
    items, meta = _pmix_for_restaurant(r, range_name, custom_start, custom_end)
    total_qty = sum(it["quantity"] or 0 for it in items)
    total_rev = round(sum(it["total_revenue"] or 0 for it in items), 2)
    return jsonify({
        "items": items,
        "total_qty": total_qty,
        "total_revenue": total_rev,
        "top_item": items[0] if items else None,
        **meta,
    })


@app.route("/pmix")
def pmix():
    r = _get_selected_restaurant()
    range_name = request.args.get("range", "today")
    custom_start = request.args.get("start_date")
    custom_end = request.args.get("end_date")
    items = []
    meta = {}
    if r:
        items, meta = _pmix_for_restaurant(r, range_name, custom_start, custom_end)
    categories = sorted({(it.get("category") or "Uncategorized") for it in items})
    total_qty = sum(it["quantity"] or 0 for it in items)
    total_rev = round(sum(it["total_revenue"] or 0 for it in items), 2)
    top_item = items[0] if items else None
    return render_template(
        "pmix.html",
        items=items,
        categories=categories,
        selected_range=range_name,
        custom_start=custom_start or "",
        custom_end=custom_end or "",
        total_qty=total_qty,
        total_revenue=total_rev,
        top_item=top_item,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Bison AI Assistant — chat + proactive co-pilot backed by Anthropic Claude
# ---------------------------------------------------------------------------

import json as _json

ASSISTANT_SYSTEM_TEMPLATE = (
    "You are the Bison Stockyard AI guardian. You are watchful, direct, and helpful. "
    "You speak like a trusted manager who knows the operation inside out. You catch "
    "mistakes before they become problems.\n\n"
    "Current context — Restaurant: {restaurant_name}. Time: {date}. "
    "Sales today: ${sales_today}. Labor: {labor_pct}%. Food cost: {food_cost_pct}%. "
    "Open alerts: {alert_count}. Low stock items: {low_stock_count}. "
    "Pending invoices: {pending_invoices}.\n"
    "Top sellers today: {top_sellers}.\n\n"
    "Common UOM rules: spirits measured in oz, beer in each/case, proteins in oz or lb, "
    "produce in lb or each, dairy in oz or lb. Flag anything that doesn't match expected "
    "UOM for its category.\n\n"
    "When reviewing user input, check for: unrealistic quantities (>32oz spirits in one "
    "drink), wrong UOM for category, prices that are 10x higher or lower than similar "
    "items, duplicate item names.\n\n"
    "You have tools to look up recipes, items, sales, and alerts, and to take actions "
    "like approving invoices, adjusting inventory, or creating draft recipes. Use the "
    "lookup tools whenever a question depends on live data — don't guess. For any "
    "action that mutates data, the platform will surface a confirmation card to the "
    "user before executing. Be concise and action-oriented."
)

# Tool catalog. Read-only tools execute server-side and feed results back into
# the conversation. Mutating tools short-circuit and return a pending_action so
# the frontend can render a confirmation card.
ASSISTANT_TOOLS = [
    {
        "name": "look_up_recipe",
        "description": "Look up a recipe by name and return its costs, menu price, and ingredients.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "look_up_item",
        "description": "Look up an inventory item by name and return its stock, par, and last cost.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "look_up_sales",
        "description": "Get a sales summary for a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date_range": {
                    "type": "string",
                    "enum": ["today", "yesterday", "week", "last_week", "month"],
                }
            },
            "required": ["date_range"],
        },
    },
    {
        "name": "get_alerts",
        "description": "Return all currently unresolved alerts for the restaurant.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "approve_invoice",
        "description": "Approve a pending invoice. Mutates state — requires confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "integer"}},
            "required": ["invoice_id"],
        },
    },
    {
        "name": "adjust_inventory",
        "description": "Set or adjust an inventory item's current stock. Mutates state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer"},
                "quantity": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["item_id", "quantity"],
        },
    },
    {
        "name": "create_draft_recipe",
        "description": "Create a draft recipe with the given name, ingredients, and menu price. Mutates state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "menu_price": {"type": "number"},
                "ingredients": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string"},
                            "unit_cost": {"type": "number"},
                        },
                        "required": ["name"],
                    },
                },
            },
            "required": ["name"],
        },
    },
]

MUTATING_TOOLS = {"approve_invoice", "adjust_inventory", "create_draft_recipe"}


def _assistant_gather_context(restaurant):
    """Pull live numbers used in the system prompt."""
    rid = restaurant.id if restaurant else None
    now_central = datetime.now(CENTRAL_TZ)
    date_str = now_central.strftime("%A, %B %d, %Y %I:%M %p %Z")

    alert_count = 0
    low_stock_count = 0
    pending_invoices = 0
    sales_today = 0.0
    labor_pct = "—"
    food_cost_pct = "—"
    top_sellers = "(no data)"

    if restaurant:
        alert_count = Alert.query.filter_by(restaurant_id=rid, resolved=False).count()
        low_stock_count = InventoryItem.query.filter(
            InventoryItem.restaurant_id == rid,
            InventoryItem.par_level > 0,
            InventoryItem.current_stock < InventoryItem.par_level,
        ).count()
        pending_invoices = Invoice.query.filter_by(
            restaurant_id=rid, status="pending"
        ).count()
        try:
            summary = _build_sales_summary(restaurant, "today", compare=False)
            sales_today = summary.get("sales") or 0
            if summary.get("labor_pct") is not None:
                labor_pct = summary["labor_pct"]
            if summary.get("food_cost_pct") is not None:
                food_cost_pct = summary["food_cost_pct"]
        except Exception as e:
            print(f"[assistant] sales summary failed: {e}")

        # Top 5 sellers today, pulled from cached PMIX rows
        try:
            today_midnight = datetime.combine(
                datetime.now(CENTRAL_TZ).date(), datetime.min.time()
            )
            top_rows = (
                MenuItemSale.query.filter_by(
                    restaurant_id=restaurant.id, sale_date=today_midnight
                )
                .order_by(MenuItemSale.quantity.desc())
                .limit(5)
                .all()
            )
            if top_rows:
                top_sellers = ", ".join(
                    f"{r.item_name} ({r.quantity})" for r in top_rows
                )
        except Exception as e:
            print(f"[assistant] top sellers lookup failed: {e}")

    return {
        "restaurant_name": restaurant.name if restaurant else "(no restaurant selected)",
        "date": date_str,
        "sales_today": f"{sales_today:,.0f}",
        "labor_pct": labor_pct,
        "food_cost_pct": food_cost_pct,
        "alert_count": alert_count,
        "low_stock_count": low_stock_count,
        "pending_invoices": pending_invoices,
        "top_sellers": top_sellers,
    }


# ---- Tool implementations -------------------------------------------------

def _tool_look_up_recipe(restaurant, args):
    name = (args.get("name") or "").strip()
    if not restaurant or not name:
        return {"error": "no restaurant or name"}
    q = Recipe.query.filter_by(restaurant_id=restaurant.id)
    hit = q.filter(Recipe.name.ilike(f"%{name}%")).first()
    if not hit:
        return {"found": False, "name": name}
    return {
        "found": True,
        "id": hit.id,
        "name": hit.name,
        "category": hit.category,
        "menu_price": hit.menu_price or 0,
        "food_cost": round(hit.total_cost, 2),
        "cost_percent": round(hit.cost_percent, 1),
        "margin": round(hit.margin, 2),
        "ingredients": [
            {
                "name": ing.name or (ing.inventory_item.name if ing.inventory_item else "?"),
                "quantity": ing.quantity,
                "unit": ing.unit,
                "unit_cost": round(ing.effective_unit_cost, 4),
                "line_cost": round(ing.cost, 2),
            }
            for ing in hit.ingredients
        ],
    }


def _tool_look_up_item(restaurant, args):
    name = (args.get("name") or "").strip()
    if not restaurant or not name:
        return {"error": "no restaurant or name"}
    hit = (
        InventoryItem.query.filter_by(restaurant_id=restaurant.id)
        .filter(InventoryItem.name.ilike(f"%{name}%"))
        .first()
    )
    if not hit:
        return {"found": False, "name": name}
    return {
        "found": True,
        "id": hit.id,
        "name": hit.name,
        "category": hit.category,
        "unit": hit.unit,
        "current_stock": hit.current_stock or 0,
        "par_level": hit.par_level or 0,
        "below_par": (hit.par_level or 0) > 0
        and (hit.current_stock or 0) < (hit.par_level or 0),
        "last_cost": hit.last_cost or 0,
        "vendor": hit.vendor.name if hit.vendor else None,
    }


def _tool_look_up_sales(restaurant, args):
    if not restaurant:
        return {"error": "no restaurant"}
    range_name = args.get("date_range") or "today"
    try:
        return _build_sales_summary(restaurant, range_name)
    except Exception as e:
        return {"error": str(e)}


def _tool_get_alerts(restaurant, args):
    if not restaurant:
        return {"alerts": []}
    rows = (
        Alert.query.filter_by(restaurant_id=restaurant.id, resolved=False)
        .order_by(Alert.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        "alerts": [
            {
                "id": a.id,
                "type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


READ_TOOL_HANDLERS = {
    "look_up_recipe": _tool_look_up_recipe,
    "look_up_item": _tool_look_up_item,
    "look_up_sales": _tool_look_up_sales,
    "get_alerts": _tool_get_alerts,
}


def _describe_pending_action(tool_name, tool_input, restaurant):
    """Human-readable description for the confirmation card."""
    if tool_name == "approve_invoice":
        inv_id = tool_input.get("invoice_id")
        inv = db.session.get(Invoice, inv_id) if inv_id else None
        if inv:
            vendor = inv.vendor.name if inv.vendor else "vendor"
            return (
                f"Approve invoice #{inv.invoice_number or inv.id} from {vendor} "
                f"for ${inv.total_amount:,.2f}?"
            )
        return f"Approve invoice {inv_id}?"
    if tool_name == "adjust_inventory":
        item = db.session.get(InventoryItem, tool_input.get("item_id"))
        qty = tool_input.get("quantity")
        reason = tool_input.get("reason") or "manual adjust"
        if item:
            return (
                f"Set {item.name} stock to {qty} {item.unit or ''} ({reason})?"
            )
        return f"Adjust item {tool_input.get('item_id')} to {qty}?"
    if tool_name == "create_draft_recipe":
        name = tool_input.get("name")
        price = tool_input.get("menu_price") or 0
        n_ing = len(tool_input.get("ingredients") or [])
        return f"Create draft recipe '{name}' (${price}) with {n_ing} ingredients?"
    return f"Run {tool_name}?"


def _execute_mutating_tool(tool_name, tool_input, restaurant):
    """Actually run a mutating tool after the user confirms."""
    if tool_name == "approve_invoice":
        inv = db.session.get(Invoice, tool_input.get("invoice_id"))
        if not inv:
            return {"ok": False, "message": "Invoice not found."}
        inv.status = "approved"
        inv.approved_at = datetime.utcnow()
        db.session.commit()
        return {"ok": True, "message": f"Invoice #{inv.invoice_number or inv.id} approved."}

    if tool_name == "adjust_inventory":
        item = db.session.get(InventoryItem, tool_input.get("item_id"))
        if not item:
            return {"ok": False, "message": "Item not found."}
        item.current_stock = float(tool_input.get("quantity") or 0)
        db.session.commit()
        return {
            "ok": True,
            "message": f"{item.name} stock set to {item.current_stock} {item.unit or ''}.",
        }

    if tool_name == "create_draft_recipe":
        if not restaurant:
            return {"ok": False, "message": "No restaurant selected."}
        recipe = Recipe(
            restaurant_id=restaurant.id,
            name=tool_input.get("name") or "Untitled",
            menu_price=float(tool_input.get("menu_price") or 0),
            status="draft",
        )
        db.session.add(recipe)
        db.session.flush()
        for ing in tool_input.get("ingredients") or []:
            db.session.add(
                RecipeIngredient(
                    recipe_id=recipe.id,
                    name=ing.get("name"),
                    quantity=float(ing.get("quantity") or 0),
                    unit=ing.get("unit"),
                    unit_cost=float(ing.get("unit_cost") or 0),
                )
            )
        db.session.commit()
        return {"ok": True, "message": f"Draft recipe '{recipe.name}' created (id {recipe.id})."}

    return {"ok": False, "message": f"Unknown tool {tool_name}."}


def _resolve_restaurant_from_payload(payload):
    rid = payload.get("restaurant_id")
    restaurant = None
    if rid:
        try:
            restaurant = db.session.get(Restaurant, int(rid))
        except (TypeError, ValueError):
            restaurant = None
    return restaurant or _get_selected_restaurant()


def _normalize_history(payload):
    """Accept either {messages:[...]} or {message:'...'} for back-compat."""
    if isinstance(payload.get("messages"), list) and payload["messages"]:
        # Strip to {role, content} text-only entries
        out = []
        for m in payload["messages"]:
            role = m.get("role")
            content = m.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                out.append({"role": role, "content": content})
        return out
    msg = (payload.get("message") or "").strip()
    if msg:
        return [{"role": "user", "content": msg}]
    return []


@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    payload = request.get_json(silent=True) or {}
    history = _normalize_history(payload)
    if not history:
        return jsonify({"error": "message required"}), 400

    restaurant = _resolve_restaurant_from_payload(payload)
    ctx = _assistant_gather_context(restaurant)
    system_prompt = ASSISTANT_SYSTEM_TEMPLATE.format(**ctx)

    # Chip-specific guidance: if the latest user turn matches a known suggestion
    # chip, append a focused instruction so the response is tailored to it.
    last_user = next(
        (m.get("content", "") for m in reversed(history) if m.get("role") == "user"),
        "",
    )
    if isinstance(last_user, str):
        chip_key = last_user.strip().lower().rstrip("?.!")
        chip_instructions = {
            "morning briefing": (
                "The user clicked the 'Morning Briefing' chip. Produce a concise "
                "morning briefing covering: yesterday's total sales and how it "
                "compared to the prior week, who is on the schedule today, any "
                "active alerts that need attention, and weather if it's relevant "
                "to the operation. Keep it under ~80 words and lead with the "
                "single most important number."
            ),
            "end of day summary": (
                "The user clicked the 'End of Day Summary' chip. Summarize: "
                "total sales for today, labor as a % of sales, the top 3 selling "
                "items, and any issues to flag for tomorrow's open. Be terse — "
                "bullet style, under ~80 words."
            ),
            "who's clocked in": (
                "The user clicked the \"Who's Clocked In?\" chip. List every "
                "employee currently on the clock, their role, and the hours "
                "they've worked so far today. If nobody is clocked in, say so "
                "plainly."
            ),
            "what's selling": (
                "The user clicked the \"What's Selling?\" chip. Show the top 5 "
                "items by quantity sold in the last 2 hours. Format as a short "
                "ranked list with item name and quantity."
            ),
        }
        extra = chip_instructions.get(chip_key)
        if extra:
            system_prompt = system_prompt + "\n\n" + extra

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({
            "response": (
                "The AI assistant isn't configured yet — set ANTHROPIC_API_KEY "
                "on the server to enable it."
            )
        })

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)

        # Working messages list — starts with the chat history (text only),
        # then we may append assistant tool_use turns and user tool_result turns
        # as we loop through any read-only tool calls.
        messages = [dict(m) for m in history]

        for _iter in range(6):
            resp = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=1024,
                system=system_prompt,
                tools=ASSISTANT_TOOLS,
                messages=messages,
            )

            if resp.stop_reason == "tool_use":
                # Collect tool_use blocks and any leading text from this turn
                tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                leading_text = "".join(
                    b.text for b in resp.content if getattr(b, "type", None) == "text"
                ).strip()

                # If any mutating tool was called, short-circuit and return a
                # pending_action — frontend will render a confirmation card.
                mutating = next((tu for tu in tool_uses if tu.name in MUTATING_TOOLS), None)
                if mutating:
                    description = _describe_pending_action(
                        mutating.name, dict(mutating.input or {}), restaurant
                    )
                    return jsonify({
                        "response": leading_text or description,
                        "pending_action": {
                            "tool": mutating.name,
                            "input": dict(mutating.input or {}),
                            "description": description,
                        },
                    })

                # All read-only — execute, feed results back, loop
                assistant_blocks = []
                for b in resp.content:
                    btype = getattr(b, "type", None)
                    if btype == "text":
                        assistant_blocks.append({"type": "text", "text": b.text})
                    elif btype == "tool_use":
                        assistant_blocks.append({
                            "type": "tool_use",
                            "id": b.id,
                            "name": b.name,
                            "input": dict(b.input or {}),
                        })
                messages.append({"role": "assistant", "content": assistant_blocks})

                tool_results = []
                for tu in tool_uses:
                    handler = READ_TOOL_HANDLERS.get(tu.name)
                    if handler:
                        try:
                            result = handler(restaurant, dict(tu.input or {}))
                        except Exception as e:
                            result = {"error": str(e)}
                    else:
                        result = {"error": f"unknown tool {tu.name}"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": _json.dumps(result, default=str),
                    })
                messages.append({"role": "user", "content": tool_results})
                continue

            # Final text answer
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            ).strip() or "(no response)"
            return jsonify({"response": text})

        return jsonify({"response": "(stopped after too many tool iterations)"})
    except Exception as e:
        print(f"[assistant] error: {e}")
        return jsonify({"response": f"Sorry — the assistant hit an error: {e}"}), 200


@app.route("/api/assistant/execute", methods=["POST"])
def api_assistant_execute():
    """Run a mutating tool after the user confirmed in the chat panel."""
    payload = request.get_json(silent=True) or {}
    tool = payload.get("tool")
    tool_input = payload.get("input") or {}
    if tool not in MUTATING_TOOLS:
        return jsonify({"ok": False, "message": "unknown or non-mutating tool"}), 400
    restaurant = _resolve_restaurant_from_payload(payload)
    try:
        result = _execute_mutating_tool(tool, tool_input, restaurant)
        return jsonify(result)
    except Exception as e:
        db.session.rollback()
        print(f"[assistant.execute] error: {e}")
        return jsonify({"ok": False, "message": f"Error: {e}"}), 200


# ---- Proactive co-pilot check --------------------------------------------

# In-memory throttle: (restaurant_id, alert_type) -> last shown datetime.
# Resets on process restart, which is fine — better to over-notify after a
# restart than to silently swallow an alert.
_assistant_check_throttle = {}
_THROTTLE_WINDOW = timedelta(hours=1)


def _check_should_throttle(rid, alert_type):
    key = (rid, alert_type)
    last = _assistant_check_throttle.get(key)
    if last and datetime.utcnow() - last < _THROTTLE_WINDOW:
        return True
    _assistant_check_throttle[key] = datetime.utcnow()
    return False


@app.route("/api/assistant/check", methods=["GET", "POST"])
def api_assistant_check():
    rid = request.args.get("restaurant_id") or (
        (request.get_json(silent=True) or {}).get("restaurant_id")
    )
    restaurant = None
    if rid:
        try:
            restaurant = db.session.get(Restaurant, int(rid))
        except (TypeError, ValueError):
            restaurant = None
    if restaurant is None:
        restaurant = _get_selected_restaurant()
    if restaurant is None:
        return jsonify({"has_alert": False})

    rid = restaurant.id

    # Check candidates in priority order (highest first). The first eligible
    # one (not throttled) is returned.
    candidates = []

    # 1. Critical unresolved alerts
    crit = (
        Alert.query.filter_by(restaurant_id=rid, resolved=False, severity="critical")
        .order_by(Alert.created_at.desc())
        .first()
    )
    if crit:
        candidates.append({
            "type": "critical_alert",
            "severity": "critical",
            "message": f"Critical alert: {crit.message}",
            "action": "view_alerts",
        })

    # 2. Toast sync stale (>24h)
    if restaurant.last_toast_sync:
        age = datetime.utcnow() - restaurant.last_toast_sync
        if age > timedelta(hours=24):
            hours = int(age.total_seconds() // 3600)
            candidates.append({
                "type": "toast_sync_stale",
                "severity": "warning",
                "message": f"Toast hasn't synced in {hours} hours — sales numbers may be stale.",
                "action": "sync_toast",
            })

    # 3. Labor % over 35
    try:
        summary = _build_sales_summary(restaurant, "today")
        lp = summary.get("labor_pct")
        if lp is not None and lp > 35:
            candidates.append({
                "type": "labor_high",
                "severity": "warning",
                "message": f"Labor is running at {lp}% today — that's over the 35% threshold.",
                "action": "view_labor",
            })
    except Exception:
        pass

    # 4. Price increases > 10% (look at most recent price history)
    big_jump = (
        db.session.query(PriceHistory, InventoryItem)
        .join(InventoryItem, PriceHistory.inventory_item_id == InventoryItem.id)
        .filter(InventoryItem.restaurant_id == rid)
        .filter(PriceHistory.change_percent != None)
        .filter(PriceHistory.change_percent > 10)
        .order_by(PriceHistory.recorded_at.desc())
        .first()
    )
    if big_jump:
        ph, item = big_jump
        candidates.append({
            "type": "price_jump",
            "severity": "warning",
            "message": (
                f"{item.name} jumped {ph.change_percent:+.1f}% to ${ph.new_cost:.2f} "
                f"on the latest invoice."
            ),
            "action": "view_price_tracker",
        })

    # 5. New pending invoices
    pending = Invoice.query.filter_by(restaurant_id=rid, status="pending").count()
    if pending > 0:
        candidates.append({
            "type": "pending_invoices",
            "severity": "info",
            "message": (
                f"{pending} invoice{'s' if pending != 1 else ''} waiting for approval."
            ),
            "action": "view_invoices",
        })

    # 6. Items below par
    low = InventoryItem.query.filter(
        InventoryItem.restaurant_id == rid,
        InventoryItem.par_level > 0,
        InventoryItem.current_stock < InventoryItem.par_level,
    ).count()
    if low > 0:
        candidates.append({
            "type": "low_stock",
            "severity": "info",
            "message": f"{low} item{'s' if low != 1 else ''} below par — time to reorder.",
            "action": "view_inventory",
        })

    for cand in candidates:
        if not _check_should_throttle(rid, cand["type"]):
            return jsonify({
                "has_alert": True,
                "message": cand["message"],
                "severity": cand["severity"],
                "action": cand["action"],
                "type": cand["type"],
            })

    return jsonify({"has_alert": False})


@app.route("/invoices")
def invoices():
    r = _get_selected_restaurant()
    status_filter = request.args.get("status")
    query = Invoice.query.filter_by(restaurant_id=r.id) if r else Invoice.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    invoice_list = query.order_by(Invoice.invoice_date.desc()).all()
    return render_template("invoices.html", invoices=invoice_list, status_filter=status_filter)


@app.route("/invoices/<int:id>/approve", methods=["POST"])
def approve_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    invoice.status = "approved"
    invoice.approved_at = datetime.utcnow()
    db.session.commit()
    flash(f"Invoice {invoice.invoice_number} approved.", "success")
    return redirect(request.referrer or url_for("invoices"))


@app.route("/invoices/<int:id>/pay", methods=["POST"])
def pay_invoice(id):
    invoice = Invoice.query.get_or_404(id)
    invoice.status = "paid"
    invoice.paid_at = datetime.utcnow()
    db.session.commit()
    flash(f"Invoice {invoice.invoice_number} marked as paid.", "success")
    return redirect(request.referrer or url_for("invoices"))


@app.route("/invoices/import")
@app.route("/invoices/upload")
def import_invoices():
    return render_template("import.html")


@app.route("/invoices/import/gfs", methods=["POST"])
def import_gfs():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("import_invoices"))
    invoices = fetch_gfs_invoices(r.gfs_account)
    for inv_data in invoices:
        inv_data["vendor_name"] = "Gordon Food Service"
        _save_invoice_to_db(inv_data, r.id)
    flash(f"Imported {len(invoices)} invoice(s) from GFS.", "success")
    return redirect(url_for("invoices"))


@app.route("/invoices/import/fintech", methods=["POST"])
def import_fintech():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("import_invoices"))
    invoices = fetch_fintech_invoices()
    for inv_data in invoices:
        _save_invoice_to_db(inv_data, r.id)
    flash(f"Imported {len(invoices)} invoice(s) from Fintech.", "success")
    return redirect(url_for("invoices"))


@app.route("/invoices/import/upload", methods=["POST"])
def import_upload():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("import_invoices"))
    file = request.files.get("invoice_file")
    if not file or file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("import_invoices"))
    if not _allowed_file(file.filename):
        flash("Invalid file type. Allowed: PDF, JPG, PNG, WEBP.", "error")
        return redirect(url_for("import_invoices"))
    filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    try:
        inv_data = extract_invoice_from_image(filepath)
        _save_invoice_to_db(inv_data, r.id)
        flash(f"Invoice extracted and imported from {file.filename}.", "success")
    except Exception as e:
        flash(f"OCR extraction failed: {str(e)}", "error")
    return redirect(url_for("invoices"))


@app.route("/invoices/import/email", methods=["POST"])
def import_email():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("import_invoices"))
    invoices = poll_invoice_email()
    for inv_data in invoices:
        _save_invoice_to_db(inv_data, r.id)
    flash(f"Imported {len(invoices)} invoice(s) from email.", "success")
    return redirect(url_for("invoices"))


@app.route("/invoices/export/qb")
def export_qb_invoices():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("invoices"))
    inv_list = Invoice.query.filter(
        Invoice.restaurant_id == r.id,
        Invoice.status.in_(["pending", "approved"]),
    ).all()
    if not inv_list:
        flash("No invoices to export.", "error")
        return redirect(url_for("invoices"))
    export_data = []
    for inv in inv_list:
        vendor = Vendor.query.get(inv.vendor_id) if inv.vendor_id else None
        lines_data = []
        for line in inv.lines:
            lines_data.append({
                "description": line.description,
                "vendor_sku": line.vendor_sku,
                "quantity": line.quantity,
                "unit": line.unit,
                "unit_cost": line.unit_cost,
                "line_total": line.line_total,
            })
        export_data.append({
            "vendor_name": vendor.name if vendor else "",
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date.strftime("%Y-%m-%d") if inv.invoice_date else "",
            "total_amount": inv.total_amount,
            "source": inv.source or "",
            "lines": lines_data,
        })
        inv.qb_exported = True
    db.session.commit()
    timestamp = datetime.now(CENTRAL_TZ).strftime("%Y%m%d_%H%M%S")
    output_path = f"/root/restaurant-ops/exports/invoices_{r.id}_{timestamp}.iif"
    export_invoices_iif(export_data, output_path)
    return send_file(output_path, as_attachment=True, download_name=f"invoices_{timestamp}.iif")


@app.route("/inventory")
def inventory():
    r = _get_selected_restaurant()
    items = InventoryItem.query.filter_by(restaurant_id=r.id).all() if r else []
    food_categories = {'protein', 'produce', 'dairy', 'bakery', 'supplies'}
    beverage_categories = {'alcohol'}
    food_items = [i for i in items if (i.category or '').lower() in food_categories]
    beverage_items = [i for i in items if (i.category or '').lower() in beverage_categories]
    return render_template("inventory.html", items=items, food_items=food_items, beverage_items=beverage_items)


@app.route("/inventory/<int:id>/update", methods=["POST"])
def update_inventory(id):
    item = InventoryItem.query.get_or_404(id)
    item.current_stock = float(request.form.get("current_stock", item.current_stock))
    item.par_level = float(request.form.get("par_level", item.par_level))
    db.session.commit()
    flash(f"Updated {item.name}.", "success")
    return redirect(url_for("inventory"))


@app.route("/counts")
def counts():
    r = _get_selected_restaurant()
    sessions = CountSession.query.filter_by(restaurant_id=r.id).order_by(CountSession.count_date.desc()).all() if r else []
    return render_template("counts.html", sessions=sessions)


@app.route("/counts/setup")
def count_setup():
    r = _get_selected_restaurant()
    zones = StorageZone.query.filter_by(restaurant_id=r.id).order_by(StorageZone.sort_order).all() if r else []
    items = InventoryItem.query.filter_by(restaurant_id=r.id).all() if r else []
    # Build zone assignments lookup
    assignments = {}
    for item in items:
        za = InventoryItemZone.query.filter_by(inventory_item_id=item.id).first()
        assignments[item.id] = za.storage_zone_id if za else None
    return render_template("count_setup.html", zones=zones, items=items, assignments=assignments)


@app.route("/counts/setup/add-zone", methods=["POST"])
def add_zone():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("count_setup"))
    name = request.form.get("zone_name", "").strip()
    if not name:
        flash("Zone name is required.", "error")
        return redirect(url_for("count_setup"))
    max_order = db.session.query(db.func.max(StorageZone.sort_order)).filter_by(restaurant_id=r.id).scalar() or 0
    zone = StorageZone(restaurant_id=r.id, name=name, sort_order=max_order + 1)
    db.session.add(zone)
    db.session.commit()
    flash(f"Zone '{name}' added.", "success")
    return redirect(url_for("count_setup"))


@app.route("/counts/setup/rename-zone/<int:id>", methods=["POST"])
def rename_zone(id):
    zone = StorageZone.query.get_or_404(id)
    new_name = request.form.get("zone_name", "").strip()
    if new_name:
        zone.name = new_name
        db.session.commit()
        flash(f"Zone renamed to '{new_name}'.", "success")
    return redirect(url_for("count_setup"))


@app.route("/counts/setup/delete-zone/<int:id>", methods=["POST"])
def delete_zone(id):
    zone = StorageZone.query.get_or_404(id)
    # Unassign items from this zone
    InventoryItemZone.query.filter_by(storage_zone_id=zone.id).delete()
    # Remove zone from any count entries
    CountEntry.query.filter_by(storage_zone_id=zone.id).update({"storage_zone_id": None})
    name = zone.name
    db.session.delete(zone)
    db.session.commit()
    flash(f"Zone '{name}' removed.", "success")
    return redirect(url_for("count_setup"))


@app.route("/counts/setup/reorder-zones", methods=["POST"])
def reorder_zones():
    data = request.get_json()
    for item in data.get("zones", []):
        zone = StorageZone.query.get(item.get("id"))
        if zone:
            zone.sort_order = item.get("order", 0)
    db.session.commit()
    return jsonify({"status": "ok"})


@app.route("/counts/setup/assign-items", methods=["POST"])
def assign_items_to_zones():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("count_setup"))
    items = InventoryItem.query.filter_by(restaurant_id=r.id).all()
    for item in items:
        field = f"zone_{item.id}"
        zone_id = request.form.get(field)
        zone_id = int(zone_id) if zone_id else None

        existing = InventoryItemZone.query.filter_by(inventory_item_id=item.id).first()
        if zone_id:
            if existing:
                existing.storage_zone_id = zone_id
            else:
                db.session.add(InventoryItemZone(
                    inventory_item_id=item.id,
                    storage_zone_id=zone_id,
                ))
        elif existing:
            db.session.delete(existing)
    db.session.commit()
    flash("Item zone assignments updated.", "success")
    return redirect(url_for("count_setup"))


@app.route("/counts/new", methods=["POST"])
def new_count():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("counts"))
    count_date = datetime.strptime(request.form.get("count_date", datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d")), "%Y-%m-%d").date()
    counted_by = request.form.get("counted_by", "")

    session = CountSession(
        restaurant_id=r.id,
        count_date=count_date,
        counted_by=counted_by,
        status="in_progress",
    )
    db.session.add(session)
    db.session.flush()

    # Calculate expected counts and pre-populate entries
    expected = calculate_expected_counts(r.id, count_date)
    items = InventoryItem.query.filter_by(restaurant_id=r.id).all()

    for item in items:
        zone_assignment = InventoryItemZone.query.filter_by(inventory_item_id=item.id).first()
        exp_data = expected.get(item.id, {})
        entry = CountEntry(
            session_id=session.id,
            inventory_item_id=item.id,
            storage_zone_id=zone_assignment.storage_zone_id if zone_assignment else None,
            actual_count=0,
            expected_count=exp_data.get("expected", item.current_stock or 0),
            unit_cost=item.last_cost or 0,
        )
        db.session.add(entry)

    db.session.commit()
    flash(f"Count session started for {count_date.strftime('%b %d, %Y')}.", "success")
    return redirect(url_for("count_sheet", id=session.id))


@app.route("/counts/<int:id>")
def count_sheet(id):
    session = CountSession.query.get_or_404(id)
    r = _get_selected_restaurant()
    zones = StorageZone.query.filter_by(restaurant_id=session.restaurant_id, active=True).order_by(StorageZone.sort_order).all()

    # Group entries by zone
    entries_by_zone = {}
    unzoned = []
    for entry in session.entries:
        zone_id = entry.storage_zone_id
        if zone_id:
            entries_by_zone.setdefault(zone_id, []).append(entry)
        else:
            unzoned.append(entry)

    return render_template("count_sheet.html",
        session=session,
        zones=zones,
        entries_by_zone=entries_by_zone,
        unzoned=unzoned,
    )


@app.route("/counts/<int:id>/save", methods=["POST"])
def save_count(id):
    session = CountSession.query.get_or_404(id)
    data = request.get_json()
    for entry_data in data.get("entries", []):
        entry = CountEntry.query.get(entry_data.get("id"))
        if entry and entry.session_id == session.id:
            entry.actual_count = float(entry_data.get("actual_count", 0))
            entry.notes = entry_data.get("notes", "")
    db.session.commit()
    return jsonify({"status": "saved"})


@app.route("/counts/<int:id>/submit", methods=["POST"])
def submit_count(id):
    session = CountSession.query.get_or_404(id)

    # Save any final counts from form
    for entry in session.entries:
        field_name = f"count_{entry.id}"
        if field_name in request.form:
            entry.actual_count = float(request.form.get(field_name, 0))
        notes_name = f"notes_{entry.id}"
        if notes_name in request.form:
            entry.notes = request.form.get(notes_name, "")

    # Calculate totals
    total_value = sum(e.actual_count * e.unit_cost for e in session.entries)
    total_variance = sum(e.variance_value for e in session.entries)

    session.status = "submitted"
    session.submitted_at = datetime.utcnow()
    session.total_value = round(total_value, 2)
    session.total_variance_value = round(total_variance, 2)

    # Update current_stock on inventory items
    for entry in session.entries:
        if entry.inventory_item:
            entry.inventory_item.current_stock = entry.actual_count

    db.session.commit()
    flash(f"Count submitted. Total variance: ${total_variance:,.2f}", "success")
    return redirect(url_for("count_report", id=session.id))


@app.route("/counts/<int:id>/report")
def count_report(id):
    report = generate_variance_report(id)
    if not report:
        flash("Count session not found.", "error")
        return redirect(url_for("counts"))
    return render_template("count_report.html", report=report)


@app.route("/payroll")
def payroll():
    r = _get_selected_restaurant()
    runs = PayrollRun.query.filter_by(restaurant_id=r.id).order_by(PayrollRun.period_end.desc()).all() if r else []
    employee_count = Employee.query.filter_by(restaurant_id=r.id, active=True).count() if r else 0
    return render_template("payroll.html", runs=runs, employee_count=employee_count)


@app.route("/payroll/export/<int:id>")
def export_payroll(id):
    pr = PayrollRun.query.get_or_404(id)
    employees = Employee.query.filter_by(restaurant_id=pr.restaurant_id, active=True).all()
    employees_data = [{"first_name": e.first_name, "last_name": e.last_name, "role": e.role, "pay_rate": e.pay_rate, "pay_type": e.pay_type} for e in employees]
    payroll_data = {
        "total_gross": pr.total_gross,
        "period_start": pr.period_start.strftime("%Y-%m-%d") if pr.period_start else "",
        "period_end": pr.period_end.strftime("%Y-%m-%d") if pr.period_end else "",
    }
    timestamp = datetime.now(CENTRAL_TZ).strftime("%Y%m%d_%H%M%S")
    output_path = f"/root/restaurant-ops/exports/payroll_{pr.id}_{timestamp}.iif"
    export_payroll_iif(payroll_data, employees_data, output_path)
    pr.qb_exported = True
    db.session.commit()
    return send_file(output_path, as_attachment=True, download_name=f"payroll_{timestamp}.iif")


@app.route("/vendors")
def vendors():
    vendor_list = Vendor.query.all()
    return render_template("vendors.html", vendors=vendor_list)


@app.route("/employees")
def employees():
    r = _get_selected_restaurant()
    emp_list = Employee.query.filter_by(restaurant_id=r.id).all() if r else []
    return render_template("employees.html", employees=emp_list)


@app.route("/employees/<int:emp_id>/manual-rate", methods=["POST"])
def employees_set_manual_rate(emp_id):
    """Set or clear an employee's manual_pay_rate override.

    Empty string clears the override (falls back to Toast pay_rate). Restricted
    to employees of the currently-selected restaurant to prevent cross-tenant
    edits.
    """
    r = _get_selected_restaurant()
    if not r:
        return jsonify({"ok": False, "error": "no restaurant selected"}), 400
    emp = Employee.query.filter_by(id=emp_id, restaurant_id=r.id).first()
    if not emp:
        return jsonify({"ok": False, "error": "not found"}), 404
    raw = (request.form.get("manual_pay_rate") or "").strip()
    if raw == "":
        emp.manual_pay_rate = None
    else:
        try:
            val = float(raw)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid number"}), 400
        if val < 0 or val > 1000:
            return jsonify({"ok": False, "error": "out of range"}), 400
        emp.manual_pay_rate = val
    db.session.commit()
    return jsonify({"ok": True, "manual_pay_rate": emp.manual_pay_rate})


@app.route("/recipes")
def recipes():
    r = _get_selected_restaurant()
    if not r:
        return render_template("recipes.html", all_recipes=[], subcategory_groups=[], food_recipes=[], beverage_recipes=[], inventory_items=[])
    all_recipes = Recipe.query.filter_by(restaurant_id=r.id, status='active').all()
    food_recipes = [rec for rec in all_recipes if rec.category == "food"]
    beverage_recipes = [rec for rec in all_recipes if rec.category == "beverage"]

    # Group recipes by subcategory (sorted alphabetically, with Uncategorized last)
    groups = {}
    for rec in all_recipes:
        key = rec.subcategory or "Uncategorized"
        groups.setdefault(key, []).append(rec)
    def _sort_key(name):
        return (1 if name == "Uncategorized" else 0, name.lower())
    subcategory_groups = [
        {"name": name, "slug": "sub-" + "".join(c if c.isalnum() else "-" for c in name).lower(), "recipes": recs, "count": len(recs)}
        for name, recs in sorted(groups.items(), key=lambda kv: _sort_key(kv[0]))
    ]

    inventory_items = InventoryItem.query.filter_by(restaurant_id=r.id).all()
    return render_template(
        "recipes.html",
        all_recipes=all_recipes,
        subcategory_groups=subcategory_groups,
        food_recipes=food_recipes,
        beverage_recipes=beverage_recipes,
        inventory_items=inventory_items,
    )


@app.route('/recipes/<int:recipe_id>')
def recipe_detail(recipe_id):
    restaurants = Restaurant.query.filter_by(active=True).all()
    recipe = Recipe.query.get_or_404(recipe_id)
    ingredients = RecipeIngredient.query.filter_by(recipe_id=recipe_id).all()
    return render_template('recipe_detail.html', recipe=recipe, ingredients=ingredients, restaurants=restaurants)


@app.route("/recipes/create", methods=["POST"])
def create_recipe():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("recipes"))
    recipe = Recipe(
        restaurant_id=r.id,
        name=request.form.get("name", ""),
        category=request.form.get("category", "food"),
        subcategory=request.form.get("subcategory", ""),
        menu_price=float(request.form.get("menu_price", 0)),
        portion_size=request.form.get("portion_size", ""),
        notes=request.form.get("notes", ""),
    )
    db.session.add(recipe)
    db.session.flush()

    ing_names = request.form.getlist("ing_name[]")
    ing_qtys = request.form.getlist("ing_qty[]")
    ing_units = request.form.getlist("ing_unit[]")
    ing_costs = request.form.getlist("ing_cost[]")
    ing_inv_ids = request.form.getlist("ing_inv_id[]")

    for i in range(len(ing_names)):
        if not ing_names[i].strip():
            continue
        inv_id = int(ing_inv_ids[i]) if ing_inv_ids[i] else None
        ingredient = RecipeIngredient(
            recipe_id=recipe.id,
            inventory_item_id=inv_id,
            name=ing_names[i],
            quantity=float(ing_qtys[i] or 0),
            unit=ing_units[i],
            unit_cost=float(ing_costs[i] or 0),
        )
        db.session.add(ingredient)

    db.session.commit()
    flash(f"Recipe '{recipe.name}' created.", "success")
    return redirect(url_for("recipes"))


@app.route("/recipes/<int:id>/edit", methods=["POST"])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    recipe.name = request.form.get("name", recipe.name)
    recipe.category = request.form.get("category", recipe.category)
    recipe.subcategory = request.form.get("subcategory", recipe.subcategory)
    recipe.menu_price = float(request.form.get("menu_price", recipe.menu_price))
    recipe.portion_size = request.form.get("portion_size", recipe.portion_size)
    recipe.notes = request.form.get("notes", recipe.notes)

    RecipeIngredient.query.filter_by(recipe_id=recipe.id).delete()

    ing_names = request.form.getlist("ing_name[]")
    ing_qtys = request.form.getlist("ing_qty[]")
    ing_units = request.form.getlist("ing_unit[]")
    ing_costs = request.form.getlist("ing_cost[]")
    ing_inv_ids = request.form.getlist("ing_inv_id[]")

    for i in range(len(ing_names)):
        if not ing_names[i].strip():
            continue
        inv_id = int(ing_inv_ids[i]) if ing_inv_ids[i] else None
        ingredient = RecipeIngredient(
            recipe_id=recipe.id,
            inventory_item_id=inv_id,
            name=ing_names[i],
            quantity=float(ing_qtys[i] or 0),
            unit=ing_units[i],
            unit_cost=float(ing_costs[i] or 0),
        )
        db.session.add(ingredient)

    db.session.commit()
    flash(f"Recipe '{recipe.name}' updated.", "success")
    return redirect(url_for("recipes"))


@app.route("/recipes/<int:id>/delete", methods=["POST"])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    name = recipe.name
    recipe.status = 'inactive'
    db.session.commit()
    flash(f"Recipe '{name}' removed.", "success")
    return redirect(url_for("recipes"))


@app.route("/recipes/import-csv", methods=["POST"])
def import_recipe_csv():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("recipes"))
    file = request.files.get("recipe_csv")
    if not file or file.filename == "":
        flash("No CSV file selected.", "error")
        return redirect(url_for("recipes"))
    content = file.read()
    recipes_data = parse_recipe_csv(content)
    if not recipes_data:
        flash("No recipes found in CSV. Check the format.", "error")
        return redirect(url_for("recipes"))
    count = 0
    for rec_data in recipes_data:
        recipe = Recipe(
            restaurant_id=r.id,
            name=rec_data.get("name", ""),
            category=rec_data.get("category", "food"),
            subcategory=rec_data.get("subcategory", ""),
            menu_price=float(rec_data.get("menu_price", 0)),
            xtra_chef_id=rec_data.get("xtra_chef_id", ""),
        )
        db.session.add(recipe)
        db.session.flush()
        for ing in rec_data.get("ingredients", []):
            result = match_item(
                restaurant_id=r.id,
                name=ing.get("name", ""),
                source="xtra_chef",
                unit=ing.get("unit", ""),
                auto_create_unmatched=False,
            )
            db.session.add(RecipeIngredient(
                recipe_id=recipe.id,
                inventory_item_id=result["item"].id if result["item"] else None,
                name=ing.get("name", ""),
                quantity=float(ing.get("quantity", 0)),
                unit=ing.get("unit", ""),
                unit_cost=float(ing.get("unit_cost", 0)),
            ))
        count += 1
    db.session.commit()
    flash(f"Imported {count} recipe(s) from CSV.", "success")
    return redirect(url_for("recipes"))


@app.route("/recipes/sync-toast", methods=["POST"])
def sync_toast_recipes():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("recipes"))
    menu_items = fetch_toast_menu(r)
    count = 0
    for item in menu_items:
        existing = Recipe.query.filter_by(
            restaurant_id=r.id, toast_recipe_id=item.get("toast_recipe_id")
        ).first() if item.get("toast_recipe_id") else None
        if existing:
            existing.menu_price = item.get("menu_price", existing.menu_price)
            existing.name = item.get("name", existing.name)
            existing.active = True
        else:
            recipe = Recipe(
                restaurant_id=r.id,
                name=item.get("name", ""),
                category=item.get("category", "food"),
                subcategory=item.get("subcategory", ""),
                menu_price=float(item.get("menu_price", 0)),
                portion_size=item.get("portion_size", ""),
                toast_recipe_id=item.get("toast_recipe_id", ""),
            )
            db.session.add(recipe)
            db.session.flush()
            for ing in item.get("ingredients", []):
                db.session.add(RecipeIngredient(
                    recipe_id=recipe.id,
                    name=ing.get("name", ""),
                    quantity=float(ing.get("quantity", 0)),
                    unit=ing.get("unit", ""),
                    unit_cost=float(ing.get("unit_cost", 0)),
                ))
            count += 1
    db.session.commit()
    flash(f"Synced {count} new recipe(s) from Toast POS.", "success")
    return redirect(url_for("recipes"))


@app.route("/api/recipe-cost", methods=["POST"])
def api_recipe_cost():
    data = request.get_json()
    ingredients = data.get("ingredients", [])
    menu_price = float(data.get("menu_price", 0))
    total_cost = 0
    for ing in ingredients:
        total_cost += float(ing.get("quantity", 0)) * float(ing.get("unit_cost", 0))
    margin = menu_price - total_cost if menu_price > 0 else 0
    margin_pct = ((menu_price - total_cost) / menu_price * 100) if menu_price > 0 else 0
    cost_pct = (total_cost / menu_price * 100) if menu_price > 0 else 0
    return jsonify({
        "total_cost": round(total_cost, 2),
        "margin": round(margin, 2),
        "margin_percent": round(margin_pct, 1),
        "cost_percent": round(cost_pct, 1),
    })


@app.route("/mapping")
def mapping():
    r = _get_selected_restaurant()
    pending = get_pending_unmatched(r.id) if r else []
    # Attach suggestions to each unmatched item
    for item in pending:
        item._suggestions = get_suggestions_for_unmatched(item)
    resolved_count = UnmatchedItem.query.filter(
        UnmatchedItem.restaurant_id == r.id,
        UnmatchedItem.status != "pending",
    ).count() if r else 0
    alias_count = ItemAlias.query.join(InventoryItem).filter(
        InventoryItem.restaurant_id == r.id,
        ItemAlias.confirmed == True,
    ).count() if r else 0
    inventory_items = InventoryItem.query.filter_by(restaurant_id=r.id).order_by(InventoryItem.name).all() if r else []
    return render_template("mapping.html",
        pending=pending,
        resolved_count=resolved_count,
        alias_count=alias_count,
        inventory_items=inventory_items,
    )


@app.route("/mapping/confirm", methods=["POST"])
def mapping_confirm():
    unmatched_id = int(request.form.get("unmatched_id", 0))
    inventory_item_id = int(request.form.get("inventory_item_id", 0))
    if confirm_match(unmatched_id, inventory_item_id):
        flash("Match confirmed and alias saved.", "success")
    else:
        flash("Could not confirm match.", "error")
    return redirect(url_for("mapping"))


@app.route("/mapping/create-new", methods=["POST"])
def mapping_create_new():
    unmatched_id = int(request.form.get("unmatched_id", 0))
    category = request.form.get("category", "uncategorized")
    item = create_new_from_unmatched(unmatched_id, category)
    if item:
        flash(f"Created new inventory item '{item.name}' and saved alias.", "success")
    else:
        flash("Could not create item.", "error")
    return redirect(url_for("mapping"))


@app.route("/mapping/dismiss", methods=["POST"])
def mapping_dismiss():
    unmatched_id = int(request.form.get("unmatched_id", 0))
    dismiss_unmatched(unmatched_id)
    flash("Item dismissed.", "success")
    return redirect(url_for("mapping"))


@app.route("/mapping/relink-recipes", methods=["POST"])
def relink_recipes():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("mapping"))
    count = auto_link_recipe_ingredients(r.id)
    flash(f"Re-linked {count} recipe ingredient(s) to inventory.", "success")
    return redirect(url_for("mapping"))


# Legacy /matching* paths — keep old bookmarks/tests working.
@app.route("/matching")
def matching_redirect():
    return redirect(url_for("mapping"), code=301)


@app.route("/matching/confirm", methods=["POST"])
def matching_confirm_redirect():
    return redirect(url_for("mapping_confirm"), code=308)


@app.route("/matching/create-new", methods=["POST"])
def matching_create_new_redirect():
    return redirect(url_for("mapping_create_new"), code=308)


@app.route("/matching/dismiss", methods=["POST"])
def matching_dismiss_redirect():
    return redirect(url_for("mapping_dismiss"), code=308)


@app.route("/matching/relink-recipes", methods=["POST"])
def matching_relink_redirect():
    return redirect(url_for("relink_recipes"), code=308)


# ========== Alerts ==========

@app.route("/alerts")
def alerts():
    r = _get_selected_restaurant()
    if not r:
        return render_template("alerts.html", alerts=[], counts={})
    open_alerts = (
        Alert.query.filter_by(restaurant_id=r.id, resolved=False)
        .order_by(
            db.case(
                {"critical": 0, "warning": 1, "info": 2},
                value=Alert.severity,
                else_=3,
            ),
            Alert.created_at.desc(),
        )
        .all()
    )
    return render_template("alerts.html", alerts=open_alerts)


@app.route("/alerts/<int:id>/resolve", methods=["POST"])
def alerts_resolve(id):
    a = Alert.query.get_or_404(id)
    a.resolved = True
    a.resolved_at = datetime.utcnow()
    db.session.commit()
    flash("Alert resolved.", "success")
    return redirect(request.referrer or url_for("alerts"))


@app.route("/alerts/run", methods=["POST"])
def alerts_run():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("alerts"))
    n = run_alerts(r.id)
    flash(f"Alert check complete — {n} new alert(s).", "success")
    return redirect(url_for("alerts"))


@app.route("/api/price-history/<int:item_id>")
def api_price_history(item_id):
    history = PriceHistory.query.filter_by(inventory_item_id=item_id).order_by(PriceHistory.recorded_at.asc()).all()
    return jsonify({
        "item_id": item_id,
        "history": [
            {
                "date": h.recorded_at.strftime("%Y-%m-%d %H:%M") if h.recorded_at else "",
                "old_cost": h.old_cost,
                "new_cost": h.new_cost,
                "change_percent": h.change_percent,
                "source": h.source,
            }
            for h in history
        ],
    })


@app.route("/api/dashboard-data")
def api_dashboard_data():
    r = _get_selected_restaurant()
    if not r:
        return jsonify({"error": "No restaurant selected"}), 400
    now = datetime.now(CENTRAL_TZ).date()
    pending_count = Invoice.query.filter_by(restaurant_id=r.id, status="pending").count()
    overdue_count = Invoice.query.filter(
        Invoice.restaurant_id == r.id,
        Invoice.status.in_(["pending", "approved"]),
        Invoice.due_date < now,
    ).count()
    low_stock_count = InventoryItem.query.filter(
        InventoryItem.restaurant_id == r.id,
        InventoryItem.current_stock < InventoryItem.par_level,
    ).count()
    thirty_days_ago = now - timedelta(days=30)
    spend = db.session.query(db.func.sum(Invoice.total_amount)).filter(
        Invoice.restaurant_id == r.id,
        Invoice.invoice_date >= thirty_days_ago,
    ).scalar() or 0
    return jsonify({
        "restaurant": r.name,
        "pending_count": pending_count,
        "overdue_count": overdue_count,
        "low_stock_count": low_stock_count,
        "thirty_day_spend": round(float(spend), 2),
    })


@app.route("/api/vendor-spend")
def api_vendor_spend():
    r = _get_selected_restaurant()
    if not r:
        return jsonify({"vendors": [], "amounts": []})
    thirty_days_ago = datetime.now(CENTRAL_TZ).date() - timedelta(days=30)
    results = (
        db.session.query(Vendor.name, db.func.sum(Invoice.total_amount))
        .join(Vendor, Invoice.vendor_id == Vendor.id)
        .filter(
            Invoice.restaurant_id == r.id,
            Invoice.invoice_date >= thirty_days_ago,
        )
        .group_by(Vendor.name)
        .order_by(db.func.sum(Invoice.total_amount).desc())
        .all()
    )
    vendors = [row[0] for row in results]
    amounts = [round(float(row[1]), 2) for row in results]
    return jsonify({"vendors": vendors, "amounts": amounts})


@app.route("/set-restaurant/<int:id>")
def set_restaurant(id):
    session["restaurant_id"] = id
    resp = make_response(redirect(request.referrer or url_for("dashboard")))
    resp.set_cookie("restaurant_id", str(id), max_age=60 * 60 * 24 * 365)
    return resp



# ── xtraCHEF Blueprint ───────────────────────────────────────────────────────
from xtrachef_blueprint import xtrachef_bp
app.register_blueprint(xtrachef_bp)

# ========== Background scheduler ==========

def _scheduler_run_alerts():
    """Wrapper so the scheduler job runs inside an app context."""
    with app.app_context():
        try:
            run_alerts_all()
        except Exception as e:
            print(f"[scheduler] run_alerts failed: {e}")


def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_scheduler_run_alerts, "interval", minutes=30, id="run_alerts")
    scheduler.start()
    # Run once on startup so we have fresh state right away
    _scheduler_run_alerts()


# Avoid double-start in Flask debug reloader. In production debug=False so this
# guard is essentially always true; in dev it gates on WERKZEUG_RUN_MAIN.
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _start_scheduler()


# ─────────────────────────────────────────────────────────────
# SCHEDULE / SHIFT MANAGEMENT
# ─────────────────────────────────────────────────────────────

def _week_bounds(date_str=None):
    from datetime import date, timedelta
    if date_str:
        try:
            pivot = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            pivot = datetime.now(CENTRAL_TZ).date()
    else:
        pivot = datetime.now(CENTRAL_TZ).date()
    monday = pivot - timedelta(days=pivot.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


@app.route("/schedule")
def schedule():
    from datetime import timedelta, date
    from sqlalchemy import func
    restaurant = _get_selected_restaurant()
    week_str = request.args.get("week")
    tab = request.args.get("tab", "full")
    monday, sunday = _week_bounds(week_str)
    week_days = [monday + timedelta(days=i) for i in range(7)]
    today_str = datetime.now(CENTRAL_TZ).date().isoformat()

    employees = Employee.query.filter_by(
        restaurant_id=restaurant.id, active=True
    ).order_by(Employee.role, Employee.last_name).all()

    positions = Position.query.filter_by(
        restaurant_id=restaurant.id, active=True
    ).order_by(Position.display_order).all()
    position_map = {p.name.lower(): p for p in positions}

    shifts = Shift.query.filter_by(restaurant_id=restaurant.id).filter(
        Shift.shift_date >= monday,
        Shift.shift_date <= sunday
    ).all()

    shift_map = {}
    for s in shifts:
        key = (s.employee_id, s.shift_date.isoformat())
        shift_map.setdefault(key, []).append(s)

    active_shifts = [s for s in shifts if s.status not in ('called_out', 'no_show', 'pto')]
    weekly_cost = sum(s.labor_cost for s in active_shifts)
    weekly_hours = sum(s.hours for s in active_shifts)

    emp_hours = {}
    for s in active_shifts:
        emp_hours[s.employee_id] = emp_hours.get(s.employee_id, 0) + s.hours
    rs = RestaurantSettings.query.filter_by(restaurant_id=restaurant.id).first()
    ot_threshold = rs.overtime_weekly_hours if rs else 40.0
    ot_rate = rs.overtime_weekly_rate if rs else 1.5
    ot_cost = 0.0
    ot_hours = 0.0
    for emp_id, hrs in emp_hours.items():
        if hrs > ot_threshold:
            extra = hrs - ot_threshold
            emp = Employee.query.get(emp_id)
            if emp:
                rate = emp.manual_pay_rate if emp.manual_pay_rate is not None else emp.pay_rate
                ot_cost += extra * rate * (ot_rate - 1)
                ot_hours += extra

    absences = len([s for s in shifts if s.status in ('called_out', 'no_show')])
    total_shifts = len([s for s in shifts if s.status != 'pto'])

    daily_cost = {}
    daily_hours = {}
    for s in active_shifts:
        d = s.shift_date.isoformat()
        daily_cost[d] = daily_cost.get(d, 0) + s.labor_cost
        daily_hours[d] = daily_hours.get(d, 0) + s.hours

    last_mon = monday - timedelta(days=7)
    last_sun = sunday - timedelta(days=7)
    last_week_sales_row = db.session.query(
        func.sum(MenuItemSale.total_revenue)
    ).filter(
        MenuItemSale.restaurant_id == restaurant.id,
        MenuItemSale.sale_date >= last_mon,
        MenuItemSale.sale_date <= last_sun
    ).scalar()
    last_week_sales = float(last_week_sales_row or 0)
    labor_pct_goal = rs.labor_pct_goal if rs else 25.0
    projected_labor_pct = (weekly_cost / last_week_sales * 100) if last_week_sales > 0 else None

    prev_week = (monday - timedelta(days=7)).isoformat()
    next_week = (monday + timedelta(days=7)).isoformat()
    restaurants = Restaurant.query.all()

    pending_pto = PTORequest.query.filter_by(
        restaurant_id=restaurant.id, status='pending'
    ).count()

    return render_template(
        "schedule.html",
        restaurant=restaurant,
        restaurants=restaurants,
        selected_restaurant=restaurant,
        week_days=week_days,
        monday=monday,
        today_str=today_str,
        tab=tab,
        employees=employees,
        positions=positions,
        position_map=position_map,
        shift_map=shift_map,
        daily_cost=daily_cost,
        daily_hours=daily_hours,
        weekly_cost=weekly_cost,
        weekly_hours=weekly_hours,
        ot_cost=ot_cost,
        ot_hours=ot_hours,
        absences=absences,
        total_shifts=total_shifts,
        last_week_sales=last_week_sales,
        projected_labor_pct=projected_labor_pct,
        labor_pct_goal=labor_pct_goal,
        prev_week=prev_week,
        next_week=next_week,
        pending_pto=pending_pto,
    )


@app.route("/schedule/shift/add", methods=["POST"])
def schedule_add_shift():
    restaurant = _get_selected_restaurant()
    data = request.form
    shift_date = None
    try:
        shift_date = datetime.strptime(data["shift_date"], "%Y-%m-%d").date()
        shift = Shift(
            restaurant_id=restaurant.id,
            employee_id=int(data["employee_id"]),
            shift_date=shift_date,
            start_time=data["start_time"],
            end_time=data["end_time"],
            role=data.get("role", ""),
            status=data.get("status", "scheduled"),
            notes=data.get("notes", ""),
        )
        db.session.add(shift)
        db.session.commit()
        flash("Shift added.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error adding shift: {e}", "danger")
    week_str = data.get("week") or (shift_date.isoformat() if shift_date else None)
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/shift/<int:shift_id>/edit", methods=["POST"])
def schedule_edit_shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    data = request.form
    try:
        shift.employee_id = int(data["employee_id"])
        shift.shift_date = datetime.strptime(data["shift_date"], "%Y-%m-%d").date()
        shift.start_time = data["start_time"]
        shift.end_time = data["end_time"]
        shift.role = data.get("role", shift.role)
        shift.status = data.get("status", shift.status)
        shift.notes = data.get("notes", shift.notes)
        db.session.commit()
        flash("Shift updated.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error updating shift: {e}", "danger")
    week_str = data.get("week", shift.shift_date.isoformat())
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/shift/<int:shift_id>/delete", methods=["POST"])
def schedule_delete_shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    week_str = request.form.get("week", shift.shift_date.isoformat())
    try:
        db.session.delete(shift)
        db.session.commit()
        flash("Shift removed.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "danger")
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/copy-week", methods=["POST"])
def schedule_copy_week():
    from datetime import timedelta
    restaurant = _get_selected_restaurant()
    week_str = request.form.get("week")
    monday, sunday = _week_bounds(week_str)
    last_mon = monday - timedelta(days=7)
    last_sun = sunday - timedelta(days=7)

    source_shifts = Shift.query.filter_by(restaurant_id=restaurant.id).filter(
        Shift.shift_date >= last_mon,
        Shift.shift_date <= last_sun
    ).all()

    copied = 0
    for s in source_shifts:
        new_date = s.shift_date + timedelta(days=7)
        exists = Shift.query.filter_by(
            restaurant_id=restaurant.id,
            employee_id=s.employee_id,
            shift_date=new_date,
            start_time=s.start_time,
            end_time=s.end_time,
        ).first()
        if not exists:
            db.session.add(Shift(
                restaurant_id=restaurant.id,
                employee_id=s.employee_id,
                shift_date=new_date,
                start_time=s.start_time,
                end_time=s.end_time,
                role=s.role,
                status='scheduled',
                notes=s.notes,
            ))
            copied += 1

    db.session.commit()
    flash(f"Copied {copied} shift{'s' if copied != 1 else ''} from last week.", "success")
    return redirect(url_for("schedule", week=monday.isoformat()))


@app.route("/api/schedule/shift/<int:shift_id>")
def api_get_shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    return jsonify({
        "id": shift.id,
        "employee_id": shift.employee_id,
        "shift_date": shift.shift_date.isoformat(),
        "start_time": shift.start_time,
        "end_time": shift.end_time,
        "role": shift.role or "",
        "status": shift.status,
        "notes": shift.notes or "",
        "hours": round(shift.hours, 1),
        "labor_cost": round(shift.labor_cost, 2),
    })

# ─────────────────────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username, active=True).first()
        if user and user.check_password(password):
            user.last_login = datetime.now(CENTRAL_TZ)
            db.session.commit()
            login_user(user, remember=True)
            if user.temp_password:
                flash("Welcome! Please set a new password.", "info")
                return redirect(url_for("change_password"))
            next_page = request.args.get("next")
            return redirect(next_page or url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if not current_user.check_password(current_pw):
            flash("Current password is incorrect.", "danger")
        elif len(new_pw) < 8:
            flash("New password must be at least 8 characters.", "danger")
        elif new_pw != confirm_pw:
            flash("Passwords do not match.", "danger")
        else:
            current_user.set_password(new_pw)
            current_user.temp_password = False
            db.session.commit()
            flash("Password updated successfully.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")


@app.route("/api/auth/status")
def auth_status():
    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "role": current_user.role,
            "restaurant_id": current_user.restaurant_id,
        })
    return jsonify({"authenticated": False})

# ─────────────────────────────────────────────────────────────
# USER ACCOUNT MANAGEMENT
# ─────────────────────────────────────────────────────────────

@app.route("/admin/sync-users", methods=["POST"])
@login_required
def sync_users_from_toast():
    """Auto-create User accounts for managers and owners from Toast employee data."""
    import random
    import string

    if not current_user.is_owner:
        flash("Owner access required.", "danger")
        return redirect(url_for("dashboard"))

    MANAGER_ROLES = {
        'owner', 'general manager', 'assistant general manager',
        'kitchen manager', 'bar manager', 'floor manager', 'shift manager',
        'manager', 'agm', 'gm'
    }

    employees = Employee.query.filter_by(active=True).all()
    created = []
    skipped = []

    for emp in employees:
        role_lower = (emp.role or '').lower().strip()
        if not any(mr in role_lower for mr in MANAGER_ROLES):
            continue

        username = f"{(emp.first_name or '').lower().strip()}.{(emp.last_name or '').lower().strip()}"
        username = username.replace(' ', '').replace("'", '')
        if not username or username == '.':
            continue

        existing = User.query.filter_by(username=username).first()
        if existing:
            skipped.append(username)
            continue

        # Determine role
        user_role = 'owner' if 'owner' in role_lower or 'general manager' in role_lower else 'manager'

        # Owners get NULL restaurant_id (all access)
        restaurant_id = None if user_role == 'owner' else emp.restaurant_id

        # Generate temp password
        temp_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=10))

        user = User(
            username=username,
            first_name=emp.first_name,
            last_name=emp.last_name,
            role=user_role,
            restaurant_id=restaurant_id,
            temp_password=True,
            active=True,
        )
        user.set_password(temp_pw)
        db.session.add(user)
        created.append({
            'username': username,
            'temp_password': temp_pw,
            'role': user_role,
            'restaurant': emp.restaurant.name if emp.restaurant else 'All',
        })

    db.session.commit()

    # Print credentials to log (one time only)
    if created:
        app.logger.info("=" * 60)
        app.logger.info("NEW USER ACCOUNTS CREATED — TEMP PASSWORDS (one time only)")
        app.logger.info("=" * 60)
        for u in created:
            app.logger.info(f"  {u['username']:30} pw: {u['temp_password']:12} role: {u['role']:8} location: {u['restaurant']}")
        app.logger.info("=" * 60)

    flash(f"Created {len(created)} user account(s). Skipped {len(skipped)} existing. Check server logs for temp passwords.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/users")
@login_required
def admin_users():
    """Simple user management page for owners."""
    if not current_user.is_owner:
        flash("Owner access required.", "danger")
        return redirect(url_for("dashboard"))
    users = User.query.order_by(User.role, User.last_name).all()
    restaurants = Restaurant.query.all()
    return render_template("admin_users.html",
        users=users,
        restaurants=restaurants,
        selected_restaurant=_get_selected_restaurant()
    )


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
def reset_user_password(user_id):
    if not current_user.is_owner:
        flash("Owner access required.", "danger")
        return redirect(url_for("dashboard"))
    import random, string
    user = User.query.get_or_404(user_id)
    temp_pw = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    user.set_password(temp_pw)
    user.temp_password = True
    db.session.commit()
    app.logger.info(f"PASSWORD RESET: {user.username} new temp pw: {temp_pw}")
    flash(f"Password reset for {user.username}. New temp password printed to server log.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_user_active(user_id):
    if not current_user.is_owner:
        flash("Owner access required.", "danger")
        return redirect(url_for("dashboard"))
    user = User.query.get_or_404(user_id)
    user.active = not user.active
    db.session.commit()
    flash(f"{'Activated' if user.active else 'Deactivated'} {user.username}.", "success")
    return redirect(url_for("admin_users"))

# ─────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────

def _get_or_create_settings(restaurant_id):
    s = RestaurantSettings.query.filter_by(restaurant_id=restaurant_id).first()
    if not s:
        s = RestaurantSettings(restaurant_id=restaurant_id)
        db.session.add(s)
        db.session.commit()
    return s

def _get_or_create_prefs(user_id):
    p = ManagerPreference.query.filter_by(user_id=user_id).first()
    if not p:
        p = ManagerPreference(user_id=user_id)
        db.session.add(p)
        db.session.commit()
    return p

@app.route("/settings")
def settings():
    restaurant = _get_selected_restaurant()
    restaurants = Restaurant.query.all()
    tab = request.args.get("tab", "notifications")
    rs = _get_or_create_settings(restaurant.id)
    positions = Position.query.filter_by(
        restaurant_id=restaurant.id, active=True
    ).order_by(Position.display_order).all()
    prefs = None
    if current_user.is_authenticated:
        prefs = _get_or_create_prefs(current_user.id)
    return render_template("settings.html",
        restaurant=restaurant,
        restaurants=restaurants,
        selected_restaurant=restaurant,
        tab=tab,
        rs=rs,
        positions=positions,
        prefs=prefs,
    )

@app.route("/settings/notifications", methods=["POST"])
def settings_save_notifications():
    if not current_user.is_authenticated:
        flash("Please log in to save preferences.", "warning")
        return redirect(url_for("settings", tab="notifications"))
    prefs = _get_or_create_prefs(current_user.id)
    f = request.form
    prefs.notify_pto_email     = 'notify_pto_email'     in f
    prefs.notify_pto_sms       = 'notify_pto_sms'       in f
    prefs.notify_pto_inapp     = 'notify_pto_inapp'     in f
    prefs.notify_shift_email   = 'notify_shift_email'   in f
    prefs.notify_shift_sms     = 'notify_shift_sms'     in f
    prefs.notify_shift_inapp   = 'notify_shift_inapp'   in f
    prefs.notify_low_stock_email  = 'notify_low_stock_email'  in f
    prefs.notify_low_stock_inapp  = 'notify_low_stock_inapp'  in f
    prefs.notify_payroll_email    = 'notify_payroll_email'    in f
    prefs.notify_payroll_inapp    = 'notify_payroll_inapp'    in f
    prefs.notify_invoice_email    = 'notify_invoice_email'    in f
    prefs.notify_invoice_inapp    = 'notify_invoice_inapp'    in f
    prefs.phone_number   = f.get("phone_number", "").strip()
    prefs.email_override = f.get("email_override", "").strip()
    db.session.commit()
    flash("Notification preferences saved.", "success")
    return redirect(url_for("settings", tab="notifications"))

@app.route("/settings/schedule", methods=["POST"])
def settings_save_schedule():
    restaurant = _get_selected_restaurant()
    rs = _get_or_create_settings(restaurant.id)
    f = request.form
    rs.week_start               = f.get("week_start", "monday")
    rs.clopening_warning        = 'clopening_warning' in f
    rs.clopening_min_hours      = float(f.get("clopening_min_hours", 10))
    rs.shift_acceptance         = 'shift_acceptance' in f
    rs.allow_shift_swaps        = 'allow_shift_swaps' in f
    rs.unavailability_approval  = 'unavailability_approval' in f
    db.session.commit()
    flash("Schedule settings saved.", "success")
    return redirect(url_for("settings", tab="schedule"))

@app.route("/settings/labor", methods=["POST"])
def settings_save_labor():
    restaurant = _get_selected_restaurant()
    rs = _get_or_create_settings(restaurant.id)
    f = request.form
    rs.overtime_weekly_enabled = 'overtime_weekly_enabled' in f
    rs.overtime_weekly_hours   = float(f.get("overtime_weekly_hours", 40))
    rs.overtime_weekly_rate    = float(f.get("overtime_weekly_rate", 1.5))
    rs.overtime_daily_enabled  = 'overtime_daily_enabled' in f
    rs.overtime_daily_hours    = float(f.get("overtime_daily_hours", 8))
    rs.overtime_daily_rate     = float(f.get("overtime_daily_rate", 1.5))
    rs.labor_pct_goal          = float(f.get("labor_pct_goal", 25))
    db.session.commit()
    flash("Labor cost settings saved.", "success")
    return redirect(url_for("settings", tab="labor"))

@app.route("/settings/timeoff", methods=["POST"])
def settings_save_timeoff():
    restaurant = _get_selected_restaurant()
    rs = _get_or_create_settings(restaurant.id)
    f = request.form
    rs.pto_enabled           = 'pto_enabled' in f
    rs.pto_requires_approval = 'pto_requires_approval' in f
    rs.pto_accrual_rate      = float(f.get("pto_accrual_rate", 0.025))
    rs.pto_usage_cap         = float(f.get("pto_usage_cap", 40))
    db.session.commit()
    flash("Time off settings saved.", "success")
    return redirect(url_for("settings", tab="timeoff"))

@app.route("/settings/positions/add", methods=["POST"])
def settings_add_position():
    restaurant = _get_selected_restaurant()
    f = request.form
    name = f.get("name", "").strip()
    if name:
        exists = Position.query.filter_by(
            restaurant_id=restaurant.id, name=name
        ).first()
        if not exists:
            max_order = db.session.query(
                db.func.max(Position.display_order)
            ).filter_by(restaurant_id=restaurant.id).scalar() or 0
            db.session.add(Position(
                restaurant_id=restaurant.id,
                name=name,
                color_hex=f.get("color_hex", "#64748b"),
                display_order=max_order + 1,
            ))
            db.session.commit()
            flash(f"Position '{name}' added.", "success")
        else:
            flash(f"Position '{name}' already exists.", "warning")
    return redirect(url_for("settings", tab="positions"))

@app.route("/settings/positions/<int:pos_id>/edit", methods=["POST"])
def settings_edit_position(pos_id):
    pos = Position.query.get_or_404(pos_id)
    f = request.form
    pos.name      = f.get("name", pos.name).strip()
    pos.color_hex = f.get("color_hex", pos.color_hex)
    pos.active    = 'active' in f
    db.session.commit()
    flash("Position updated.", "success")
    return redirect(url_for("settings", tab="positions"))

@app.route("/settings/positions/<int:pos_id>/delete", methods=["POST"])
def settings_delete_position(pos_id):
    pos = Position.query.get_or_404(pos_id)
    pos.active = False
    db.session.commit()
    flash("Position removed.", "success")
    return redirect(url_for("settings", tab="positions"))

# ─────────────────────────────────────────────────────────────
# PTO SYSTEM
# ─────────────────────────────────────────────────────────────

def _get_or_create_pto_balance(employee_id, restaurant_id, year):
    b = PTOBalance.query.filter_by(
        employee_id=employee_id,
        restaurant_id=restaurant_id,
        year=year
    ).first()
    if not b:
        b = PTOBalance(
            employee_id=employee_id,
            restaurant_id=restaurant_id,
            year=year,
            hours_accrued=0.0,
            hours_used=0.0,
            hours_carried=0.0,
        )
        db.session.add(b)
        db.session.flush()
    return b


def _accrue_pto_from_timesheets(restaurant_id):
    """
    Run after every Toast timesheet sync.
    Reads actual punched hours from the last 90 days and updates PTOBalance.
    1 hr PTO per 40 hrs worked. Balance never expires. Usage capped at 40hrs/year.
    """
    from datetime import date, timedelta
    from sqlalchemy import func

    policy = PTOPolicy.query.filter_by(restaurant_id=restaurant_id).first()
    if not policy or not policy.enabled:
        return

    rate = policy.accrual_rate  # default 0.025

    # Get all timesheets for this restaurant from Toast DB
    # We use the PayrollRun / timesheet data already in DB
    # For now we approximate from Shift actuals with status != called_out/no_show
    today = datetime.now(CENTRAL_TZ).date()
    year = today.year
    cutoff = today - timedelta(days=90)

    employees = Employee.query.filter_by(
        restaurant_id=restaurant_id, active=True
    ).all()

    for emp in employees:
        # Sum actual hours from shifts in the last 90 days
        shifts = Shift.query.filter_by(
            employee_id=emp.id,
            restaurant_id=restaurant_id,
        ).filter(
            Shift.shift_date >= cutoff,
            Shift.shift_date <= today,
            Shift.status.notin_(['called_out', 'no_show']),
        ).all()

        hours_worked = sum(s.hours for s in shifts)
        new_accrual = round(hours_worked * rate, 2)

        balance = _get_or_create_pto_balance(emp.id, restaurant_id, year)

        # Only update if accrual has changed since last run
        if balance.last_accrual_date != today:
            balance.hours_accrued = new_accrual
            balance.last_accrual_date = today
            balance.updated_at = datetime.utcnow()

    db.session.commit()


@app.route("/pto")
def pto():
    from datetime import date
    restaurant = _get_selected_restaurant()
    restaurants = Restaurant.query.all()
    year = int(request.args.get("year", datetime.now(CENTRAL_TZ).year))

    employees = Employee.query.filter_by(
        restaurant_id=restaurant.id, active=True
    ).order_by(Employee.last_name).all()

    # Build balance map
    balances = PTOBalance.query.filter_by(
        restaurant_id=restaurant.id, year=year
    ).all()
    balance_map = {b.employee_id: b for b in balances}

    # Ensure every employee has a balance row
    for emp in employees:
        if emp.id not in balance_map:
            b = _get_or_create_pto_balance(emp.id, restaurant.id, year)
            balance_map[emp.id] = b
    db.session.commit()

    # Pending requests
    pending = PTORequest.query.filter_by(
        restaurant_id=restaurant.id,
        status='pending'
    ).order_by(PTORequest.requested_at).all()

    # Recent approved/denied
    recent = PTORequest.query.filter_by(
        restaurant_id=restaurant.id
    ).filter(
        PTORequest.status.in_(['approved', 'denied'])
    ).order_by(PTORequest.reviewed_at.desc()).limit(20).all()

    policy = PTOPolicy.query.filter_by(restaurant_id=restaurant.id).first()
    if not policy:
        policy = PTOPolicy(restaurant_id=restaurant.id)
        db.session.add(policy)
        db.session.commit()

    # Coverage warning: count pending requests per date
    from collections import defaultdict
    date_conflicts = defaultdict(list)
    all_pending = PTORequest.query.filter_by(
        restaurant_id=restaurant.id, status='pending'
    ).all()
    for req in all_pending:
        if req.start_date and req.end_date:
            d = req.start_date
            from datetime import timedelta
            while d <= req.end_date:
                date_conflicts[d].append(req.employee.first_name + ' ' + req.employee.last_name)
                d += timedelta(days=1)

    return render_template("pto.html",
        restaurant=restaurant,
        restaurants=restaurants,
        selected_restaurant=restaurant,
        employees=employees,
        balance_map=balance_map,
        pending=pending,
        recent=recent,
        policy=policy,
        year=year,
        date_conflicts=date_conflicts,
    )


@app.route("/pto/request/add", methods=["POST"])
def pto_add_request():
    """Manager submits PTO on behalf of employee (pre-auth). Employee self-service after auth."""
    from datetime import date
    restaurant = _get_selected_restaurant()
    f = request.form
    try:
        start = datetime.strptime(f["start_date"], "%Y-%m-%d").date()
        end = datetime.strptime(f["end_date"], "%Y-%m-%d").date()
        if end < start:
            flash("End date cannot be before start date.", "danger")
            return redirect(url_for("pto"))
        hours = float(f.get("hours_requested", 8))
        req = PTORequest(
            employee_id=int(f["employee_id"]),
            restaurant_id=restaurant.id,
            start_date=start,
            end_date=end,
            hours_requested=hours,
            notes=f.get("notes", ""),
            status='pending',
        )
        db.session.add(req)
        db.session.commit()

        # Create in-app alert
        emp = Employee.query.get(int(f["employee_id"]))
        db.session.add(Alert(
            restaurant_id=restaurant.id,
            alert_type='pto_request',
            message=f"PTO request: {emp.first_name} {emp.last_name} — {start.strftime('%b %-d')} to {end.strftime('%b %-d')} ({hours}h)",
            severity='info',
        ))
        db.session.commit()
        flash("PTO request submitted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "danger")
    return redirect(url_for("pto"))


@app.route("/pto/request/<int:req_id>/approve", methods=["POST"])
def pto_approve(req_id):
    from datetime import date
    req = PTORequest.query.get_or_404(req_id)
    year = req.start_date.year
    balance = _get_or_create_pto_balance(req.employee_id, req.restaurant_id, year)

    # Check if enough hours available
    if req.hours_requested > balance.total_available:
        flash(f"Warning: Employee only has {balance.total_available:.1f}h available but {req.hours_requested:.1f}h requested. Approving anyway.", "warning")

    # Check annual usage cap
    policy = PTOPolicy.query.filter_by(restaurant_id=req.restaurant_id).first()
    cap = policy.usage_cap if policy else 40.0
    if balance.hours_used + req.hours_requested > cap:
        flash(f"Warning: This approval would exceed the {cap:.0f}h annual cap. Approving anyway.", "warning")

    req.status = 'approved'
    req.reviewed_at = datetime.utcnow()
    if current_user.is_authenticated:
        req.reviewed_by_id = current_user.id

    # Deduct from balance
    balance.hours_used += req.hours_requested
    balance.updated_at = datetime.utcnow()

    # Add PTO shift to schedule
    from datetime import timedelta
    d = req.start_date
    while d <= req.end_date:
        existing = Shift.query.filter_by(
            employee_id=req.employee_id,
            restaurant_id=req.restaurant_id,
            shift_date=d,
            status='pto',
        ).first()
        if not existing:
            db.session.add(Shift(
                employee_id=req.employee_id,
                restaurant_id=req.restaurant_id,
                shift_date=d,
                start_time='09:00',
                end_time='17:00',
                role='PTO',
                status='pto',
                notes=f"Approved PTO — {req.hours_requested}h",
            ))
        d += timedelta(days=1)

    db.session.commit()
    flash(f"PTO approved. {req.hours_requested:.1f}h deducted from balance.", "success")
    return redirect(url_for("pto"))


@app.route("/pto/request/<int:req_id>/deny", methods=["POST"])
def pto_deny(req_id):
    req = PTORequest.query.get_or_404(req_id)
    req.status = 'denied'
    req.reviewed_at = datetime.utcnow()
    req.denial_reason = request.form.get("denial_reason", "")
    req.denial_notes = request.form.get("denial_notes", "")
    if current_user.is_authenticated:
        req.reviewed_by_id = current_user.id
    db.session.commit()
    flash("PTO request denied.", "info")
    return redirect(url_for("pto"))


@app.route("/pto/balance/<int:employee_id>/adjust", methods=["POST"])
def pto_adjust_balance(employee_id):
    """Manual balance adjustment by manager."""
    restaurant = _get_selected_restaurant()
    year = int(request.form.get("year", datetime.now(CENTRAL_TZ).year))
    balance = _get_or_create_pto_balance(employee_id, restaurant.id, year)
    try:
        adj_type = request.form.get("adj_type", "add")
        hours = float(request.form.get("hours", 0))
        if adj_type == "add":
            balance.hours_accrued += hours
        elif adj_type == "subtract":
            balance.hours_used += hours
        elif adj_type == "set_accrued":
            balance.hours_accrued = hours
        elif adj_type == "set_carried":
            balance.hours_carried = hours
        balance.updated_at = datetime.utcnow()
        db.session.commit()
        flash(f"Balance adjusted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "danger")
    return redirect(url_for("pto"))


@app.route("/api/pto/balance/<int:employee_id>")
def api_pto_balance(employee_id):
    year = int(request.args.get("year", datetime.now(CENTRAL_TZ).year))
    restaurant = _get_selected_restaurant()
    b = PTOBalance.query.filter_by(
        employee_id=employee_id,
        restaurant_id=restaurant.id,
        year=year
    ).first()
    if not b:
        return jsonify({"accrued": 0, "used": 0, "carried": 0, "available": 0, "remaining_cap": 40})
    return jsonify({
        "accrued": round(b.hours_accrued, 2),
        "used": round(b.hours_used, 2),
        "carried": round(b.hours_carried, 2),
        "available": round(b.total_available, 2),
        "remaining_cap": round(b.hours_remaining_this_year, 2),
    })

# ─────────────────────────────────────────────────────────────
# SCHEDULE — DRAFT/PUBLISH, TEMPLATES, OPEN SHIFTS
# ─────────────────────────────────────────────────────────────

def _get_or_create_schedule_week(restaurant_id, monday):
    sw = ScheduleWeek.query.filter_by(
        restaurant_id=restaurant_id,
        week_start=monday
    ).first()
    if not sw:
        sw = ScheduleWeek(
            restaurant_id=restaurant_id,
            week_start=monday,
            status='draft',
        )
        db.session.add(sw)
        db.session.commit()
    return sw


@app.route("/schedule/publish", methods=["POST"])
def schedule_publish():
    from datetime import date
    restaurant = _get_selected_restaurant()
    week_str = request.form.get("week")
    monday, sunday = _week_bounds(week_str)
    sw = _get_or_create_schedule_week(restaurant.id, monday)
    sw.status = 'published'
    sw.published_at = datetime.now(CENTRAL_TZ)
    if current_user.is_authenticated:
        sw.published_by_id = current_user.id
    db.session.commit()
    # Notification to employees skipped during testing
    flash(f"Schedule published for week of {monday.strftime('%b %-d')}.", "success")
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/unpublish", methods=["POST"])
def schedule_unpublish():
    restaurant = _get_selected_restaurant()
    week_str = request.form.get("week")
    monday, sunday = _week_bounds(week_str)
    sw = _get_or_create_schedule_week(restaurant.id, monday)
    sw.status = 'draft'
    sw.published_at = None
    db.session.commit()
    flash("Schedule moved back to draft.", "info")
    return redirect(url_for("schedule", week=week_str))


@app.route("/api/schedule/autosave", methods=["POST"])
def schedule_autosave():
    """Called automatically when any shift is added/edited to mark week as draft."""
    restaurant = _get_selected_restaurant()
    data = request.get_json()
    week_str = data.get("week")
    if not week_str:
        return jsonify({"ok": False})
    monday, sunday = _week_bounds(week_str)
    sw = _get_or_create_schedule_week(restaurant.id, monday)
    # If published, move back to draft on any change
    if sw.status == 'published':
        sw.status = 'draft'
    sw.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "status": sw.status})


# ── SHIFT COPY/PASTE ──
@app.route("/api/schedule/shift/copy", methods=["POST"])
def schedule_copy_shift():
    """Return shift data for client-side clipboard."""
    shift_id = request.get_json().get("shift_id")
    shift = Shift.query.get_or_404(shift_id)
    return jsonify({
        "start_time": shift.start_time,
        "end_time": shift.end_time,
        "role": shift.role or "",
        "notes": shift.notes or "",
        "hours": round(shift.hours, 1),
    })


@app.route("/api/schedule/shift/paste", methods=["POST"])
def schedule_paste_shift():
    """Create a new shift from clipboard data."""
    restaurant = _get_selected_restaurant()
    data = request.get_json()
    try:
        shift_date = datetime.strptime(data["shift_date"], "%Y-%m-%d").date()
        shift = Shift(
            restaurant_id=restaurant.id,
            employee_id=int(data["employee_id"]),
            shift_date=shift_date,
            start_time=data["start_time"],
            end_time=data["end_time"],
            role=data.get("role", ""),
            status="scheduled",
            notes=data.get("notes", ""),
        )
        db.session.add(shift)
        db.session.commit()
        # Autosave
        monday, _ = _week_bounds(data.get("week"))
        sw = _get_or_create_schedule_week(restaurant.id, monday)
        if sw.status == 'published':
            sw.status = 'draft'
        db.session.commit()
        return jsonify({"ok": True, "shift_id": shift.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/schedule/shift/move", methods=["POST"])
def schedule_move_shift():
    """Drag shift to new employee and/or date."""
    data = request.get_json()
    shift = Shift.query.get_or_404(data["shift_id"])
    try:
        if data.get("employee_id"):
            shift.employee_id = int(data["employee_id"])
        if data.get("shift_date"):
            shift.shift_date = datetime.strptime(data["shift_date"], "%Y-%m-%d").date()
        db.session.commit()
        restaurant = _get_selected_restaurant()
        monday, _ = _week_bounds(data.get("week"))
        sw = _get_or_create_schedule_week(restaurant.id, monday)
        if sw.status == 'published':
            sw.status = 'draft'
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)})


# ── TEMPLATES ──
@app.route("/schedule/templates")
def schedule_templates():
    restaurant = _get_selected_restaurant()
    templates = ShiftTemplate.query.filter_by(restaurant_id=restaurant.id).all()
    restaurants = Restaurant.query.all()
    return render_template("schedule_templates.html",
        restaurant=restaurant,
        restaurants=restaurants,
        selected_restaurant=restaurant,
        templates=templates,
    )


@app.route("/schedule/templates/save", methods=["POST"])
def schedule_save_template():
    """Save current week's shifts as a named template."""
    restaurant = _get_selected_restaurant()
    week_str = request.form.get("week")
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        flash("Template name is required.", "danger")
        return redirect(url_for("schedule", week=week_str))

    monday, sunday = _week_bounds(week_str)
    shifts = Shift.query.filter_by(restaurant_id=restaurant.id).filter(
        Shift.shift_date >= monday,
        Shift.shift_date <= sunday,
        Shift.status.notin_(['pto', 'called_out', 'no_show']),
    ).all()

    if not shifts:
        flash("No shifts this week to save as template.", "warning")
        return redirect(url_for("schedule", week=week_str))

    template = ShiftTemplate(
        restaurant_id=restaurant.id,
        name=name,
        description=description,
        created_by_id=current_user.id if current_user.is_authenticated else None,
    )
    db.session.add(template)
    db.session.flush()

    for s in shifts:
        entry = ShiftTemplateEntry(
            template_id=template.id,
            day_of_week=s.shift_date.weekday(),
            start_time=s.start_time,
            end_time=s.end_time,
            role=s.role,
            notes=s.notes,
            employee_id=s.employee_id,
        )
        db.session.add(entry)

    db.session.commit()
    flash(f"Template '{name}' saved with {len(shifts)} shifts.", "success")
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/templates/<int:template_id>/load", methods=["POST"])
def schedule_load_template(template_id):
    """Load a template onto the current week."""
    from datetime import timedelta
    restaurant = _get_selected_restaurant()
    week_str = request.form.get("week")
    monday, sunday = _week_bounds(week_str)
    template = ShiftTemplate.query.get_or_404(template_id)
    overwrite = request.form.get("overwrite") == "1"

    if overwrite:
        Shift.query.filter_by(restaurant_id=restaurant.id).filter(
            Shift.shift_date >= monday,
            Shift.shift_date <= sunday,
        ).delete()
        db.session.flush()

    loaded = 0
    for entry in template.entries:
        shift_date = monday + timedelta(days=entry.day_of_week)
        if not overwrite:
            exists = Shift.query.filter_by(
                restaurant_id=restaurant.id,
                employee_id=entry.employee_id,
                shift_date=shift_date,
                start_time=entry.start_time,
                end_time=entry.end_time,
            ).first()
            if exists:
                continue
        db.session.add(Shift(
            restaurant_id=restaurant.id,
            employee_id=entry.employee_id,
            shift_date=shift_date,
            start_time=entry.start_time,
            end_time=entry.end_time,
            role=entry.role,
            status='scheduled',
            notes=entry.notes,
        ))
        loaded += 1

    sw = _get_or_create_schedule_week(restaurant.id, monday)
    sw.status = 'draft'
    db.session.commit()
    flash(f"Loaded {loaded} shifts from template '{template.name}'.", "success")
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/templates/<int:template_id>/delete", methods=["POST"])
def schedule_delete_template(template_id):
    template = ShiftTemplate.query.get_or_404(template_id)
    week_str = request.form.get("week")
    ShiftTemplateEntry.query.filter_by(template_id=template_id).delete()
    db.session.delete(template)
    db.session.commit()
    flash("Template deleted.", "success")
    return redirect(url_for("schedule", week=week_str))


# ── OPEN SHIFTS ──
@app.route("/schedule/open-shift/add", methods=["POST"])
def schedule_add_open_shift():
    restaurant = _get_selected_restaurant()
    data = request.form
    try:
        shift_date = datetime.strptime(data["shift_date"], "%Y-%m-%d").date()
        db.session.add(OpenShift(
            restaurant_id=restaurant.id,
            shift_date=shift_date,
            start_time=data["start_time"],
            end_time=data["end_time"],
            role=data.get("role", ""),
            notes=data.get("notes", ""),
            status='open',
        ))
        db.session.commit()
        flash("Open shift posted.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "danger")
    return redirect(url_for("schedule", week=data.get("week")))


@app.route("/schedule/open-shift/<int:shift_id>/claim", methods=["POST"])
def schedule_claim_open_shift(shift_id):
    shift = OpenShift.query.get_or_404(shift_id)
    emp_id = request.form.get("employee_id")
    week_str = request.form.get("week")
    if emp_id:
        shift.claimed_by_id = int(emp_id)
        shift.claimed_at = datetime.utcnow()
        shift.status = 'claimed'
        restaurant = _get_selected_restaurant()
        db.session.add(Shift(
            restaurant_id=restaurant.id,
            employee_id=int(emp_id),
            shift_date=shift.shift_date,
            start_time=shift.start_time,
            end_time=shift.end_time,
            role=shift.role,
            status='scheduled',
            notes=shift.notes,
        ))
        db.session.commit()
        flash("Open shift claimed and added to schedule.", "success")
    return redirect(url_for("schedule", week=week_str))


@app.route("/schedule/open-shift/<int:shift_id>/delete", methods=["POST"])
def schedule_delete_open_shift(shift_id):
    shift = OpenShift.query.get_or_404(shift_id)
    week_str = request.form.get("week")
    db.session.delete(shift)
    db.session.commit()
    flash("Open shift removed.", "success")
    return redirect(url_for("schedule", week=week_str))


# ── PROJECTED SALES ──
@app.route("/api/schedule/projected-sales", methods=["POST"])
def schedule_save_projected_sales():
    """Save projected sales for a single day. Called via AJAX."""
    restaurant = _get_selected_restaurant()
    data = request.get_json()
    try:
        sale_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        ps = ProjectedSales.query.filter_by(
            restaurant_id=restaurant.id,
            sale_date=sale_date,
        ).first()
        if ps:
            ps.projected_amount = float(data["amount"])
            ps.updated_at = datetime.utcnow()
        else:
            ps = ProjectedSales(
                restaurant_id=restaurant.id,
                sale_date=sale_date,
                projected_amount=float(data["amount"]),
            )
            db.session.add(ps)
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)})


# ── EMPLOYEE AVAILABILITY ──
@app.route("/schedule/availability/add", methods=["POST"])
def schedule_add_availability():
    restaurant = _get_selected_restaurant()
    data = request.form
    try:
        avail = EmployeeAvailability(
            employee_id=int(data["employee_id"]),
            restaurant_id=restaurant.id,
            day_of_week=int(data["day_of_week"]),
            all_day=data.get("all_day") == "1",
            start_time=data.get("start_time") or None,
            end_time=data.get("end_time") or None,
            reason=data.get("reason", ""),
            status='approved',
        )
        db.session.add(avail)
        db.session.commit()
        flash("Availability block added.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error: {e}", "danger")
    return redirect(url_for("schedule", tab="unavailability", week=data.get("week")))


@app.route("/schedule/availability/<int:avail_id>/delete", methods=["POST"])
def schedule_delete_availability(avail_id):
    avail = EmployeeAvailability.query.get_or_404(avail_id)
    week_str = request.form.get("week")
    db.session.delete(avail)
    db.session.commit()
    flash("Availability block removed.", "success")
    return redirect(url_for("schedule", tab="unavailability", week=week_str))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082, debug=False)
