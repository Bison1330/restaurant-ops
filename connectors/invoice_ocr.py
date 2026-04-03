import anthropic
import base64
import json
import os
import re
from pathlib import Path

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


def extract_invoice_from_image(image_path):
    if not ANTHROPIC_API_KEY:
        return _mock_invoice()

    path = Path(image_path)
    suffix = path.suffix.lower()

    with open(image_path, "rb") as f:
        file_data = base64.standard_b64encode(f.read()).decode("utf-8")

    media_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix)
    if not media_type:
        raise ValueError(f"Unsupported file type: {suffix}")

    if suffix == ".pdf":
        content_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": file_data,
            },
        }
    else:
        content_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": file_data,
            },
        }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-opus-4-5-20250514",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    content_block,
                    {
                        "type": "text",
                        "text": (
                            "Extract the invoice data from this document and return ONLY valid JSON "
                            "with no markdown formatting. The JSON should contain these fields: "
                            "vendor_name, invoice_number, invoice_date, total_amount, "
                            "and a lines array where each line has: description, vendor_sku, "
                            "quantity, unit, unit_cost, line_total."
                        ),
                    },
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()
    json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group()

    invoice = json.loads(response_text)
    invoice["source"] = "ocr"
    return invoice


def _mock_invoice():
    lines = [
        {
            "description": "Roma Tomatoes 25lb Case",
            "vendor_sku": "USF-RT25",
            "quantity": 3.0,
            "unit": "case",
            "unit_cost": 38.50,
            "line_total": 115.50,
        },
        {
            "description": "Yellow Onions 50lb Bag",
            "vendor_sku": "USF-YO50",
            "quantity": 2.0,
            "unit": "bag",
            "unit_cost": 24.00,
            "line_total": 48.00,
        },
        {
            "description": "Fresh Basil 1lb Clamshell",
            "vendor_sku": "USF-FB1",
            "quantity": 6.0,
            "unit": "each",
            "unit_cost": 4.75,
            "line_total": 28.50,
        },
    ]
    return {
        "vendor_name": "US Foods",
        "invoice_number": "USF-2024-441290",
        "invoice_date": "2024-11-15",
        "total_amount": sum(l["line_total"] for l in lines),
        "source": "ocr",
        "lines": lines,
    }
