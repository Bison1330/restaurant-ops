"""
        return _mock_vendors()


# ── Mock Data (fallback when no API credentials configured) ───────────────────
# Based on real data observed from Hale Street Cantina - Wheaton xtraCHEF account

def _mock_cogs_summary(start_date: date, end_date: date) -> dict:
    return {
        "period_start": start_date.isoformat(),
        "period_end":   end_date.isoformat(),
        "cogs":         19891.00,
        "net_sales":    76165.00,
        "cost_ratio":   0.26,
        "groups": [
            {"name": "Food",   "cogs": 19891, "net_sales": 40184, "ratio": 0.4950},
            {"name": "Beer",   "cogs":     0, "net_sales": 11731, "ratio": 0.0},
            {"name": "Liquor", "cogs":     0, "net_sales": 20866, "ratio": 0.0},
            {"name": "NA Bev", "cogs":     0, "net_sales":  3384, "ratio": 0.0},
        ],
    }


def _mock_operating_summary(year: int, period: int) -> dict:
    """Real data from xtraCHEF Operating Summary — Hale Street Cantina, Apr 2026."""
    return {
        "year":             year,
        "period":           period,
        "period_start":     f"{year}-{period:02d}-01",
        "period_end":       f"{year}-{period:02d}-30",
        "revenue":          7190.24,
        "cogs":             3137.85,
        "labor":            0.00,
        "prime_cost":       3137.85,
        "prime_cost_pct":   0.4364,
        "gross_profit":     4052.39,
        "gross_profit_pct": 0.5636,
        "operating_costs":  279.00,
        "net_profit":       3773.39,
        "net_profit_pct":   0.5247,
    }


def _mock_invoices() -> list:
    return [
        {
            "vendor_name":    "Gordon Food Service",
            "invoice_number": "GFS-2026-0312",
            "invoice_date":   "2026-03-12",
            "total_amount":   4231.50,
            "status":         "complete",
            "lines": [
                {"description": "Chicken Breast 40lb", "quantity": 4, "unit": "case",  "unit_price": 89.99,  "total": 359.96},
                {"description": "Romaine Hearts",      "quantity": 6, "unit": "case",  "unit_price": 24.50,  "total": 147.00},
                {"description": "Olive Oil 1gal",      "quantity": 3, "unit": "each",  "unit_price": 34.75,  "total": 104.25},
                {"description": "Pasta Rigatoni 20lb", "quantity": 5, "unit": "case",  "unit_price": 42.00,  "total": 210.00},
            ],
        },
        {
            "vendor_name":    "Sysco Chicago",
            "invoice_number": "SYS-2026-0318",
            "invoice_date":   "2026-03-18",
            "total_amount":   2844.20,
            "status":         "complete",
            "lines": [
                {"description": "Beef Tenderloin",    "quantity": 10, "unit": "lb",    "unit_price": 28.50,  "total": 285.00},
                {"description": "Salmon Fillet",      "quantity":  8, "unit": "lb",    "unit_price": 18.75,  "total": 150.00},
                {"description": "Heavy Cream",        "quantity":  4, "unit": "case",  "unit_price": 55.00,  "total": 220.00},
            ],
        },
        {
            "vendor_name":    "Reyes Beverage Group",
            "invoice_number": "RBG-2026-0305",
            "invoice_date":   "2026-03-05",
            "total_amount":   1890.00,
            "status":         "complete",
            "lines": [
                {"description": "Goose Island IPA 1/2bbl",     "quantity": 2, "unit": "keg",  "unit_price": 175.00, "total": 350.00},
                {"description": "Miller Lite 1/2bbl",           "quantity": 3, "unit": "keg",  "unit_price": 120.00, "total": 360.00},
                {"description": "Tito's Handmade Vodka 1.75L",  "quantity": 6, "unit": "btl",  "unit_price": 31.50,  "total": 189.00},
            ],
        },
    ]

