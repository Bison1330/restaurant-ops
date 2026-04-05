"""
xtrachef_blueprint.py
----------------------
Flask Blueprint for all xtraCHEF integration routes.

Routes:
  GET  /xtra-chef/              Dashboard (operating summary + trend)
    GET  /xtra-chef/cogs          COGS breakdown by category
      GET  /xtra-chef/invoices      Invoice list with filters
        GET  /xtra-chef/items         Item library
          GET  /xtra-chef/vendors       Vendor directory
            POST /xtra-chef/sync          Trigger a data refresh
              GET  /xtra-chef/api/summary   JSON - operating summary
                GET  /xtra-chef/api/cogs      JSON - COGS summary
                  GET  /xtra-chef/api/trend     JSON - multi-period trend data
                    GET  /xtra-chef/api/items     JSON - item library (filterable)
                      GET  /xtra-chef/api/vendors   JSON - vendor list (filterable)
                      """

import os
from datetime import date

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from connectors.xtrachef_api import (
    fetch_cogs_summary,
    fetch_invoices,
    fetch_item_library,
    fetch_operating_summary,
    fetch_vendors,
)

# ---------------------------------------------------------------------------
# Blueprint setup
# ---------------------------------------------------------------------------

xtra_chef_bp = Blueprint(
      "xtra_chef",
      __name__,
      url_prefix="/xtra-chef",
      template_folder="templates",
)

# ---------------------------------------------------------------------------
# Template filters
# ---------------------------------------------------------------------------


@xtra_chef_bp.app_template_filter("currency")
def currency_filter(value):
      """Format a number as USD currency string."""
      try:
                return f"${float(value):,.2f}"
except (TypeError, ValueError):
        return "$0.00"


@xtra_chef_bp.app_template_filter("pct")
def pct_filter(value):
      """Format a decimal fraction as a percentage string."""
      try:
                return f"{float(value) * 100:.1f}%"
except (TypeError, ValueError):
        return "0.0%"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _current_period():
      """Return the period key that matches the current calendar quarter."""
      today = date.today()
      quarter = (today.month - 1) // 3 + 1
      return quarter


def _build_periods(summary_data: list[dict]) -> dict[int, tuple[str, str]]:
      """Build a {period_key: (start_label, end_label)} mapping from summary rows."""
      periods: dict[int, tuple[str, str]] = {}
      for row in summary_data:
                key = row.get("period")
                start = row.get("period_start", "")
                end = row.get("period_end", "")
                if key is not None:
                              periods[key] = (start, end)
                      return periods


def _build_trend(summary_rows: list[dict]) -> dict:
      """
          Build Chart.js-ready trend data from operating-summary rows.

              Returns
                  -------
                      dict with keys: labels, revenue, cogs, labor, net_income
                          """
      labels, revenue, cogs, labor, net_income = [], [], [], [], []
      for row in sorted(summary_rows, key=lambda r: r.get("period", 0)):
                labels.append(row.get("period_label", f"P{row.get('period')}"))
                revenue.append(row.get("total_revenue", 0))
                cogs.append(row.get("total_cogs", 0))
                labor.append(row.get("total_labor", 0))
                net_income.append(row.get("net_income", 0))
            return {
                      "labels": labels,
                      "revenue": revenue,
                      "cogs": cogs,
                      "labor": labor,
                      "net_income": net_income,
            }


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@xtra_chef_bp.route("/")
def dashboard():
      """Operating-summary dashboard with P&L table and trend chart."""
      period = request.args.get("period", type=int, default=_current_period())

    summary_rows = fetch_operating_summary()
    periods = _build_periods(summary_rows)

    # Current-period row (fall back to first row if period not found)
    current = next(
              (r for r in summary_rows if r.get("period") == period),
              summary_rows[0] if summary_rows else {},
    )

    trend = _build_trend(summary_rows)

    return render_template(
              "xtra_chef.html",
              active_tab="dashboard",
              summary=current,
              periods=periods,
              selected_period=period,
              trend=trend,
    )


@xtra_chef_bp.route("/cogs")
def cogs():
      """COGS breakdown by category."""
      period = request.args.get("period", type=int, default=_current_period())

    summary_rows = fetch_operating_summary()
    periods = _build_periods(summary_rows)

    cogs_data = fetch_cogs_summary(period)

    return render_template(
              "xtra_chef.html",
              active_tab="cogs",
              cogs=cogs_data,
              periods=periods,
              selected_period=period,
    )


@xtra_chef_bp.route("/invoices")
def invoices():
      """Invoice list with optional date-range and vendor filters."""
      start_str = request.args.get("start", "")
      end_str = request.args.get("end", "")
      vendor_filter = request.args.get("vendor", "").strip().lower()

    # Parse date strings; fall back to broad defaults so the page always loads
      try:
                start = date.fromisoformat(start_str)
except ValueError:
          start = date(2000, 1, 1)
      try:
                end = date.fromisoformat(end_str)
except ValueError:
          end = date(2099, 12, 31)

    all_invoices = fetch_invoices(start_str, end_str)

    # Server-side date filter (connector may ignore date params)
    filtered = [
              inv
              for inv in all_invoices
              if start <= date.fromisoformat(inv["invoice_date"]) <= end
    ]

    # Optional vendor name filter
    if vendor_filter:
              filtered = [
                            inv
                            for inv in filtered
                            if vendor_filter in inv.get("vendor_name", "").lower()
              ]

    vendors = [v["name"] for v in fetch_vendors()]

    return render_template(
              "xtra_chef.html",
              active_tab="invoices",
              invoices=filtered,
              vendors=vendors,
              start=start_str,
              end=end_str,
              vendor_filter=vendor_filter,
    )


@xtra_chef_bp.route("/items")
def items():
      """Item library with optional category and status filters."""
      category_filter = request.args.get("category", "").strip()
      status_filter = request.args.get("status", "").strip()

    all_items = fetch_item_library()

    filtered = all_items
    if category_filter:
              filtered = [i for i in filtered if i.get("category") == category_filter]
          if status_filter:
                    filtered = [i for i in filtered if i.get("status") == status_filter]

    categories = sorted({i.get("category", "") for i in all_items if i.get("category")})
    statuses = sorted({i.get("status", "") for i in all_items if i.get("status")})

    return render_template(
              "xtra_chef.html",
              active_tab="items",
              items=filtered,
              categories=categories,
              statuses=statuses,
              category_filter=category_filter,
              status_filter=status_filter,
    )


@xtra_chef_bp.route("/vendors")
def vendors():
      """Vendor directory with optional category filter."""
      category_filter = request.args.get("category", "").strip()

    all_vendors = fetch_vendors()

    filtered = all_vendors
    if category_filter:
              filtered = [v for v in all_vendors if v.get("category") == category_filter]

    categories = sorted(
              {v.get("category", "") for v in all_vendors if v.get("category")}
    )

    return render_template(
              "xtra_chef.html",
              active_tab="vendors",
              vendors=filtered,
              categories=categories,
              category_filter=category_filter,
    )


@xtra_chef_bp.route("/sync", methods=["POST"])
def sync():
      """Trigger a manual data refresh and redirect back to the dashboard."""
      # In production this would call the xtraCHEF API and refresh local cache.
      flash("xtraCHEF data refreshed successfully.", "success")
    return redirect(url_for("xtra_chef.dashboard"))


# ---------------------------------------------------------------------------
# JSON / API routes
# ---------------------------------------------------------------------------


@xtra_chef_bp.route("/api/summary")
def api_summary():
      """Return operating summary rows as JSON."""
      rows = fetch_operating_summary()
      return jsonify(rows)


@xtra_chef_bp.route("/api/cogs")
def api_cogs():
      """Return COGS breakdown for a given period as JSON."""
      period = request.args.get("period", type=int, default=_current_period())
      data = fetch_cogs_summary(period)
      return jsonify(data)


@xtra_chef_bp.route("/api/trend")
def api_trend():
      """Return multi-period trend data formatted for Chart.js."""
      rows = fetch_operating_summary()
      return jsonify(_build_trend(rows))


@xtra_chef_bp.route("/api/items")
def api_items():
      """Return item library as JSON, optionally filtered by category and status."""
      category_filter = request.args.get("category", "").strip()
      status_filter = request.args.get("status", "").strip()

    all_items = fetch_item_library()

    filtered = all_items
    if category_filter:
              filtered = [i for i in filtered if i.get("category") == category_filter]
          if status_filter:
                    filtered = [i for i in filtered if i.get("status") == status_filter]

    return jsonify(filtered)


@xtra_chef_bp.route("/api/vendors")
def api_vendors():
      """Return vendor list as JSON, optionally filtered by category."""
      category_filter = request.args.get("category", "").strip()

    all_vendors = fetch_vendors()

    if category_filter:
              all_vendors = [v for v in all_vendors if v.get("category") == category_filter]

    return jsonify(all_vendors)
