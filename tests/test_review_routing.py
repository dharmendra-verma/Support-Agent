"""Confidence calibration + review-routing tests (SA-20). Fully offline."""
from __future__ import annotations

from extraction.confidence import (
    LabeledSample,
    accuracy_report,
    calibrate_threshold,
    low_confidence_fields,
    worst_segments,
)
from review import router


# --- calibration against labels (not arbitrary) -----------------------------


def test_calibrate_threshold_from_labels():
    # below 0.8 there are errors; at >=0.9 everything is correct
    samples = [
        LabeledSample(0.6, False), LabeledSample(0.7, False),
        LabeledSample(0.8, True), LabeledSample(0.9, True), LabeledSample(0.95, True),
    ]
    t = calibrate_threshold(samples, target_error=0.0)
    assert t == 0.8  # lowest cutoff whose kept population is 100% correct


def test_calibrate_returns_1_when_target_unreachable():
    samples = [LabeledSample(0.99, False), LabeledSample(0.5, False)]
    assert calibrate_threshold(samples, target_error=0.0) == 1.0  # nothing is clean → all review


def test_low_confidence_fields():
    assert low_confidence_fields({"a": 0.9, "b": 0.4, "c": 0.7}, 0.75) == ["b", "c"]


# --- accuracy by doc-type AND field -----------------------------------------


def test_accuracy_report_segments_hide_in_aggregate():
    records = [
        {"doc_type": "invoice", "field": "total_amount", "correct": True},
        {"doc_type": "invoice", "field": "total_amount", "correct": True},
        {"doc_type": "invoice", "field": "currency", "correct": False},  # bad segment
        {"doc_type": "invoice", "field": "currency", "correct": False},
    ]
    report = accuracy_report(records)
    assert report[("invoice", "total_amount")]["accuracy"] == 1.0
    assert report[("invoice", "currency")]["accuracy"] == 0.0
    assert worst_segments(report) == [("invoice", "currency")]


# --- routing ----------------------------------------------------------------


def test_high_confidence_clean_is_accepted():
    d = router.route({"total_amount": 0.95, "vendor": 0.9}, threshold=0.8)
    assert d.route == router.ACCEPT and d.reasons == []


def test_low_confidence_routes_to_review():
    d = router.route({"total_amount": 0.4}, threshold=0.8)
    assert d.route == router.REVIEW and "low confidence" in d.reasons[0]


def test_conflict_routes_to_review_even_if_confident():
    d = router.route({"total_amount": 0.99}, threshold=0.8, conflict_detected=True)
    assert d.route == router.REVIEW and "contradictory" in d.reasons[0]


def test_ambiguous_field_routes_to_review():
    d = router.route({"damage_type": 0.99}, threshold=0.8, ambiguous_fields=("damage_type",))
    assert d.route == router.REVIEW


# --- review queue (JSONL) ---------------------------------------------------


def test_enqueue_and_read_queue(tmp_path):
    q = tmp_path / "queue.jsonl"
    router.enqueue({"id": "doc-1", "reason": "low confidence"}, q)
    router.enqueue({"id": "doc-2", "reason": "conflict"}, q)
    items = router.read_queue(q)
    assert [i["id"] for i in items] == ["doc-1", "doc-2"]


def test_read_missing_queue_is_empty(tmp_path):
    assert router.read_queue(tmp_path / "none.jsonl") == []


# --- stratified audit sampling of high-confidence ---------------------------


def test_stratified_sample_covers_every_stratum_deterministically():
    items = [{"id": f"d{i}", "doc_type": "invoice"} for i in range(10)] + \
            [{"id": f"w{i}", "doc_type": "warranty_card"} for i in range(10)]
    s1 = router.stratified_audit_sample(items, stratum_key=lambda x: x["doc_type"],
                                        id_key=lambda x: x["id"], rate=0.2)
    s2 = router.stratified_audit_sample(items, stratum_key=lambda x: x["doc_type"],
                                        id_key=lambda x: x["id"], rate=0.2)
    types = {x["doc_type"] for x in s1}
    assert types == {"invoice", "warranty_card"}  # every segment represented
    assert len(s1) == 4                            # 20% of each stratum of 10
    assert s1 == s2                                # deterministic


def test_stratified_sample_takes_at_least_one_per_stratum():
    items = [{"id": "a", "doc_type": "invoice"}, {"id": "b", "doc_type": "warranty_card"}]
    s = router.stratified_audit_sample(items, stratum_key=lambda x: x["doc_type"],
                                       id_key=lambda x: x["id"], rate=0.01)
    assert len(s) == 2  # one from each, even at a tiny rate
