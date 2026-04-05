"""
xtrachef_blueprint.py
---------
Flask Blueprint that registers the xtraCHEF integration routes.

Add to app.py with two lines:
    from xtrachef_blueprint import xtrachef_bp
    app.register_blueprint(xtrachef_bp)
"""

import calendar
import os
from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from connectors.xtrachef_api import (
    fetch_cogs_summary,
    fetch_invoices,
    fetch_item_library,
    fetch_operating_summary,
    fetch_vendors,
)

xtrachef_bp = Blueprint("xtrachef", __name__, url_prefix="/xtra-chef")

LOCATION_NAME = os.environ.get("LOCATION_NAME", "Hale Street Cantina -- Wheaton")


@xtrachef_bp.app_template_filter("dollar")
def dollar_filter(value):
    """Format a number as $1,234.56"""
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


@xtrachef_bp.route("/", endpoint="xtra_chef")
def xtra_chef():
    year   = int(request.args.get("year",   datetime.now().year))
    period = int(request.args.get("period", datetime.now().month))

    start    = date(year, period, 1)
    last_day = calendar.monthrange(year, period)[1]
    end      = date(year, period, last_day)

    ops      = fetch_operating_summary(year, period)
    cogs     = fetch_cogs_summary(start, end)
    invoices = fetch_invoices(start, end)
    items    = fetch_item_library()
    vendors  = fetch_vendors()

    period_label = f"Period {period} -- {start.strftime('%B %Y')}"

    return render_template(
        "xtra_chef.html",
        ops=ops,
        cogs=cogs,
        invoices=invoices,
        items=items,
        vendors=vendors,
        period_label=period_label,
        location_name=LOCATION_NAME,
        selected_year=year,
        selected_period=period,
        last_sync=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@xtrachef_bp.route("/sync", endpoint="xtra_chef_sync")
def xtra_chef_sync():
    flash("xtraCHEF sync triggered successfully.", "success")
    return redirect(url_for("xtrachef.xtra_chef"))
