# Bison Stockyard Restaurant Operations Platform — HANDOFF

Full rebuild plan to mimic xtraCHEF. Data layer is solid; UI/routes being stripped and rebuilt.

---

## CURRENT STATUS

### What's DONE and KEEPING (data layer — solid)
- All database models and tables
- Toast API connector (employees, timesheets, sales, orders)
- All seeded data:
  - 1,083 inventory items across 3 restaurants
  - 49 storage zones, 48 count sheets (exact xtraCHEF match)
  - 86 invoices imported from xtraCHEF
  - 15 vendors seeded
  - 2,830 recipes per restaurant from xtraCHEF export
- Auth system (email login, owner/manager/employee roles)
- Illinois compliance rules (Food Handler, BASSET, CFPM/DuPage County)
- Gunicorn production server setup
- In-memory TTL cache helper
- SSE streaming for AI assistant

### What's being STRIPPED and REBUILT
- All HTML templates — rebuild to match xtraCHEF layout
- Left navigation — replace with xtraCHEF structure
- All page routes — rewrite to match new structure
- Dashboard — rebuild as xtraCHEF COGS dashboard

### What's being KEPT as-is (Team section)
- Schedule system (fully built, just needs nav update)
- PTO system (Illinois PLAWA compliant)
- Employee management (6-tab detail page)
- Payroll (QuickBooks IIF export)
- Compliance alerts (daily cert check)

---

## xtraCHEF DOCUMENTATION (captured April 13, 2026)

### Inventory Section — FULLY DOCUMENTED
- Inventory Counts: calendar + zone cards with beginning/ending inv + fluctuation
- Count Lists: per-zone count sheets with product/invoice item/prep recipe tabs
- Area Setup: schedule, lock, users per zone
- Manage Waste: date range, item type filter, waste entry form
- Analytics: AvT Analysis + Depleting Inventory (date-gated)
- Reports: 4 tiles — by COGS, by GL, Summary, Variance

### All Other Sections — FULLY DOCUMENTED
- Invoice Automation: Search, List, Reconciliation, Extract Monitor, Map Items, Approvals
- Item Library: master catalog, price history, pack size, UOM, category
- Vendors: list + detail (overview + configuration tabs)
- Recipe: recipes table, variance analysis, pmix mapping, pmix report, config, menus
- Order: purchase orders, order guides, order history
- Data Dashboard: COGS KPIs, invoice tasks, cost ratio
- Analytics: 7 tabs (spending by GL, category weekly, food cost weekly, etc.)
- Operating Summary: revenue/prime cost/gross profit/net profit KPIs + table
- Sync Monitor: calendar with colored chips (sales/payroll/inventory/errors)
- Budget: dashboard + budget entry + import
- Reporting: category tiles → individual report filter forms
- COGS: hierarchical COGS group → category → product with comparison periods

---

## REBUILD PRIORITY ORDER
1. Navigation structure + base template
2. COGS Dashboard (Data > Dashboard)
3. Invoices full workflow (Invoice Automation section)
4. Inventory Counts (full rebuild matching xtraCHEF)
5. Item Library
6. Recipe costing
7. Analytics / Operating Summary
8. Sync Monitor
9. Remaining pages

---

## KEY FILES
- App: /root/restaurant-ops/app.py
- DB models: /root/restaurant-ops/database.py
- Templates: /root/restaurant-ops/templates/
- Base template: /root/restaurant-ops/templates/base.html
- Toast connector: /root/restaurant-ops/connectors/toast_pos.py
- Env vars: /root/restaurant-ops/.env
- Restart: /root/restaurant-ops/restart.sh
- Inventory seed: /root/restaurant-ops/seed_inventory.py

## KEY COMMANDS
```bash
# Start/restart server
bash /root/restaurant-ops/restart.sh

# Check logs
tail -f /root/restaurant-ops/logs/error.log

# Run compliance check manually
cd /root/restaurant-ops && source venv/bin/activate
python -c "from app import app, _check_certification_alerts; _check_certification_alerts()"

# DB record counts
python -c "
from app import app
from database import db, Employee, Recipe, Invoice, Restaurant, InventoryItem
with app.app_context():
    for r in Restaurant.query.all():
        print(f'{r.name}:')
        print(f'  employees: {Employee.query.filter_by(restaurant_id=r.id).count()}')
        print(f'  recipes: {Recipe.query.filter_by(restaurant_id=r.id).count()}')
        print(f'  invoices: {Invoice.query.filter_by(restaurant_id=r.id).count()}')
        print(f'  inventory: {InventoryItem.query.filter_by(restaurant_id=r.id).count()}')
"
```

---

## EXTERNAL INTEGRATIONS
- Toast POS API — credentials in .env
- Anthropic API — ANTHROPIC_API_KEY in .env
- GFS SFTP — NOT YET SET UP
- Fintech API — NOT YET SET UP

## SECURITY NOTE
⚠️ ANTHROPIC_API_KEY and TOAST_CLIENT_SECRET were exposed in chat twice.
Rotate both keys when possible at console.anthropic.com and Toast Developer Portal.
