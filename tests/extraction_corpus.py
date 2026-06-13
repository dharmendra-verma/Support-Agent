"""20 synthetic documents for extraction testing (SA-17): varied formats, many with
deliberately missing fields. ``expected_nulls`` are fields that MUST come back null (the
document genuinely lacks them) — the live extraction test asserts they are never fabricated.
"""

CORPUS = [
    # --- invoices ---
    {"doc_type": "invoice", "text": "INVOICE INV-1001\nAcme Corp\n2026-01-15\nTotal: $1,234.50 USD",
     "expected_nulls": []},
    {"doc_type": "invoice", "text": "Bill from Globex\nAmount due: 99 EUR",
     "expected_nulls": ["invoice_number", "invoice_date"]},
    {"doc_type": "invoice", "text": "Receipt #7782\nDated 01/02/2026\n£12.00",
     "expected_nulls": ["vendor"]},
    {"doc_type": "invoice", "text": "Invoice from Initech\nTotal: 500 (currency not printed)",
     "expected_nulls": ["invoice_number", "invoice_date"]},
    {"doc_type": "invoice", "text": "Handwritten invoice, amount illegible\nVendor: Wonka Ltd\n2025-11-03",
     "expected_nulls": ["total_amount", "invoice_number"]},
    {"doc_type": "invoice", "text": "INV-2231\nUmbrella Co\n2026-03-09\n¥10000",
     "expected_nulls": []},
    {"doc_type": "invoice", "text": "Total only: $42.00",
     "expected_nulls": ["invoice_number", "vendor", "invoice_date"]},
    # --- warranty cards ---
    {"doc_type": "warranty_card",
     "text": "Warranty\nProduct: SuperBlender 3000\nSerial: SB-9921\nPurchased 2025-12-01\n24 months",
     "expected_nulls": []},
    {"doc_type": "warranty_card", "text": "Warranty card\nProduct: Toaster\n(no serial printed)",
     "expected_nulls": ["serial_number", "purchase_date", "warranty_months"]},
    {"doc_type": "warranty_card", "text": "Serial 00-AB-12 only on the sticker",
     "expected_nulls": ["product", "purchase_date", "warranty_months"]},
    {"doc_type": "warranty_card", "text": "Lifetime warranty on Widget X, bought Jan 2026",
     "expected_nulls": ["serial_number"]},
    {"doc_type": "warranty_card",
     "text": "Card: Drone Z\nSN: DRZ-5\nBought: 2026-02-20\nCoverage: 12 mo",
     "expected_nulls": []},
    {"doc_type": "warranty_card", "text": "Smashed card, only 'Headphones' legible",
     "expected_nulls": ["serial_number", "purchase_date", "warranty_months"]},
    # --- damage reports ---
    {"doc_type": "damage_report",
     "text": "Order 12345 arrived with a cracked screen from shipping. Major damage.",
     "expected_nulls": []},
    {"doc_type": "damage_report", "text": "Item was soaked / wet on arrival",
     "expected_nulls": ["order_id", "severity"]},
    {"doc_type": "damage_report", "text": "Customer says it broke; cause unknown",
     "expected_nulls": ["order_id"]},
    {"doc_type": "damage_report",
     "text": "Order 98765 totally destroyed, looks like a chemical spill",
     "expected_nulls": []},
    {"doc_type": "damage_report", "text": "Minor scuff, manufacturing defect, order 222",
     "expected_nulls": []},
    {"doc_type": "damage_report", "text": "No order number; severe water damage to the box",
     "expected_nulls": ["order_id"]},
    {"doc_type": "damage_report", "text": "Order 555 — slight dent, not sure what caused it",
     "expected_nulls": []},
]

INCOMPLETE = [d for d in CORPUS if d["expected_nulls"]]
