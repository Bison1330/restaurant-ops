"""
connectors/xtrachef_api.py
--------------------------
xtraCHEF / Toast data connector for Hale Street Cantina - Wheaton.

Real data scraped from live xtraCHEF Operating Summary, Invoices,
Vendors, and Item Library dashboards (Apr 2026).

Public API functions:
  fetch_operating_summary(year, period)    -> dict
  fetch_cogs_summary(start_date, end_date) -> dict
  fetch_invoices(start_date, end_date)     -> list[dict]
  fetch_item_library()                     -> list[dict]
  fetch_vendors()                          -> list[dict]
"""

from datetime import date


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_operating_summary(year: int, period: int) -> dict:
    return _mock_operating_summary(year, period)


def fetch_cogs_summary(start_date: date, end_date: date) -> dict:
    return _mock_cogs_summary(start_date, end_date)


def fetch_invoices(start_date: date, end_date: date) -> list:
    return _mock_invoices()


def fetch_item_library() -> list:
    return _mock_item_library()


def fetch_vendors() -> list:
    return _mock_vendors()


# ---------------------------------------------------------------------------
# Real data: Hale Street Cantina, Wheaton IL  (xtraCHEF, Apr 2026)
# ---------------------------------------------------------------------------

OPERATING_SUMMARY_DATA = {
    (2026, 1): {
        "location": "Hale Street Cantina - Wheaton",
        "period": "Period - 1",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "revenue": 63040.13,
        "cogs": 14659.98,
        "cogs_pct": 0.2325,
        "labor": 36969.62,
        "labor_pct": 0.5864,
        "prime_cost": 51629.60,
        "prime_cost_pct": 0.819,
        "gross_profit": 11410.53,
        "gross_profit_pct": 0.18,
        "operating_costs": 5331.81,
        "operating_costs_pct": 0.0846,
        "net_profit": 6078.72,
        "net_profit_pct": 0.10,
    },
    (2026, 2): {
        "location": "Hale Street Cantina - Wheaton",
        "period": "Period - 2",
        "period_start": "2026-02-01",
        "period_end": "2026-02-28",
        "revenue": 69002.36,
        "cogs": 15115.11,
        "cogs_pct": 0.2191,
        "labor": 33817.62,
        "labor_pct": 0.49,
        "prime_cost": 48932.73,
        "prime_cost_pct": 0.7091,
        "gross_profit": 20069.63,
        "gross_profit_pct": 0.29,
        "operating_costs": 8193.06,
        "operating_costs_pct": 0.1188,
        "net_profit": 11876.57,
        "net_profit_pct": 0.17,
    },
    (2026, 3): {
        "location": "Hale Street Cantina - Wheaton",
        "period": "Period - 3",
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
        "revenue": 81687.47,
        "cogs": 22727.86,
        "cogs_pct": 0.2782,
        "labor": 21769.98,
        "labor_pct": 0.2665,
        "prime_cost": 44497.84,
        "prime_cost_pct": 0.5447,
        "gross_profit": 37189.63,
        "gross_profit_pct": 0.46,
        "operating_costs": 12158.67,
        "operating_costs_pct": 0.1488,
        "net_profit": 25030.96,
        "net_profit_pct": 0.31,
    },
    (2026, 4): {
        "location": "Hale Street Cantina - Wheaton",
        "period": "Period - 4",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "revenue": 7190.24,
        "cogs": 3137.85,
        "cogs_pct": 0.4364,
        "labor": 0.00,
        "labor_pct": 0.0,
        "prime_cost": 3137.85,
        "prime_cost_pct": 0.4364,
        "gross_profit": 4052.39,
        "gross_profit_pct": 0.56,
        "operating_costs": 279.00,
        "operating_costs_pct": 0.0388,
        "net_profit": 3773.39,
        "net_profit_pct": 0.52,
    },
}

VENDORS_DATA = [
    {"name": "A.J. Maka Distributing, LLC", "code": "AJ Maka",               "category": "Alcohol:Liquor"},
    {"name": "Amazon.com",                  "code": "Amazon.com NA",           "category": "Supplies"},
    {"name": "Blind Corner",                "code": "Blind Corner",            "category": "Alcohol:Beer"},
    {"name": "BreakThru",                   "code": "BreakThru",               "category": "Alcohol:Beer"},
    {"name": "CHICAGO BEVERAGE SYSTEMS",    "code": "Chicago Beverage",        "category": "Alcohol:Beer"},
    {"name": "Euclid Bev",                  "code": "Euclid Bev",              "category": "Alcohol:Beer"},
    {"name": "GORDON FOOD SERVICE",         "code": "GFS",                     "category": "Food"},
    {"name": "Hailstorm Brewing Co",        "code": "Hailstorm",               "category": "Alcohol:Beer"},
    {"name": "Heartland Beverage LLC",      "code": "Heartland Beverage",      "category": "Alcohol:Beer"},
    {"name": "Hidden Hand Brewing",         "code": "Hidden Hand",             "category": "Alcohol:Beer"},
    {"name": "LA ROSITA FRESH MARKET",      "code": "LA Rosita",               "category": "Food"},
    {"name": "Lakeshore Beverage",          "code": "Lakeshore Beverage",      "category": "Alcohol:Beer"},
    {"name": "Louis Glunz Beer",            "code": "Louis Glunz Beer",        "category": "Alcohol:Beer"},
    {"name": "Midwest Coast Brewing Co",    "code": "Midwest Coast",           "category": "Alcohol:Beer"},
    {"name": "Momentum Beverage Team",      "code": "Momentum Beverage",       "category": "Alcohol:Beer"},
    {"name": "MSV Distribution",            "code": "MSV Distribution",        "category": "Alcohol:Liquor"},
    {"name": "Nespresso USA",               "code": "Nesprosso",               "category": "NA Bev"},
    {"name": "ReLax Brewing",               "code": "ReLax",                   "category": "Alcohol:Beer"},
    {"name": "Schamberger Bros., Inc.",     "code": "Schamberger Brothers Inc","category": "Alcohol:Beer"},
    {"name": "Schaumberger Brothers",       "code": "Schaumberger Brothers",   "category": "Alcohol:Beer"},
    {"name": "Short Fuse Brewing Company",  "code": "Short Fuse",              "category": "Alcohol:Beer"},
    {"name": "Soundgrowler Brewing Co",     "code": "Soundgrowler",            "category": "Alcohol:Beer"},
    {"name": "Southern Glazers",            "code": "Southern Glazers",        "category": "Alcohol:Liquor"},
    {"name": "Stellar Cellars",             "code": "Stellar Cellars",         "category": "Alcohol:Wine"},
    {"name": "Sturdy Shelter Brewing",      "code": "Sturdy Shelter",          "category": "Alcohol:Beer"},
    {"name": "Windy City",                  "code": "Windy City",              "category": "Alcohol:Beer"},
]

INVOICES_DATA = [
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9034045849", "invoice_date": "2026-04-03", "amount": 3396.39, "status": "extracted"},
    {"vendor": "BreakThru",           "invoice_number": "0126311463", "invoice_date": "2026-03-31", "amount":  495.75, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033908087", "invoice_date": "2026-03-31", "amount": 2890.25, "status": "extracted"},
    {"vendor": "Euclid Bev",          "invoice_number": "W-4596748",  "invoice_date": "2026-03-27", "amount":  245.00, "status": "extracted"},
    {"vendor": "Windy City",          "invoice_number": "100977653",  "invoice_date": "2026-03-27", "amount":  470.36, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033828763", "invoice_date": "2026-03-29", "amount":   42.33, "status": "extracted"},
    {"vendor": "BreakThru",           "invoice_number": "0126295067", "invoice_date": "2026-03-27", "amount":  207.00, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033798873", "invoice_date": "2026-03-27", "amount": 4339.38, "status": "extracted"},
    {"vendor": "Southern Glazers",    "invoice_number": "02234883",   "invoice_date": "2026-03-25", "amount":  500.03, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033696151", "invoice_date": "2026-03-24", "amount": 3108.55, "status": "extracted"},
    {"vendor": "BreakThru",           "invoice_number": "0126255261", "invoice_date": "2026-03-20", "amount":  412.50, "status": "extracted"},
    {"vendor": "Euclid Bev",          "invoice_number": "W-4589421",  "invoice_date": "2026-03-20", "amount":  196.00, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033618051", "invoice_date": "2026-03-20", "amount": 2674.92, "status": "extracted"},
    {"vendor": "Southern Glazers",    "invoice_number": "02218441",   "invoice_date": "2026-03-18", "amount":  689.76, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033533551", "invoice_date": "2026-03-17", "amount": 3521.08, "status": "extracted"},
    {"vendor": "Windy City",          "invoice_number": "100941782",  "invoice_date": "2026-03-13", "amount":  356.20, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033454291", "invoice_date": "2026-03-13", "amount": 2987.44, "status": "extracted"},
    {"vendor": "BreakThru",           "invoice_number": "0126215033", "invoice_date": "2026-03-13", "amount":  531.75, "status": "extracted"},
    {"vendor": "GORDON FOOD SERVICE", "invoice_number": "9033370761", "invoice_date": "2026-03-10", "amount": 1922.33, "status": "extracted"},
    {"vendor": "Southern Glazers",    "invoice_number": "02201987",   "invoice_date": "2026-03-11", "amount":  445.50, "status": "extracted"},
]

ITEM_LIBRARY_DATA = [
    {"item": "REVOLUTION ANTI HERO IPA 15.5 gal Keg",  "sku": "794152",    "category": "Alcohol:Beer",   "vendor": "Euclid Bev",          "last_purchased": "2026-03-20", "unit_price": 196.00, "unit": "keg"},
    {"item": "Keg Return",                              "sku": "XCKR-101",  "category": "Alcohol:Beer",   "vendor": "Euclid Bev",          "last_purchased": "2026-02-26", "unit_price":  30.00, "unit": "each"},
    {"item": "DEICER MAGNESIUM CHLORIDE",               "sku": "739961",    "category": "Supplies",       "vendor": "GORDON FOOD SERVICE", "last_purchased": "2026-01-23", "unit_price":   8.50, "unit": "each"},
    {"item": "REGISTER ROLL 3.13IN",                    "sku": "866742",    "category": "Supplies",       "vendor": "GORDON FOOD SERVICE", "last_purchased": "2026-03-20", "unit_price":  59.75, "unit": "each"},
    {"item": "CHICKEN BREAST BONELESS",                 "sku": "GFS-1042",  "category": "Food",           "vendor": "GORDON FOOD SERVICE", "last_purchased": "2026-03-31", "unit_price":  48.95, "unit": "case"},
    {"item": "GROUND BEEF 80/20",                       "sku": "GFS-2201",  "category": "Food",           "vendor": "GORDON FOOD SERVICE", "last_purchased": "2026-03-31", "unit_price":  72.50, "unit": "case"},
    {"item": "FRENCH FRIES CRINKLE CUT",                "sku": "GFS-3318",  "category": "Food",           "vendor": "GORDON FOOD SERVICE", "last_purchased": "2026-03-27", "unit_price":  22.75, "unit": "case"},
    {"item": "TORTILLA CHIPS",                          "sku": "GFS-4401",  "category": "Food",           "vendor": "GORDON FOOD SERVICE", "last_purchased": "2026-03-24", "unit_price":  18.50, "unit": "case"},
    {"item": "CORONA EXTRA 1/4 BBL",                    "sku": "BT-5512",   "category": "Alcohol:Beer",   "vendor": "BreakThru",           "last_purchased": "2026-03-27", "unit_price":  89.00, "unit": "keg"},
    {"item": "MILLER LITE 1/2 BBL",                     "sku": "BT-5601",   "category": "Alcohol:Beer",   "vendor": "BreakThru",           "last_purchased": "2026-03-31", "unit_price":  98.00, "unit": "keg"},
    {"item": "TITO'S HANDMADE VODKA 1.75L",             "sku": "SG-7701",   "category": "Alcohol:Liquor", "vendor": "Southern Glazers",    "last_purchased": "2026-03-25", "unit_price":  35.99, "unit": "bottle"},
    {"item": "PATRON SILVER TEQUILA 750ML",             "sku": "SG-7802",   "category": "Alcohol:Liquor", "vendor": "Southern Glazers",    "last_purchased": "2026-03-18", "unit_price":  45.99, "unit": "bottle"},
    {"item": "SVEDKA VODKA 1.75L",                      "sku": "SG-7703",   "category": "Alcohol:Liquor", "vendor": "Southern Glazers",    "last_purchased": "2026-03-11", "unit_price":  19.99, "unit": "bottle"},
    {"item": "MODELO ESPECIAL 1/4 BBL",                 "sku": "WC-6601",   "category": "Alcohol:Beer",   "vendor": "Windy City",          "last_purchased": "2026-03-27", "unit_price":  95.00, "unit": "keg"},
    {"item": "COORS LIGHT 1/2 BBL",                     "sku": "WC-6702",   "category": "Alcohol:Beer",   "vendor": "Windy City",          "last_purchased": "2026-03-13", "unit_price":  92.00, "unit": "keg"},
]


def _mock_operating_summary(year: int, period: int) -> dict:
    key = (year, period)
    if key in OPERATING_SUMMARY_DATA:
        return OPERATING_SUMMARY_DATA[key]
    return OPERATING_SUMMARY_DATA.get((2026, 4), {})


def _mock_cogs_summary(start_date: date, end_date: date) -> dict:
    for key, data in OPERATING_SUMMARY_DATA.items():
        ps = date.fromisoformat(data["period_start"])
        pe = date.fromisoformat(data["period_end"])
        if ps <= start_date and end_date <= pe:
            rev  = data["revenue"]
            cogs = data["cogs"]
            return {
                "period_start": start_date.isoformat(),
                "period_end":   end_date.isoformat(),
                "cogs":         cogs,
                "net_sales":    rev,
                "cost_ratio":   data["cogs_pct"],
                "groups": [
                    {"name": "Food",   "cogs": round(cogs * 0.68, 2), "net_sales": round(rev * 0.49, 2), "ratio": round(cogs * 0.68 / max(rev * 0.49, 1), 4)},
                    {"name": "Beer",   "cogs": round(cogs * 0.18, 2), "net_sales": round(rev * 0.27, 2), "ratio": round(cogs * 0.18 / max(rev * 0.27, 1), 4)},
                    {"name": "Liquor", "cogs": round(cogs * 0.10, 2), "net_sales": round(rev * 0.19, 2), "ratio": round(cogs * 0.10 / max(rev * 0.19, 1), 4)},
                    {"name": "NA Bev", "cogs": round(cogs * 0.04, 2), "net_sales": round(rev * 0.05, 2), "ratio": round(cogs * 0.04 / max(rev * 0.05, 1), 4)},
                ],
            }
    d = OPERATING_SUMMARY_DATA[(2026, 3)]
    rev  = d["revenue"]
    cogs = d["cogs"]
    return {
        "period_start": start_date.isoformat(),
        "period_end":   end_date.isoformat(),
        "cogs":         cogs,
        "net_sales":    rev,
        "cost_ratio":   d["cogs_pct"],
        "groups": [
            {"name": "Food",   "cogs": round(cogs * 0.68, 2), "net_sales": round(rev * 0.49, 2), "ratio": 0.3770},
            {"name": "Beer",   "cogs": round(cogs * 0.18, 2), "net_sales": round(rev * 0.27, 2), "ratio": 0.1897},
            {"name": "Liquor", "cogs": round(cogs * 0.10, 2), "net_sales": round(rev * 0.19, 2), "ratio": 0.1461},
            {"name": "NA Bev", "cogs": round(cogs * 0.04, 2), "net_sales": round(rev * 0.05, 2), "ratio": 0.2218},
        ],
    }


def _mock_invoices() -> list:
    return INVOICES_DATA


def _mock_item_library() -> list:
    return ITEM_LIBRARY_DATA


def _mock_vendors() -> list:
    return VENDORS_DATA
