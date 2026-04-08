import paramiko
import csv
import io
import os
from datetime import datetime
import pytz

CENTRAL_TZ = pytz.timezone("US/Central")

GFS_HOST = "sftp-gordon.gfs.com"
GFS_PORT = 22
GFS_SFTP_USER = os.environ.get("GFS_SFTP_USER")
GFS_SFTP_PASS = os.environ.get("GFS_SFTP_PASS")


def fetch_gfs_invoices(account_number):
    if not GFS_SFTP_USER or not GFS_SFTP_PASS:
        return _mock_invoices(account_number)

    invoices = []
    transport = paramiko.Transport((GFS_HOST, GFS_PORT))
    try:
        transport.connect(username=GFS_SFTP_USER, password=GFS_SFTP_PASS)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            for filename in sftp.listdir("/inbox"):
                if account_number in filename and filename.endswith(".csv"):
                    with sftp.open(f"/inbox/{filename}", "r") as f:
                        content = f.read().decode("utf-8")
                    reader = csv.DictReader(io.StringIO(content))
                    invoice_map = {}
                    for row in reader:
                        inv_num = row.get("invoice_number", "")
                        if inv_num not in invoice_map:
                            invoice_map[inv_num] = {
                                "invoice_number": inv_num,
                                "invoice_date": row.get("invoice_date", ""),
                                "total_amount": 0.0,
                                "source": "gfs",
                                "lines": [],
                            }
                        line_total = float(row.get("line_total", 0))
                        invoice_map[inv_num]["lines"].append({
                            "description": row.get("description", ""),
                            "vendor_sku": row.get("vendor_sku", ""),
                            "quantity": float(row.get("quantity", 0)),
                            "unit": row.get("unit", ""),
                            "unit_cost": float(row.get("unit_cost", 0)),
                            "line_total": line_total,
                        })
                        invoice_map[inv_num]["total_amount"] += line_total
                    invoices.extend(invoice_map.values())
        finally:
            sftp.close()
    finally:
        transport.close()

    return invoices


def _mock_invoices(account_number):
    today = datetime.now(CENTRAL_TZ).strftime("%Y-%m-%d")
    lines = [
        {
            "description": "Chicken Breast 40lb Case",
            "vendor_sku": "GFS-10441",
            "quantity": 3.0,
            "unit": "case",
            "unit_cost": 89.50,
            "line_total": 268.50,
        },
        {
            "description": "Ground Beef 80/20 10lb Roll",
            "vendor_sku": "GFS-20118",
            "quantity": 5.0,
            "unit": "roll",
            "unit_cost": 42.75,
            "line_total": 213.75,
        },
        {
            "description": "Idaho Potatoes 50lb Bag",
            "vendor_sku": "GFS-30205",
            "quantity": 2.0,
            "unit": "bag",
            "unit_cost": 31.00,
            "line_total": 62.00,
        },
        {
            "description": "Romaine Lettuce Hearts 24ct",
            "vendor_sku": "GFS-40087",
            "quantity": 4.0,
            "unit": "case",
            "unit_cost": 28.25,
            "line_total": 113.00,
        },
    ]
    return [
        {
            "invoice_number": f"GFS-MOCK-{account_number}-001",
            "invoice_date": today,
            "total_amount": sum(l["line_total"] for l in lines),
            "source": "gfs",
            "lines": lines,
        }
    ]
