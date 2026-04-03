import os
from datetime import datetime

QB_ACCOUNTS = {
    "food_cost": "Cost of Goods Sold:Food Cost",
    "alcohol_cost": "Cost of Goods Sold:Beverage Cost",
    "supplies": "Operating Expenses:Supplies",
    "ap": "Accounts Payable",
    "wages": "Payroll Expenses:Wages",
    "checking": "Checking",
}


def export_invoices_iif(invoices, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    lines = []
    lines.append("!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO")
    lines.append("!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO")
    lines.append("!ENDTRNS")

    for inv in invoices:
        vendor_name = inv.get("vendor_name", "")
        inv_num = inv.get("invoice_number", "")
        total = float(inv.get("total_amount", 0))
        source = inv.get("source", "")

        inv_date = inv.get("invoice_date", "")
        if inv_date:
            try:
                parsed = datetime.strptime(inv_date, "%Y-%m-%d")
                inv_date = parsed.strftime("%m/%d/%Y")
            except ValueError:
                pass

        expense_account = QB_ACCOUNTS["alcohol_cost"] if source == "fintech" else QB_ACCOUNTS["food_cost"]

        lines.append(
            f"TRNS\tBILL\t{inv_date}\t{QB_ACCOUNTS['ap']}\t{vendor_name}\t{-total:.2f}\t{inv_num}"
        )

        for line_item in inv.get("lines", []):
            line_total = float(line_item.get("line_total", 0))
            desc = line_item.get("description", "")
            lines.append(
                f"SPL\tBILL\t{inv_date}\t{expense_account}\t{vendor_name}\t{line_total:.2f}\t{desc}"
            )

        lines.append("ENDTRNS")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return output_path


def export_payroll_iif(payroll_run, employees_data, output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    lines = []
    lines.append("!TRNS\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO")
    lines.append("!SPL\tTRNSTYPE\tDATE\tACCNT\tNAME\tAMOUNT\tMEMO")
    lines.append("!ENDTRNS")

    total_gross = float(payroll_run.get("total_gross", 0))
    period_end = payroll_run.get("period_end", "")
    if period_end:
        try:
            parsed = datetime.strptime(period_end, "%Y-%m-%d")
            period_end = parsed.strftime("%m/%d/%Y")
        except ValueError:
            pass

    memo = f"Payroll {payroll_run.get('period_start', '')} to {payroll_run.get('period_end', '')}"

    lines.append(
        f"TRNS\tGENERAL JOURNAL\t{period_end}\t{QB_ACCOUNTS['wages']}\t\t{total_gross:.2f}\t{memo}"
    )
    lines.append(
        f"SPL\tGENERAL JOURNAL\t{period_end}\t{QB_ACCOUNTS['checking']}\t\t{-total_gross:.2f}\t{memo}"
    )
    lines.append("ENDTRNS")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    return output_path
