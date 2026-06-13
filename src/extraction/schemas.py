"""Extraction schemas (SA-17).

Each document type is a Pydantic model whose JSON schema becomes a tool's
``input_schema`` — the **output contract**. The model extracts by *calling* the tool, so its
arguments are guaranteed-shaped JSON (read from the ``tool_use`` block), not free text.

Two anti-fabrication guarantees live in the schema itself:
- every field that may be absent is **optional/nullable** → missing info comes back ``null``,
  never invented;
- categorical fields always include **``unclear``** (ambiguous) and **``other``** (+ a detail
  string) so a real value is never forced into the wrong bucket.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    OTHER = "other"      # use with currency_other
    UNCLEAR = "unclear"  # ambiguous in the document


class DamageType(str, Enum):
    SHIPPING = "shipping"
    MANUFACTURING = "manufacturing"
    WATER = "water"
    OTHER = "other"      # use with damage_type_other
    UNCLEAR = "unclear"


class Severity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    TOTAL_LOSS = "total_loss"
    UNCLEAR = "unclear"


class Invoice(BaseModel):
    invoice_number: str | None = None
    vendor: str | None = None
    invoice_date: str | None = None          # ISO 8601
    total_amount: float | None = None        # plain decimal, no symbol
    currency: Currency | None = None
    currency_other: str | None = None        # when currency == other


class WarrantyCard(BaseModel):
    product: str | None = None
    serial_number: str | None = None
    purchase_date: str | None = None         # ISO 8601
    warranty_months: int | None = None


class DamageReport(BaseModel):
    order_id: str | None = None
    damage_type: DamageType | None = None
    damage_type_other: str | None = None     # when damage_type == other
    severity: Severity | None = None
    description: str | None = None


# document type -> model. The single source for tool defs and parsing.
DOC_MODELS: dict[str, type[BaseModel]] = {
    "invoice": Invoice,
    "warranty_card": WarrantyCard,
    "damage_report": DamageReport,
}


def tool_name(doc_type: str) -> str:
    return f"extract_{doc_type}"


def tool_defs() -> list[dict]:
    """Anthropic tool defs whose ``input_schema`` is the extraction contract."""
    defs = []
    for doc_type, model in DOC_MODELS.items():
        pretty = doc_type.replace("_", " ")
        defs.append({
            "name": tool_name(doc_type),
            "description": (f"Extract structured fields from a {pretty}. Use null for any "
                            "field the document does not contain — never guess or fabricate."),
            "input_schema": model.model_json_schema(),
        })
    return defs
