import requests
import os
from datetime import datetime
import pytz

CENTRAL_TZ = pytz.timezone("US/Central")
FINTECH_API_KEY = os.environ.get("FINTECH_API_KEY")


def fetch_fintech_invoices():
    if not FINTECH_API_KEY:
        return _mock_invoices()

    headers = {"Authorization": f"Bearer {FINTECH_API_KEY}"}
    response = requests.get("https://api.fintech.com/v1/invoices", headers=headers)
    response.raise_for_status()
    data = response.json()

    invoices = []
    for inv in data.get("invoices", []):
        lines = []
        for line in inv.get("lines", []):
            lines.append({
                "description": line.get("description", ""),
                "vendor_sku": line.get("vendor_sku", ""),
                "quantity": float(line.get("quantity", 0)),
                "unit": line.get("unit", ""),
                "unit_cost": float(line.get("unit_cost", 0)),
                "line_total": float(line.get("line_total", 0)),
            })
        invoices.append({
            "invoice_number": inv.get("invoice_number", ""),
            "invoice_date": inv.get("invoice_date", ""),
            "total_amount": float(inv.get("total_amount", 0)),
            "source": "fintech",
            "vendor_name": inv.get("vendor_name", ""),
            "lines": lines,
        })

    return invoices


def _mock_invoices():
    today = datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d")
    lines = [
        {
            "description": "Tito's Vodka 1.75L",
            "vendor_sku": "SG-TV175",
            "quantity": 6.0,
            "unit": "case",
            "unit_cost": 185.00,
            "line_total": 1110.00,
        },
        {
            "description": "Modelo Especial 24pk",
            "vendor_sku": "SG-ME24",
            "quantity": 8.0,
            "unit": "case",
            "unit_cost": 32.50,
            "line_total": 260.00,
        },
        {
            "description": "House Cabernet 3L Box",
            "vendor_sku": "SG-HC3L",
            "quantity": 4.0,
            "unit": "box",
            "unit_cost": 28.00,
            "line_total": 112.00,
        },
    ]
    return [
        {
            "invoice_number": "SGW-2024-088431",
            "invoice_date": today,
            "total_amount": sum(l["line_total"] for l in lines),
            "source": "fintech",
            "vendor_name": "Southern Glazer's Wine & Spirits",
            "lines": lines,
        }
    ]
