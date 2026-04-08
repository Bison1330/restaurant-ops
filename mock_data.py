from database import (
    db, Restaurant, Vendor, InventoryItem, Invoice, InvoiceLine,
    PayrollRun, Employee, ItemAlias,
    StorageZone, InventoryItemZone, CountSession, CountEntry,
)
from datetime import datetime, timedelta
import random
import pytz

CENTRAL_TZ = pytz.timezone("US/Central")


def seed_mock_data(app):
    with app.app_context():
        if Restaurant.query.count() > 0:
            return

        # Restaurants
        r1 = Restaurant(name="Hale Street Cantina", location="Wheaton, IL", gfs_account="PENDING", toast_location_id="PENDING")
        r2 = Restaurant(name="Jackson Avenue Pub", location="Naperville, IL", gfs_account="PENDING", toast_location_id="PENDING")
        r3 = Restaurant(name="Main Street Pub", location="Glen Ellyn, IL", gfs_account="PENDING", toast_location_id="PENDING")
        db.session.add_all([r1, r2, r3])
        db.session.flush()

        # Vendors
        v1 = Vendor(name="Gordon Food Service", type="broadline", account_number="GFS-44120", contact_email="orders@gfs.com", payment_terms=14)
        v2 = Vendor(name="Southern Glazer's Wine & Spirits", type="alcohol", account_number="SG-88210", contact_email="orders@southernglazers.com", payment_terms=30)
        v3 = Vendor(name="US Foods", type="broadline", account_number="USF-55430", contact_email="orders@usfoods.com", payment_terms=21)
        v4 = Vendor(name="Sysco", type="broadline", account_number="SYS-77012", contact_email="orders@sysco.com", payment_terms=30)
        db.session.add_all([v1, v2, v3, v4])
        db.session.flush()

        # Inventory Items — 5 per restaurant
        items = [
            # Hale Street Cantina
            InventoryItem(restaurant_id=r1.id, name="Chicken Breast 40lb Case", category="protein", unit="case", par_level=4, current_stock=3, last_cost=89.50, vendor_id=v1.id, vendor_sku="GFS-10441"),
            InventoryItem(restaurant_id=r1.id, name="Ground Beef 80/20 10lb", category="protein", unit="roll", par_level=8, current_stock=5, last_cost=42.75, vendor_id=v1.id, vendor_sku="GFS-20118"),
            InventoryItem(restaurant_id=r1.id, name="Tito's Vodka 1.75L", category="alcohol", unit="case", par_level=3, current_stock=2, last_cost=185.00, vendor_id=v2.id, vendor_sku="SG-TV175"),
            InventoryItem(restaurant_id=r1.id, name="Romaine Lettuce Hearts 24ct", category="produce", unit="case", par_level=6, current_stock=4, last_cost=28.25, vendor_id=v3.id, vendor_sku="USF-RL24"),
            InventoryItem(restaurant_id=r1.id, name="Idaho Potatoes 50lb Bag", category="produce", unit="bag", par_level=3, current_stock=2, last_cost=31.00, vendor_id=v1.id, vendor_sku="GFS-30205"),
            # Jackson Avenue Pub
            InventoryItem(restaurant_id=r2.id, name="Salmon Fillet 10lb Case", category="protein", unit="case", par_level=3, current_stock=2, last_cost=112.00, vendor_id=v3.id, vendor_sku="USF-SF10"),
            InventoryItem(restaurant_id=r2.id, name="Modelo Especial 24pk", category="alcohol", unit="case", par_level=10, current_stock=8, last_cost=32.50, vendor_id=v2.id, vendor_sku="SG-ME24"),
            InventoryItem(restaurant_id=r2.id, name="Fryer Oil 35lb", category="supplies", unit="jug", par_level=4, current_stock=3, last_cost=28.00, vendor_id=v4.id, vendor_sku="SYS-FO35"),
            InventoryItem(restaurant_id=r2.id, name="Roma Tomatoes 25lb Case", category="produce", unit="case", par_level=5, current_stock=3, last_cost=38.50, vendor_id=v3.id, vendor_sku="USF-RT25"),
            InventoryItem(restaurant_id=r2.id, name="Pork Shoulder 20lb", category="protein", unit="case", par_level=3, current_stock=1, last_cost=67.00, vendor_id=v1.id, vendor_sku="GFS-PS20"),
            # Main Street Pub
            InventoryItem(restaurant_id=r3.id, name="Wings 40lb Case", category="protein", unit="case", par_level=6, current_stock=4, last_cost=98.00, vendor_id=v4.id, vendor_sku="SYS-WG40"),
            InventoryItem(restaurant_id=r3.id, name="House Cabernet 3L Box", category="alcohol", unit="box", par_level=5, current_stock=4, last_cost=28.00, vendor_id=v2.id, vendor_sku="SG-HC3L"),
            InventoryItem(restaurant_id=r3.id, name="Burger Buns 48ct", category="bakery", unit="case", par_level=4, current_stock=3, last_cost=18.50, vendor_id=v1.id, vendor_sku="GFS-BB48"),
            InventoryItem(restaurant_id=r3.id, name="Yellow Onions 50lb Bag", category="produce", unit="bag", par_level=2, current_stock=1, last_cost=24.00, vendor_id=v3.id, vendor_sku="USF-YO50"),
            InventoryItem(restaurant_id=r3.id, name="Cheddar Cheese 5lb Block", category="dairy", unit="block", par_level=6, current_stock=5, last_cost=22.00, vendor_id=v4.id, vendor_sku="SYS-CC5"),
        ]
        db.session.add_all(items)
        db.session.flush()

        # Invoices
        today = datetime.now(CENTRAL_TZ).date()

        inv1 = Invoice(restaurant_id=r1.id, vendor_id=v1.id, invoice_number="GFS-2024-008812", invoice_date=today - timedelta(days=5), due_date=today + timedelta(days=9), total_amount=657.25, status="approved", source="gfs")
        inv2 = Invoice(restaurant_id=r1.id, vendor_id=v2.id, invoice_number="SGW-2024-088431", invoice_date=today - timedelta(days=3), due_date=today + timedelta(days=27), total_amount=1482.00, status="pending", source="fintech")
        inv3 = Invoice(restaurant_id=r2.id, vendor_id=v3.id, invoice_number="USF-2024-441290", invoice_date=today - timedelta(days=7), due_date=today + timedelta(days=14), total_amount=586.50, status="paid", source="ocr")
        inv4 = Invoice(restaurant_id=r2.id, vendor_id=v1.id, invoice_number="GFS-2024-008920", invoice_date=today - timedelta(days=2), due_date=today + timedelta(days=12), total_amount=498.75, status="pending", source="gfs")
        inv5 = Invoice(restaurant_id=r3.id, vendor_id=v4.id, invoice_number="SYS-2024-334102", invoice_date=today - timedelta(days=10), due_date=today + timedelta(days=20), total_amount=742.00, status="approved", source="gfs")
        inv6 = Invoice(restaurant_id=r3.id, vendor_id=v2.id, invoice_number="SGW-2024-088590", invoice_date=today - timedelta(days=1), due_date=today + timedelta(days=29), total_amount=560.00, status="pending", source="fintech")
        db.session.add_all([inv1, inv2, inv3, inv4, inv5, inv6])
        db.session.flush()

        # Invoice Lines
        invoice_lines = [
            # inv1 - GFS to Hale Street
            InvoiceLine(invoice_id=inv1.id, description="Chicken Breast 40lb Case", vendor_sku="GFS-10441", quantity=3, unit="case", unit_cost=89.50, line_total=268.50),
            InvoiceLine(invoice_id=inv1.id, description="Ground Beef 80/20 10lb Roll", vendor_sku="GFS-20118", quantity=5, unit="roll", unit_cost=42.75, line_total=213.75),
            InvoiceLine(invoice_id=inv1.id, description="Idaho Potatoes 50lb Bag", vendor_sku="GFS-30205", quantity=2, unit="bag", unit_cost=31.00, line_total=62.00),
            InvoiceLine(invoice_id=inv1.id, description="Romaine Lettuce Hearts 24ct", vendor_sku="GFS-40087", quantity=4, unit="case", unit_cost=28.25, line_total=113.00),
            # inv2 - Southern Glazer's to Hale Street
            InvoiceLine(invoice_id=inv2.id, description="Tito's Vodka 1.75L", vendor_sku="SG-TV175", quantity=6, unit="case", unit_cost=185.00, line_total=1110.00),
            InvoiceLine(invoice_id=inv2.id, description="Modelo Especial 24pk", vendor_sku="SG-ME24", quantity=8, unit="case", unit_cost=32.50, line_total=260.00),
            InvoiceLine(invoice_id=inv2.id, description="House Cabernet 3L Box", vendor_sku="SG-HC3L", quantity=4, unit="box", unit_cost=28.00, line_total=112.00),
            # inv3 - US Foods to Jackson Avenue
            InvoiceLine(invoice_id=inv3.id, description="Roma Tomatoes 25lb Case", vendor_sku="USF-RT25", quantity=3, unit="case", unit_cost=38.50, line_total=115.50),
            InvoiceLine(invoice_id=inv3.id, description="Yellow Onions 50lb Bag", vendor_sku="USF-YO50", quantity=2, unit="bag", unit_cost=24.00, line_total=48.00),
            InvoiceLine(invoice_id=inv3.id, description="Salmon Fillet 10lb Case", vendor_sku="USF-SF10", quantity=3, unit="case", unit_cost=112.00, line_total=336.00),
            InvoiceLine(invoice_id=inv3.id, description="Fresh Basil 1lb Clamshell", vendor_sku="USF-FB1", quantity=6, unit="each", unit_cost=14.50, line_total=87.00),
            # inv4 - GFS to Jackson Avenue
            InvoiceLine(invoice_id=inv4.id, description="Pork Shoulder 20lb", vendor_sku="GFS-PS20", quantity=4, unit="case", unit_cost=67.00, line_total=268.00),
            InvoiceLine(invoice_id=inv4.id, description="Fryer Oil 35lb", vendor_sku="SYS-FO35", quantity=3, unit="jug", unit_cost=28.00, line_total=84.00),
            InvoiceLine(invoice_id=inv4.id, description="Burger Buns 48ct", vendor_sku="GFS-BB48", quantity=5, unit="case", unit_cost=18.50, line_total=92.50),
            InvoiceLine(invoice_id=inv4.id, description="Romaine Lettuce Hearts 24ct", vendor_sku="GFS-40087", quantity=2, unit="case", unit_cost=27.13, line_total=54.25),
            # inv5 - Sysco to Main Street
            InvoiceLine(invoice_id=inv5.id, description="Wings 40lb Case", vendor_sku="SYS-WG40", quantity=5, unit="case", unit_cost=98.00, line_total=490.00),
            InvoiceLine(invoice_id=inv5.id, description="Cheddar Cheese 5lb Block", vendor_sku="SYS-CC5", quantity=6, unit="block", unit_cost=22.00, line_total=132.00),
            InvoiceLine(invoice_id=inv5.id, description="Fryer Oil 35lb", vendor_sku="SYS-FO35", quantity=2, unit="jug", unit_cost=28.00, line_total=56.00),
            InvoiceLine(invoice_id=inv5.id, description="To-Go Containers 200ct", vendor_sku="SYS-TG200", quantity=4, unit="case", unit_cost=16.00, line_total=64.00),
            # inv6 - Southern Glazer's to Main Street
            InvoiceLine(invoice_id=inv6.id, description="House Cabernet 3L Box", vendor_sku="SG-HC3L", quantity=8, unit="box", unit_cost=28.00, line_total=224.00),
            InvoiceLine(invoice_id=inv6.id, description="Modelo Especial 24pk", vendor_sku="SG-ME24", quantity=6, unit="case", unit_cost=32.50, line_total=195.00),
            InvoiceLine(invoice_id=inv6.id, description="Tito's Vodka 1.75L", vendor_sku="SG-TV175", quantity=1, unit="case", unit_cost=141.00, line_total=141.00),
        ]
        db.session.add_all(invoice_lines)

        # Employees
        employees = [
            # Hale Street Cantina
            Employee(restaurant_id=r1.id, toast_employee_id="HSC-001", first_name="Maria", last_name="Gonzalez", role="General Manager", pay_rate=62000, pay_type="salary", filing_status="married", allowances=3),
            Employee(restaurant_id=r1.id, toast_employee_id="HSC-002", first_name="James", last_name="Chen", role="Line Cook", pay_rate=18.50, pay_type="hourly", filing_status="single", allowances=1),
            Employee(restaurant_id=r1.id, toast_employee_id="HSC-003", first_name="Ashley", last_name="Williams", role="Bartender", pay_rate=14.00, pay_type="hourly", filing_status="single", allowances=1),
            Employee(restaurant_id=r1.id, toast_employee_id="HSC-004", first_name="Derek", last_name="Johnson", role="Server", pay_rate=9.00, pay_type="hourly", filing_status="single", allowances=0),
            # Jackson Avenue Pub
            Employee(restaurant_id=r2.id, toast_employee_id="JAP-001", first_name="Kevin", last_name="O'Brien", role="General Manager", pay_rate=58000, pay_type="salary", filing_status="married", allowances=2),
            Employee(restaurant_id=r2.id, toast_employee_id="JAP-002", first_name="Rosa", last_name="Martinez", role="Sous Chef", pay_rate=21.00, pay_type="hourly", filing_status="single", allowances=1),
            Employee(restaurant_id=r2.id, toast_employee_id="JAP-003", first_name="Tyler", last_name="Brooks", role="Server", pay_rate=9.00, pay_type="hourly", filing_status="single", allowances=0),
            # Main Street Pub
            Employee(restaurant_id=r3.id, toast_employee_id="MSP-001", first_name="Sarah", last_name="Mitchell", role="General Manager", pay_rate=60000, pay_type="salary", filing_status="married", allowances=2),
            Employee(restaurant_id=r3.id, toast_employee_id="MSP-002", first_name="Andre", last_name="Davis", role="Line Cook", pay_rate=17.50, pay_type="hourly", filing_status="single", allowances=1),
            Employee(restaurant_id=r3.id, toast_employee_id="MSP-003", first_name="Megan", last_name="Taylor", role="Bartender", pay_rate=13.50, pay_type="hourly", filing_status="single", allowances=0),
        ]
        db.session.add_all(employees)

        # Payroll Runs for Hale Street Cantina
        pr1 = PayrollRun(restaurant_id=r1.id, period_start=today - timedelta(days=14), period_end=today - timedelta(days=1), status="approved", total_gross=8450.00)
        pr2 = PayrollRun(restaurant_id=r1.id, period_start=today - timedelta(days=28), period_end=today - timedelta(days=15), status="paid", total_gross=7980.00, qb_exported=True)
        db.session.add_all([pr1, pr2])

        # Seed confirmed aliases for existing inventory items
        # This means future imports from these sources will auto-match
        alias_data = []
        for item in items:
            if item.vendor_sku:
                # Alias by vendor SKU
                alias_data.append(ItemAlias(
                    inventory_item_id=item.id,
                    source="gfs" if "GFS" in (item.vendor_sku or "") else "fintech" if "SG" in (item.vendor_sku or "") else "manual",
                    external_sku=item.vendor_sku,
                    external_name=item.name,
                    confidence=1.0,
                    confirmed=True,
                ))
        db.session.add_all(alias_data)

        # Storage Zones for all restaurants
        zone_names = [
            ("Walk-in Cooler", 1),
            ("Freezer", 2),
            ("Dry Storage", 3),
            ("Bar", 4),
            ("Line", 5),
        ]
        all_zones = {}
        for rest in [r1, r2, r3]:
            rest_zones = []
            for zname, zorder in zone_names:
                z = StorageZone(restaurant_id=rest.id, name=zname, sort_order=zorder)
                db.session.add(z)
                rest_zones.append(z)
            db.session.flush()
            all_zones[rest.id] = {z.name: z for z in rest_zones}

        # Assign items to zones (Hale Street)
        zone_map_r1 = {
            "Chicken Breast 40lb Case": "Walk-in Cooler",
            "Ground Beef 80/20 10lb": "Walk-in Cooler",
            "Tito's Vodka 1.75L": "Bar",
            "Romaine Lettuce Hearts 24ct": "Walk-in Cooler",
            "Idaho Potatoes 50lb Bag": "Dry Storage",
        }
        for item in items[:5]:
            zone_name = zone_map_r1.get(item.name)
            if zone_name and zone_name in all_zones[r1.id]:
                db.session.add(InventoryItemZone(
                    inventory_item_id=item.id,
                    storage_zone_id=all_zones[r1.id][zone_name].id,
                    sort_order=0,
                ))

        # Assign items to zones (Jackson Avenue)
        zone_map_r2 = {
            "Salmon Fillet 10lb Case": "Walk-in Cooler",
            "Modelo Especial 24pk": "Bar",
            "Fryer Oil 35lb": "Dry Storage",
            "Roma Tomatoes 25lb Case": "Walk-in Cooler",
            "Pork Shoulder 20lb": "Freezer",
        }
        for item in items[5:10]:
            zone_name = zone_map_r2.get(item.name)
            if zone_name and zone_name in all_zones[r2.id]:
                db.session.add(InventoryItemZone(
                    inventory_item_id=item.id,
                    storage_zone_id=all_zones[r2.id][zone_name].id,
                    sort_order=0,
                ))

        # Assign items to zones (Main Street)
        zone_map_r3 = {
            "Wings 40lb Case": "Freezer",
            "House Cabernet 3L Box": "Bar",
            "Burger Buns 48ct": "Dry Storage",
            "Yellow Onions 50lb Bag": "Dry Storage",
            "Cheddar Cheese 5lb Block": "Walk-in Cooler",
        }
        for item in items[10:15]:
            zone_name = zone_map_r3.get(item.name)
            if zone_name and zone_name in all_zones[r3.id]:
                db.session.add(InventoryItemZone(
                    inventory_item_id=item.id,
                    storage_zone_id=all_zones[r3.id][zone_name].id,
                    sort_order=0,
                ))

        db.session.flush()

        # Sample completed count for Hale Street (last week)
        last_week = today - timedelta(days=7)
        count1 = CountSession(
            restaurant_id=r1.id,
            count_date=last_week,
            counted_by="Maria Gonzalez",
            status="submitted",
            submitted_at=datetime(last_week.year, last_week.month, last_week.day, 14, 30),
            total_value=0,
            total_variance_value=0,
        )
        db.session.add(count1)
        db.session.flush()

        # Count entries with realistic variances
        count_data_r1 = [
            # (item_index, actual, expected, notes)
            (0, 2.5, 3.0, ""),                         # Chicken - slight short
            (1, 4.0, 5.0, "Possible over-portioning"),  # Ground Beef - short
            (2, 2.0, 2.0, ""),                          # Vodka - exact
            (3, 3.0, 4.0, "Wilted, tossed 1 case"),    # Romaine - waste
            (4, 2.0, 2.0, ""),                          # Potatoes - exact
        ]
        total_val = 0
        total_var = 0
        for idx, actual, expected, notes in count_data_r1:
            item = items[idx]
            zone_name = zone_map_r1.get(item.name)
            zone_id = all_zones[r1.id][zone_name].id if zone_name and zone_name in all_zones[r1.id] else None
            entry = CountEntry(
                session_id=count1.id,
                inventory_item_id=item.id,
                storage_zone_id=zone_id,
                actual_count=actual,
                expected_count=expected,
                unit_cost=item.last_cost,
                notes=notes,
            )
            db.session.add(entry)
            total_val += actual * item.last_cost
            total_var += (actual - expected) * item.last_cost

        count1.total_value = round(total_val, 2)
        count1.total_variance_value = round(total_var, 2)

        db.session.commit()
