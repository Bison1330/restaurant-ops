import os
import uuid
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    session, send_file, jsonify, make_response
)
from werkzeug.utils import secure_filename

from database import (
    db, Restaurant, Vendor, InventoryItem, Invoice, InvoiceLine,
    PayrollRun, Employee, Recipe, RecipeIngredient,
    ItemAlias, PriceHistory, UnmatchedItem,
    StorageZone, InventoryItemZone, CountSession, CountEntry,
)
from mock_data import seed_mock_data
from connectors.gfs_sftp import fetch_gfs_invoices
from connectors.fintech_api import fetch_fintech_invoices
from connectors.invoice_ocr import extract_invoice_from_image
from connectors.email_ingestion import poll_invoice_email
from connectors.qb_export import export_invoices_iif, export_payroll_iif
from connectors.toast_pos import fetch_toast_menu
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

with app.app_context():
    db.create_all()
    seed_mock_data(app)


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _get_selected_restaurant():
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
            inv_date = datetime.now().date()
    elif not inv_date:
        inv_date = datetime.now().date()

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
    return dict(restaurants=restaurants, selected_restaurant=selected, unmatched_count=unmatched_count)


@app.route("/")
def dashboard():
    r = _get_selected_restaurant()
    if not r:
        return render_template("dashboard.html", stats={}, recent_invoices=[])

    now = datetime.now().date()
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

    stats = {
        "pending_count": pending_count,
        "overdue_count": overdue_count,
        "low_stock_count": low_stock_count,
        "thirty_day_spend": round(spend_result, 2),
    }
    return render_template("dashboard.html", stats=stats, recent_invoices=recent_invoices)


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
    count_date = datetime.strptime(request.form.get("count_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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


@app.route("/matching")
def matching():
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
    return render_template("matching.html",
        pending=pending,
        resolved_count=resolved_count,
        alias_count=alias_count,
        inventory_items=inventory_items,
    )


@app.route("/matching/confirm", methods=["POST"])
def matching_confirm():
    unmatched_id = int(request.form.get("unmatched_id", 0))
    inventory_item_id = int(request.form.get("inventory_item_id", 0))
    if confirm_match(unmatched_id, inventory_item_id):
        flash("Match confirmed and alias saved.", "success")
    else:
        flash("Could not confirm match.", "error")
    return redirect(url_for("matching"))


@app.route("/matching/create-new", methods=["POST"])
def matching_create_new():
    unmatched_id = int(request.form.get("unmatched_id", 0))
    category = request.form.get("category", "uncategorized")
    item = create_new_from_unmatched(unmatched_id, category)
    if item:
        flash(f"Created new inventory item '{item.name}' and saved alias.", "success")
    else:
        flash("Could not create item.", "error")
    return redirect(url_for("matching"))


@app.route("/matching/dismiss", methods=["POST"])
def matching_dismiss():
    unmatched_id = int(request.form.get("unmatched_id", 0))
    dismiss_unmatched(unmatched_id)
    flash("Item dismissed.", "success")
    return redirect(url_for("matching"))


@app.route("/matching/relink-recipes", methods=["POST"])
def relink_recipes():
    r = _get_selected_restaurant()
    if not r:
        flash("No restaurant selected.", "error")
        return redirect(url_for("matching"))
    count = auto_link_recipe_ingredients(r.id)
    flash(f"Re-linked {count} recipe ingredient(s) to inventory.", "success")
    return redirect(url_for("matching"))


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
    now = datetime.now().date()
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
    thirty_days_ago = datetime.now().date() - timedelta(days=30)
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082, debug=True)
