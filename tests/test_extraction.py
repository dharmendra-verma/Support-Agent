"""Extraction schema/contract tests (SA-17).

The contract — tool defs, nullable fields, extensible enums, tool_choice, and parsing a
tool_use block — is fully offline. The live extraction over the corpus needs a key (skipped).
"""
from __future__ import annotations

import json
import os

import pytest
from pydantic import ValidationError

from extraction import extractor, schemas
from extraction.schemas import Currency, DamageReport, DamageType, Invoice
from tests.extraction_corpus import CORPUS, INCOMPLETE


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Resp:
    def __init__(self, content):
        self.content = content


# --- nullable: absent => null, never fabricated -----------------------------


def test_absent_fields_return_null():
    inv = Invoice.model_validate({"vendor": "Acme"})
    assert inv.vendor == "Acme"
    assert inv.invoice_number is None and inv.total_amount is None  # not fabricated


def test_empty_document_validates_to_all_null():
    assert Invoice.model_validate({}).model_dump() == {
        "invoice_number": None, "vendor": None, "invoice_date": None,
        "total_amount": None, "currency": None, "currency_other": None}


def test_json_schema_marks_optional_fields_nullable():
    prop = Invoice.model_json_schema()["properties"]["total_amount"]
    assert "null" in json.dumps(prop)  # schema permits null


# --- extensible enums -------------------------------------------------------


def test_enums_include_unclear_and_other():
    assert Currency("unclear") and Currency("other")
    assert DamageType("unclear") and DamageType("other")


def test_other_uses_detail_field():
    d = DamageReport.model_validate({"damage_type": "other", "damage_type_other": "chemical spill"})
    assert d.damage_type == DamageType.OTHER and d.damage_type_other == "chemical spill"


def test_invalid_enum_value_rejected():
    with pytest.raises(ValidationError):
        Invoice.model_validate({"currency": "bitcoin"})


# --- tool defs are the contract ---------------------------------------------


def test_tool_defs_cover_all_doc_types_with_schemas():
    names = {t["name"] for t in schemas.tool_defs()}
    assert names == {"extract_invoice", "extract_warranty_card", "extract_damage_report"}
    for t in schemas.tool_defs():
        assert "input_schema" in t and t["input_schema"]["type"] == "object"
        assert "never guess" in t["description"] or "never" in t["description"].lower()


# --- tool_choice ------------------------------------------------------------


def test_tool_choice_forced_when_type_known():
    assert extractor.tool_choice("invoice") == {"type": "tool", "name": "extract_invoice"}


def test_tool_choice_any_when_type_unknown():
    assert extractor.tool_choice(None) == {"type": "any"}


# --- parse tool_use block ---------------------------------------------------


def test_parse_reads_tool_use_and_validates():
    resp = Resp([Block(type="text", text="..."),
                 Block(type="tool_use", name="extract_invoice",
                       input={"vendor": "Acme", "total_amount": 12.5})])
    inv = extractor.parse_extraction(resp)
    assert isinstance(inv, Invoice)
    assert inv.vendor == "Acme" and inv.invoice_number is None  # absent stays null


def test_parse_infers_doc_type_from_tool_name():
    resp = Resp([Block(type="tool_use", name="extract_damage_report",
                       input={"order_id": "12345", "severity": "major"})])
    out = extractor.parse_extraction(resp)
    assert isinstance(out, DamageReport) and out.order_id == "12345"


def test_parse_raises_without_tool_use():
    with pytest.raises(ValueError):
        extractor.parse_extraction(Resp([Block(type="text", text="no tool call")]))


# --- normalization prompt + corpus -----------------------------------------


def test_normalization_prompt_states_rules():
    p = extractor.NORMALIZATION_PROMPT
    assert "ISO 8601" in p and "ISO 4217" in p
    assert "null" in p and "NEVER fabricate" in p
    assert "unclear" in p and "other" in p


def test_corpus_has_20_docs_including_incomplete():
    assert len(CORPUS) >= 20
    assert len(INCOMPLETE) >= 5  # deliberately missing-field documents
    assert {d["doc_type"] for d in CORPUS} == set(schemas.DOC_MODELS)


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"),
                    reason="live extraction over the corpus needs ANTHROPIC_API_KEY")
def test_live_extraction_never_fabricates_missing_fields():
    fabricated = []
    for doc in CORPUS:
        result = extractor.extract(doc["text"], doc_type=doc["doc_type"])
        for field in doc["expected_nulls"]:
            if getattr(result, field) is not None:
                fabricated.append((doc["text"][:30], field, getattr(result, field)))
    assert fabricated == [], f"fabricated values: {fabricated}"
