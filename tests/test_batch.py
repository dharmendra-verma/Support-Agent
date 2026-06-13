"""Batch extraction tests (SA-19) — request building, custom_id correlation, failure
resubmission with chunking, and SLA math. All offline (no live batches API)."""
from __future__ import annotations

from extraction import batch
from extraction.schemas import Invoice


class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Msg:
    def __init__(self, content):
        self.content = content


class Result:
    def __init__(self, type, message=None, error=None):
        self.type = type
        self.message = message
        self.error = error


class Entry:
    def __init__(self, custom_id, result):
        self.custom_id = custom_id
        self.result = result


DOCS = [
    {"custom_id": "ticket-0001", "document": "Invoice INV-1\nAcme\nTotal $10", "doc_type": "invoice"},
    {"custom_id": "ticket-0002", "document": "Order 5 arrived cracked", "doc_type": "damage_report"},
]


# --- request building (pure extraction, custom_id) --------------------------


def test_build_request_is_pure_single_turn_extraction():
    req = batch.build_request("ticket-0001", "doc", doc_type="invoice")
    assert req["custom_id"] == "ticket-0001"
    p = req["params"]
    assert len(p["messages"]) == 1 and p["messages"][0]["role"] == "user"  # no multi-turn
    assert p["tools"] and p["tool_choice"] == {"type": "tool", "name": "extract_invoice"}


def test_build_batch_requests_unique_custom_ids():
    reqs = batch.build_batch_requests(DOCS)
    ids = [r["custom_id"] for r in reqs]
    assert ids == ["ticket-0001", "ticket-0002"] and len(set(ids)) == 2


def test_submit_uses_injected_client():
    captured = {}

    class FakeBatches:
        def create(self, *, requests):
            captured["n"] = len(requests)
            return Block(id="batch_123")

    class FakeClient:
        messages = Block(batches=FakeBatches())

    out = batch.submit(batch.build_batch_requests(DOCS), client=FakeClient())
    assert out.id == "batch_123" and captured["n"] == 2


# --- correlation by custom_id -----------------------------------------------


def test_correlate_succeeded_and_errored():
    results = [
        Entry("ticket-0001", Result("succeeded", message=Msg([
            Block(type="tool_use", name="extract_invoice", input={"vendor": "Acme", "total_amount": 10.0})]))),
        Entry("ticket-0002", Result("errored", error=Block(message="overloaded"))),
    ]
    out = batch.correlate_results(results)
    assert out["ticket-0001"]["status"] == "succeeded"
    assert isinstance(out["ticket-0001"]["extraction"], Invoice)
    assert out["ticket-0002"]["status"] == "errored" and out["ticket-0002"]["error"] == "overloaded"


def test_failed_ids_lists_non_succeeded():
    correlated = {"a": {"status": "succeeded"}, "b": {"status": "errored"}, "c": {"status": "expired"}}
    assert sorted(batch.failed_ids(correlated)) == ["b", "c"]


# --- resubmission + chunking ------------------------------------------------


def test_chunk_document_splits_by_size():
    assert batch.chunk_document("abcdefg", 3) == ["abc", "def", "g"]


def test_resubmit_chunks_oversized_and_passes_others_through():
    docs_by_id = {
        "big": {"custom_id": "big", "document": "x" * 50, "doc_type": "invoice"},
        "small": {"custom_id": "small", "document": "short", "doc_type": "invoice"},
    }
    reqs = batch.resubmit_requests(["big", "small"], docs_by_id, max_chars=20)
    ids = [r["custom_id"] for r in reqs]
    assert "big::chunk0" in ids and "big::chunk2" in ids  # 50/20 -> 3 chunks
    assert "small" in ids  # passed through unchunked


# --- SLA math ---------------------------------------------------------------


def test_submission_cadence_feasible_for_30h_window():
    plan = batch.submission_cadence(10_000)
    assert plan["batches"] == 1
    assert plan["slack_hours_for_resubmission"] == 6
    assert plan["feasible"] is True


def test_submission_cadence_infeasible_when_target_below_window():
    plan = batch.submission_cadence(10_000, processing_window_h=24, target_turnaround_h=20)
    assert plan["feasible"] is False


# --- runner polls + merges retry results (the dropped-results bug) -----------


class FakeBatchesAPI:
    def __init__(self, results_by_batch):
        self.results_by_batch = results_by_batch
        self._n = 0

    def create(self, *, requests):
        self._n += 1
        return Block(id=f"batch_{self._n}")

    def retrieve(self, batch_id):
        return Block(id=batch_id, processing_status="ended")  # immediate → no sleep

    def results(self, batch_id):
        return self.results_by_batch[batch_id]


class FakeClient:
    def __init__(self, results_by_batch):
        self.messages = Block(batches=FakeBatchesAPI(results_by_batch))


def test_run_backlog_polls_and_merges_retry_results():
    from scripts.run_backlog import run

    work = [
        {"custom_id": "ticket-0001", "document": "Invoice\nAcme\nTotal $10", "doc_type": "invoice"},
        {"custom_id": "ticket-0002", "document": "Order 5 cracked", "doc_type": "damage_report"},
    ]
    first = [
        Entry("ticket-0001", Result("succeeded", message=Msg([
            Block(type="tool_use", name="extract_invoice", input={"vendor": "Acme", "total_amount": 10.0})]))),
        Entry("ticket-0002", Result("errored", error=Block(message="overloaded"))),
    ]
    retry = [Entry("ticket-0002", Result("succeeded", message=Msg([
        Block(type="tool_use", name="extract_damage_report", input={"order_id": "5", "damage_type": "shipping"})])))]

    out = run(work, client=FakeClient({"batch_1": first, "batch_2": retry}))
    assert out["ticket-0001"]["status"] == "succeeded"
    assert out["ticket-0002"]["status"] == "succeeded"  # retry result merged, not dropped
