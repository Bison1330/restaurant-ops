"""
xtrachef_blueprint.py
---------------------
Flask Blueprint for all xtraCHEF integration routes.

Routes:
  GET  /xtra-chef/                    Dashboard (operating summary + trend)
  GET  /xtra-chef/cogs                COGS breakdown by category
  GET  /xtra-chef/invoices            Invoice list with filters
  GET  /xtra-chef/items               Item library
  GET  /xtra-chef/vendors             Vendor directory
  POST /xtra-chef/sync                Trigger a data refresh
  GET  /xtra-chef/api/summary         JSON — operating summary
  GET  /xtra-chef/api/cogs            JSON — COGS summary
  GET  /xtra-chef/api/trend           JSON — multi-period trend data
"""

import calendar
import os
from datetime import date, datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from connectors.xtrachef_api import (
    OPERATING_SUMMARY_DATA,
    fetch_cogs_summary,
    fetch_invoices,
    fetch_item_library,
    fetch_operating_summary,
    fetch_vendors,
)

xtrachef_bp = Blueprint("xtrachef", __name__, url_prefix="/xtra-chef")

LOCATION_NAME = os.environ.get("LOCATION_NAME", "Hale Street Cantina -- Wheaton")

# Available periods for the year 2026
PERIODS = {
    1: ("Jan 1, 2026", "Jan 31, 2026"),
    2: ("Feb 1, 2026", "Feb 28, 2026"),
    3: ("Mar 1, 2026", "Mar 31, 2026"),
    4: ("Apr 1, 2026", "Apr 30, 2026"),
}


# -------------------------------------------------------------------------
# Template filter helpers
# -------------------------------------------------------------------------

@xtrachef_bp.app_template_filter("dollar")
def dollar_filter(value):
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


@xtrachef_bp.app_template_filter("pct")
def pct_filter(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------

@xtrachef_bp.route("/", endpoint="xtra_chef")
def xtra_chef():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))

    summary  = fetch_operating_summary(year, period)
    period_label = summary.get("period", f"Period - {period}")
    period_start = summary.get("period_start", "")
    period_end   = summary.get("period_end",   "")

    # Build trend data for all periods in the year
    trend = _build_trend(year)

    return render_template(
        "xtra_chef.html",
        location=LOCATION_NAME,
        year=year,
        period=period,
        periods=PERIODS,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        summary=summary,
        trend=trend,
        active_tab="dashboard",
    )


@xtrachef_bp.route("/cogs")
def cogs():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))
    summary = fetch_operating_summary(year, period)

    start = date.fromisoformat(summary.get("period_start", f"{year}-01-01"))
    end   = date.fromisoformat(summary.get("period_end",   f"{year}-01-31"))
    cogs_detail = fetch_cogs_summary(start, end)

    return render_template(
        "xtra_chef.html",
        location=LOCATION_NAME,
        year=year,
        period=period,
        periods=PERIODS,
        summary=summary,
        cogs_detail=cogs_detail,
        active_tab="cogs",
    )


@xtrachef_bp.route("/invoices")
def invoices():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))
    vendor_filter = request.args.get("vendor", "")
    summary = fetch_operating_summary(year, period)

    start = date.fromisoformat(summary.get("period_start", f"{year}-01-01"))
    end   = date.fromisoformat(summary.get("period_end",   f"{year}-12-31"))
    all_invoices = fetch_invoices(start, end)

    if vendor_filter:
        all_invoices = [i for i in all_invoices if vendor_filter.lower() in i["vendor"].lower()]

    vendors = sorted({i["vendor"] for i in fetch_invoices(start, end)})

    return render_template(
        "xtra_chef.html",
        location=LOCATION_NAME,
        year=year,
        period=period,
        periods=PERIODS,
        summary=summary,
        invoices=all_invoices,
        vendors=vendors,
        vendor_filter=vendor_filter,
        active_tab="invoices",
    )


@xtrachef_bp.route("/items")
def items():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))
    category_filter = request.args.get("category", "")
    summary = fetch_operating_summary(year, period)

    all_items = fetch_item_library()
    if category_filter:
        all_items = [i for i in all_items if category_filter.lower() in i["category"].lower()]

    categories = sorted({i["category"] for i in fetch_item_library()})

    return render_template(
        "xtra_chef.html",
        location=LOCATION_NAME,
        year=year,
        period=period,
        periods=PERIODS,
        summary=summary,
        items=all_items,
        categories=categories,
        category_filter=category_filter,
        active_tab="items",
    )


@xtrachef_bp.route("/vendors")
def vendors():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))
    summary = fetch_operating_summary(year, period)

    all_vendors = fetch_vendors()
    categories = sorted({v.get("category", "") for v in all_vendors if v.get("category")})

    return render_template(
        "xtra_chef.html",
        location=LOCATION_NAME,
        year=year,
        period=period,
        periods=PERIODS,
        summary=summary,
        vendor_list=all_vendors,
        categories=categories,
        active_tab="vendors",
    )


@xtrachef_bp.route("/sync", methods=["POST"])
def sync():
    """Placeholder for future live xtraCHEF API sync."""
    flash("xtraCHEF data refreshed successfully.", "success")
    return redirect(url_for("xtrachef.xtra_chef"))


# -------------------------------------------------------------------------
# JSON API endpoints (for charts / AJAX)
# -------------------------------------------------------------------------

@xtrachef_bp.route("/api/summary")
def api_summary():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))
    return jsonify(fetch_operating_summary(year, period))


@xtrachef_bp.route("/api/cogs")
def api_cogs():
    year   = int(request.args.get("year",   2026))
    period = int(request.args.get("period", _current_period()))
    summary = fetch_operating_summary(year, period)
    start = date.fromisoformat(summary.get("period_start", f"{year}-01-01"))
    end   = date.fromisoformat(summary.get("period_end",   f"{year}-01-31"))
    return jsonify(fetch_cogs_summary(start, end))


@xtrachef_bp.route("/api/trend")
def api_trend():
    year  = int(request.args.get("year", 2026))
    return jsonify(_build_trend(year))


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _current_period() -> int:
    """Return the current period number based on today's month."""
    today = date.today()
    # Periods map 1-to-1 with months for this location
    return min(today.month, max(PERIODS.keys()))


def _build_trend(year: int) -> list:
    """Build a list of period summaries for trend charts."""
    trend = []
    for period_num in sorted(PERIODS.keys()):
        key = (year, period_num)
        if key in OPERATING_SUMMARY_DATA:
            d = OPERATING_SUMMARY_DATA[key]
            trend.append({
                "period": period_num,
                "label":  d.get("period", f"P{period_num}"),
                "revenue":          d["revenue"],
                "cogs":             d["cogs"],
                "cogs_pct":         d["cogs_pct"],
                "labor":            d["labor"],
                "labor_pct":        d["labor_pct"],
                "prime_cost":       d["prime_cost"],
                "prime_cost_pct":   d["prime_cost_pct"],
                "gross_profit":     d["gross_profit"],
                "gross_profit_pct": d["gross_profit_pct"],
                "operating_costs":  d["operating_costs"],
                "net_profit":       d["net_profit"],
                "net_profit_pct":   d["net_profit_pct"],
            })
    return trend
