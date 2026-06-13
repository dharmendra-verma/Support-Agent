"""Provenance + structured-context tests (SA-22). Fully offline.

Covers: the structured Finding contract (content vs metadata), end-to-end claim→source
preservation through synthesis, side-by-side conflict surfacing (never arbitrary collapse),
temporal-change vs contradiction, and type-appropriate rendering.
"""
from __future__ import annotations

from research.schemas import ContentType, Finding, finding_tool_def
from research.synthesis import (
    CONTESTED,
    ESTABLISHED,
    SINGLE,
    TEMPORAL,
    classify,
    synthesize,
)


def f(topic, claim, source, *, value=None, date=None, ctype=ContentType.OTHER, evidence=None):
    return Finding(topic=topic, claim=claim, source=source, value=value,
                   source_date=date, content_type=ctype, evidence=evidence)


# --- the structured contract ------------------------------------------------


def test_finding_separates_content_from_metadata():
    finding = f("revenue", "Q1 revenue was $5M", "https://ex.com/q1", value="5000000",
                date="2026-04-01", ctype=ContentType.FINANCIAL, evidence="revenue of $5M")
    # content
    assert finding.claim and finding.evidence
    # metadata
    assert finding.source and finding.source_date and finding.content_type


def test_finding_tool_def_is_the_output_contract():
    td = finding_tool_def()
    assert td["name"] == "record_finding"
    props = td["input_schema"]["properties"]
    for required_field in ("topic", "claim", "source", "source_date", "value", "content_type"):
        assert required_field in props


# --- provenance round-trip --------------------------------------------------


def test_every_source_survives_synthesis_mapped_to_its_claim():
    findings = [
        f("market size", "Market is $2B", "https://a.com/report", value="2B", date="2026-01-01"),
        f("market size", "Market is $2B", "https://b.com/study", value="2B", date="2026-02-01"),
        f("growth", "Growing 10% YoY", "https://c.com/news", date="2026-03-01",
          ctype=ContentType.NEWS),
    ]
    report = synthesize(findings)
    # No source dropped, each mapped to its topic.
    assert set(report.sources_for("market size")) == {"https://a.com/report", "https://b.com/study"}
    assert report.sources_for("growth") == ["https://c.com/news"]
    # And every source appears in the rendered output (cited per claim).
    md = report.to_markdown()
    for src in ("https://a.com/report", "https://b.com/study", "https://c.com/news"):
        assert src in md


# --- corroboration vs single source -----------------------------------------


def test_two_sources_same_value_is_established():
    findings = [f("price", "costs $10", "s1", value="10", date="2026-01-01"),
                f("price", "costs $10", "s2", value="10", date="2026-01-01")]
    assert classify(findings) == ESTABLISHED


def test_one_source_is_single_not_established():
    assert classify([f("price", "costs $10", "s1", value="10", date="2026-01-01")]) == SINGLE


# --- conflict: side by side, never collapsed --------------------------------


def test_same_date_disagreement_is_contested_and_shown_side_by_side():
    findings = [
        f("user count", "10M users", "https://a.com", value="10M", date="2026-01-01"),
        f("user count", "12M users", "https://b.com", value="12M", date="2026-01-01"),
    ]
    assert classify(findings) == CONTESTED
    report = synthesize(findings)
    md = report.to_markdown()
    # Both values present with their attribution — no arbitrary pick.
    assert "10M" in md and "12M" in md
    assert "https://a.com" in md and "https://b.com" in md
    assert "contested" in md.lower()


def test_undated_disagreement_is_contested_not_assumed_temporal():
    # Without dates we cannot claim the difference is change-over-time → conservative: contested.
    findings = [f("share", "30%", "a", value="30"), f("share", "45%", "b", value="45")]
    assert classify(findings) == CONTESTED


# --- temporal change is not a contradiction ---------------------------------


def test_different_values_at_different_dates_is_temporal_not_contested():
    findings = [
        f("revenue", "Revenue $4M", "https://a.com", value="4M", date="2025-01-01"),
        f("revenue", "Revenue $6M", "https://a.com", value="6M", date="2026-01-01"),
    ]
    assert classify(findings) == TEMPORAL
    md = synthesize(findings).to_markdown()
    assert "contested" not in md.lower()
    assert "over time" in md.lower()


# --- type-appropriate rendering ---------------------------------------------


def test_financial_renders_as_table():
    findings = [f("ARR", "ARR is $5M", "s1", value="$5M", date="2026-01-01",
                  ctype=ContentType.FINANCIAL)]
    md = synthesize(findings).to_markdown()
    assert "| Value | Source | Date |" in md  # table header


def test_news_renders_as_prose_with_inline_citations():
    findings = [f("launch", "Product X launched", "https://news.com", date="2026-05-01",
                  ctype=ContentType.NEWS)]
    md = synthesize(findings).to_markdown()
    assert "Product X launched [https://news.com (2026-05-01)]." in md


def test_technical_renders_as_list():
    findings = [f("api", "Supports OAuth2", "docs.md", ctype=ContentType.TECHNICAL)]
    md = synthesize(findings).to_markdown()
    assert "  - Supports OAuth2 — docs.md" in md


# --- report-level accessors --------------------------------------------------


def test_report_separates_established_from_contested():
    findings = [
        f("a", "x", "s1", value="1", date="2026-01-01"),
        f("a", "x", "s2", value="1", date="2026-01-01"),     # established
        f("b", "y", "s1", value="1", date="2026-01-01"),
        f("b", "y", "s2", value="2", date="2026-01-01"),     # contested
    ]
    report = synthesize(findings)
    assert [g.topic for g in report.established] == ["a"]
    assert [g.topic for g in report.contested] == ["b"]
