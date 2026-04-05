# RestaurantOps — xtraCHEF by Toast Clone

A fully functional restaurant operations platform built to mirror the core capabilities of xtraCHEF by Toast. Built with Flask, SQLAlchemy, and Python — deployable to DigitalOcean via GitHub Actions.

## Features

- **Invoice Automation** — Upload, OCR, and process vendor invoices; supports GFS SFTP, FinTech Hospitality API, email ingestion, and image uploads
- **COGS Tracking** — Track cost of goods sold by category (Food, Beer, Liquor, NA Beverage) with trend analysis
- **Inventory Management** — Multi-zone inventory counts, variance reports, and par-level alerts
- **Recipe Costing** — Build recipes with ingredient-level cost calculations and margin tracking
- **Vendor Management** — Manage vendors, track price history, and flag price anomalies
- **Item Matching** — AI-assisted fuzzy matching of invoice line items to inventory master
- **Toast POS Integration** — Sync menu items and sales data from Toast via the Toast API
- **QuickBooks Export** — Export invoices and payroll to IIF format for QuickBooks import
- **Payroll and Labor** — Employee records, payroll runs, and labor cost reporting
- **Operating Summary** — P and L with Revenue, COGS, Labor (Prime Cost), and Net Profit

## Tech Stack

- **Backend:** Python 3.11, Flask 3.x, SQLAlchemy, Gunicorn
- **Database:** PostgreSQL (via psycopg2)
- **Auth:** Flask-Login + TOTP 2FA (pyotp)
- **OCR:** Tesseract + Pillow + OpenAI GPT-4o
- **Frontend:** Jinja2 templates, Bootstrap 5
- **CI/CD:** GitHub Actions to DigitalOcean

## Deployment

Set these GitHub repository secrets for auto-deploy:

- DROPLET_HOST — your DigitalOcean droplet IP
- DROPLET_USER — SSH username
- DROPLET_SSH_KEY — your private SSH key

## Location

Hale Street Cantina — Wheaton, 109 N Hale St, Wheaton, IL 60187
