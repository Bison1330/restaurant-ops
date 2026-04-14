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

## KEY KNOWN ISSUES
1. **Toast sales sync stale** — "Toast hasn't synced in 159 hours" — sales data not pulling
   - Fix: check Toast API credentials in .env, verify sync job running
   - Impact: Net sales = $0 on COGS page, cost ratio = 0%

2. **COGS category names wrong** — shows "broadline", "Beverage", "alcohol"
   - Fix: map vendor.type field to proper GL categories (Food, Alcohol:Beer, etc.)
   - xtraCHEF GL categories: Food, Alcohol:Beer, Alcohol:Liquor, Alcohol:Wine,
     Restaurant Supplies, NA Beverage

3. **Inventory Counts wrong layout** — shows flat item list instead of
   calendar + zone cards matching xtraCHEF
   - Fix: full rebuild of /inventory with 6-tab structure

4. **No PDF viewer on invoice detail** — imported invoices have no PDF file
   - Fix: implement file upload storage, display PDF for newly uploaded invoices

5. **Net sales = $0 everywhere** — Toast API not returning sales for date ranges
   - Root cause: likely token expiry or wrong endpoint for sales data

---

## EXTERNAL INTEGRATIONS
| Service | Status | Credentials |
|---------|--------|-------------|
| Toast POS API | Connected, sync stale | TOAST_CLIENT_ID, TOAST_CLIENT_SECRET in .env |
| Anthropic API | Working | ANTHROPIC_API_KEY in .env — ROTATE THIS KEY |
| GFS SFTP | Not set up | sftp-gordon.gfs.com |
| Fintech API | Not set up | Southern Glazer's, RNDC alcohol invoices |
| QuickBooks Desktop | Export only (IIF) | No API — file download |

---

## KEY FILES
| File | Purpose |
|------|---------|
| /root/restaurant-ops/app.py | Main Flask app — all routes |
| /root/restaurant-ops/database.py | SQLAlchemy models |
| /root/restaurant-ops/templates/ | All HTML templates |
| /root/restaurant-ops/templates/base.html | Base layout, nav, CSS |
| /root/restaurant-ops/connectors/toast_pos.py | Toast API connector |
| /root/restaurant-ops/.env | All credentials/secrets |
| /root/restaurant-ops/restart.sh | Kill + restart Gunicorn |
| /root/restaurant-ops/seed_inventory.py | Reseed inventory from scratch |
| /root/restaurant-ops/xtrachef_docs/ | xtraCHEF page documentation |

## KEY COMMANDS
```bash
# Restart server
bash /root/restaurant-ops/restart.sh

# Check logs
tail -f /root/restaurant-ops/logs/error.log
tail -f /root/restaurant-ops/logs/access.log

# Check DB counts
cd /root/restaurant-ops && source venv/bin/activate
python -c "
from app import app
from database import db, Employee, Recipe, Invoice, Restaurant, InventoryItem, Vendor
with app.app_context():
    for r in Restaurant.query.all():
        print(f'{r.name}:')
        print(f'  invoices: {Invoice.query.filter_by(restaurant_id=r.id).count()}')
        print(f'  inventory: {InventoryItem.query.filter_by(restaurant_id=r.id).count()}')
        print(f'  recipes: {Recipe.query.filter_by(restaurant_id=r.id).count()}')
        print(f'  vendors: {Vendor.query.filter_by(restaurant_id=r.id).count()}')
"

# Git status
cd /root/restaurant-ops && git log --oneline -5
```

---

## SECURITY NOTES
⚠️ ANTHROPIC_API_KEY exposed in chat — rotate at console.anthropic.com
⚠️ TOAST_CLIENT_SECRET exposed in chat — rotate at Toast Developer Portal
⚠️ All owner passwords are temporary — users should change on first login

---

## SESSION HISTORY SUMMARY
- Session 1-3: Initial build — employees, schedule, PTO, payroll, compliance
- Session 4-5: Toast API integration, invoice import, vendor seeding
- Session 6: Inventory seeding from xtraCHEF (1,083 items, 49 zones, 48 count sheets)
- Session 7: Full xtraCHEF documentation captured via Claude Chrome (all 23 pages)
- Session 8 (current): Nav restructure to match xtraCHEF, COGS page built, Invoices rebuilt
