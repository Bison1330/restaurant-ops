# Bison Stockyard Restaurant Operations Platform — HANDOFF

## 1. Project Overview

- **Platform name:** Bison Stockyard Restaurant Operations Platform
- **Server:** 45.55.59.114:8082
- **GitHub:** https://github.com/Bison1330/restaurant-ops
- **Stack:** Flask, SQLAlchemy, SQLite, Python 3.12, DigitalOcean

## 2. Restaurants

| ID | Name | Location | Toast Location GUID |
|----|------|----------|---------------------|
| 1 | Hale Street Cantina | Wheaton, IL | `958f1466-d8c9-4b36-b0e2-094d5c0c20e7` |
| 2 | Jackson Avenue Pub | Naperville, IL | `67a38de0-8a97-4c5e-86b9-21deabe116a0` |
| 3 | Main Street Pub | Glen Ellyn, IL | `0c7ca132-75d4-42a7-89ee-f990972819ef` |

## 3. What's Built — Routes (`app.py`)

### Dashboard / Sales
- `GET /` — Main dashboard with sales summary, alerts, top-cost items
- `GET /api/sales-summary` — JSON sales summary for a date range
- `GET /api/dashboard-data` — Aggregated dashboard JSON
- `GET /api/vendor-spend` — Vendor spend rollup
- `GET /set-restaurant/<id>` — Switch active restaurant in session

### PMIX (Product Mix / Menu Sales)
- `GET /api/pmix` — JSON PMIX data
- `GET /pmix` — PMIX page with recipe cost overlay

### AI Assistant (Anthropic Claude)
- `POST /api/assistant` — Conversational assistant endpoint with tool use
- `POST /api/assistant/execute` — Execute mutating assistant tool calls
- `GET|POST /api/assistant/check` — Background alert/anomaly check

### Invoices
- `GET /invoices` — Invoice list
- `POST /invoices/<id>/approve` — Approve invoice
- `POST /invoices/<id>/pay` — Mark invoice paid
- `GET /invoices/import` and `/invoices/upload` — Import landing page
- `POST /invoices/import/gfs` — GFS SFTP import
- `POST /invoices/import/fintech` — Fintech API import
- `POST /invoices/import/upload` — File upload import (PDF/CSV)
- `POST /invoices/import/email` — Email inbox import
- `GET /invoices/export/qb` — Export approved invoices to QuickBooks IIF

### Inventory
- `GET /inventory` — Inventory list
- `POST /inventory/<id>/update` — Update an inventory item

### Counts (Physical Inventory)
- `GET /counts` — Count session list
- `GET /counts/setup` — Storage zone & item assignment setup
- `POST /counts/setup/add-zone` — Add storage zone
- `POST /counts/setup/rename-zone/<id>` — Rename zone
- `POST /counts/setup/delete-zone/<id>` — Delete zone
- `POST /counts/setup/reorder-zones` — Reorder zones
- `POST /counts/setup/assign-items` — Assign items to zones
- `POST /counts/new` — Start a new count session
- `GET /counts/<id>` — Count sheet
- `POST /counts/<id>/save` — Save count progress
- `POST /counts/<id>/submit` — Submit count
- `GET /counts/<id>/report` — Variance report

### Payroll
- `GET /payroll` — Payroll runs list
- `GET /payroll/export/<id>` — Export payroll run to QuickBooks IIF

### Vendors / Employees
- `GET /vendors` — Vendor list
- `GET /employees` — Employee list (Toast-synced)
- `POST /employees/<emp_id>/manual-rate` — Override Toast pay rate

### Recipes
- `GET /recipes` — Recipe list with food cost %
- `GET /recipes/<id>` — Recipe detail
- `POST /recipes/create` — Create recipe
- `POST /recipes/<id>/edit` — Edit recipe
- `POST /recipes/<id>/delete` — Delete recipe
- `POST /recipes/import-csv` — Import recipes from CSV
- `POST /recipes/sync-toast` — Pull menu items from Toast
- `POST /api/recipe-cost` — Calculate recipe cost

### Item Mapping (Cross-system ID matching)
- `GET /mapping` — Unmatched items review
- `POST /mapping/confirm` — Confirm a suggested match
- `POST /mapping/create-new` — Create new inventory item from unmatched
- `POST /mapping/dismiss` — Dismiss unmatched item
- `POST /mapping/relink-recipes` — Re-link recipes after mapping
- `GET /matching` and related — Legacy redirects to `/mapping`

### Alerts
- `GET /alerts` — Alert list
- `POST /alerts/<id>/resolve` — Resolve alert
- `POST /alerts/run` — Manually trigger alert scan
- `GET /api/price-history/<item_id>` — Item price history JSON

## 4. Database Models (`database.py`)

- **Restaurant** — id, name, location, gfs_account, toast_location_id, toast_client_id, toast_client_secret, last_toast_sync
- **Vendor** — id, name, type, account_number, contact_email, payment_terms
- **InventoryItem** — restaurant_id, name, category, unit, par_level, current_stock, last_cost, yield_units, vendor_id, vendor_sku, toast_guid, gfs_sku, fintech_code, xtra_chef_id
- **Invoice** — restaurant_id, vendor_id, invoice_number, invoice_date, due_date, total_amount, status, source, qb_exported
- **InvoiceLine** — invoice_id, description, vendor_sku, quantity, unit, unit_cost, line_total, inventory_item_id
- **PayrollRun** — restaurant_id, period_start, period_end, status, total_gross, qb_exported
- **Employee** — restaurant_id, toast_employee_id, first_name, last_name, role, pay_rate, manual_pay_rate, pay_type, filing_status
- **Recipe** — restaurant_id, name, category, subcategory, menu_price, food_cost, food_cost_pct, gross_margin, portion_size, toast_recipe_id, xtra_chef_id, toast_guid, pos_id
- **RecipeIngredient** — recipe_id, inventory_item_id, name, quantity, unit, unit_cost, yield_percent
- **ItemAlias** — inventory_item_id, source, external_sku, external_name, confidence, confirmed
- **PriceHistory** — inventory_item_id, old_cost, new_cost, change_percent, source, invoice_id
- **UnmatchedItem** — restaurant_id, source, external_sku, external_name, unit, last_seen_cost, suggested_item_id, status
- **StorageZone** — restaurant_id, name, sort_order
- **InventoryItemZone** — inventory_item_id, storage_zone_id, sort_order
- **CountSession** — restaurant_id, count_date, counted_by, status, total_value, total_variance_value
- **CountEntry** — session_id, inventory_item_id, storage_zone_id, actual_count, expected_count, unit_cost
- **Alert** — restaurant_id, alert_type, severity, message, resolved
- **ItemMap** — internal_name, toast_guid, xtra_chef_id, gfs_sku, fintech_code, category, restaurant_id
- **MenuItemSale** — restaurant_id, sale_date, toast_item_guid, item_name, category, quantity, unit_price, total_revenue, recipe_id

## 5. External Integrations

| Integration | Status | Notes |
|---|---|---|
| Toast API (Hale Street Cantina) | **LIVE** | OAuth client credentials stored per-restaurant |
| Toast API (Jackson Avenue Pub) | **LIVE** | OAuth client credentials stored per-restaurant |
| Toast API (Main Street Pub) | **LIVE** | OAuth client credentials stored per-restaurant |
| GFS SFTP | **PENDING CREDENTIALS** | Connector built, awaiting SFTP login |
| Fintech API | **PENDING CREDENTIALS** | Connector built, awaiting API access |
| Anthropic Claude API | **LIVE** | Powers `/api/assistant` with tool use |
| QuickBooks Desktop IIF export | **LIVE** | `/invoices/export/qb` and `/payroll/export/<id>` |
| Email invoice ingestion | **PENDING GMAIL SETUP** | Endpoint exists at `/invoices/import/email` |

## 6. Current Data

### Recipes per restaurant
- Hale Street Cantina: **620**
- Jackson Avenue Pub: **1,061**
- Main Street Pub: **1,149**

### Employees per restaurant (Toast-synced)
- Hale Street Cantina: **55**
- Jackson Avenue Pub: **52**
- Main Street Pub: **68**

### Invoices
- Total: **6**
- Pending: 3
- Approved: 2
- Paid: 1

### Alerts
- Total: **26**
- Unresolved: **19**

## 7. What Needs to Be Built Next (priority order)

1. **Schedule / shift management** — build/edit shifts, publish, sync to Toast
2. **Waste log** — track spoilage and comps against recipes
3. **Reports page** — P&L, food cost %, labor %, vendor spend
4. **User management & login** — authentication, roles, per-restaurant access
5. **Item library import from xtraCHEF** — bulk import inventory items with vendor SKUs
6. **Jackson and Main Street recipe JSON for ingredients** — Hale Street has ingredient detail; the other two need ingredient-level recipe data
7. **Mobile optimization** — count sheets and dashboards on phone
8. **Training mode for new employees** — sandboxed walkthrough of the platform

## 8. Credentials Needed

- **GFS SFTP** — email `IT.EDI.US.Customer@gfs.com` with the GFS account numbers for all three restaurants to request SFTP credentials
- **Fintech API** — request API credentials from Fintech support
- **Gmail inbox** — set up a dedicated Gmail account and OAuth/app password for the email invoice ingestion endpoint

## 9. Known Issues / Tech Debt

- **Single-tenant SQLite** at `data/restaurant_ops.db` — fine for current load but will need Postgres before multi-user concurrent writes
- **No authentication** — all routes are open; restaurant context lives only in the Flask session via `/set-restaurant/<id>`
- **Jackson Avenue Pub and Main Street Pub recipes lack ingredient breakdowns** — recipe rows exist but most have empty `RecipeIngredient` data, so food cost % is unreliable for those two locations
- **Item mapping is partially manual** — `/mapping` works but the auto-match confidence threshold catches only obvious matches; long tail still needs human review
- **Legacy `/matching/*` endpoints** — kept as redirects to `/mapping/*`; remove once no callers remain
- **`MenuItemSale.variance_percent` references `expected_count`** which doesn't exist on that model — dead/buggy property
- **No test suite** — all verification is manual
- **Multiple ad-hoc migration scripts** in repo root (`migrate_alerts.py`, `migrate_id_mapping.py`, `migrate_pmix.py`, `migrate_toast_credentials.py`) — should be consolidated into Alembic
- **Toast credentials stored in plaintext** in the `restaurants` table — encrypt at rest
- **Scheduler runs in-process** (`_start_scheduler`) — no persistence across restarts; consider APScheduler with a job store or external cron

## 10. Restart Command

```bash
/root/restaurant-ops/restart.sh
```
