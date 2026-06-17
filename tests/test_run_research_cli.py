"""End-to-end tests for the live research CLI (SA-39). Fully offline — no SDK, no network.

The CLI shell (``scripts/run_research.py``) and the real adapters (``research.runner``) are
exercised with an injected fake spawn/synthesise pair, so the blocking decompose → spawn →
synthesise → refine flow is driven without the Agent SDK or any API key. Coroutines run via
``asyncio.run`` (no pytest-asyncio). The live SDK path is gated on ``ANTHROPIC_API_KEY`` and is
not exercised here by design.
"""
from __future__ import annotations

import asyncio

import scripts.run_research as cli
from research.agents import COORDINATOR, subagent
from research.coordinator import Subtask
from research.runner import (
    RECORD_FINDING_TOOL,
    FindingCollector,
    _with_finding,
    finding_enabled_specs,
    findings_from_json,
    findings_to_json,
    format_result,
    make_spawn_fn,
    make_synthesize_fn,
)
from research.schemas import FINDING_INSTRUCTIONS, Finding


# --- fakes ------------------------------------------------------------------


def _finding(scope: str, *, source: str = "fake://src", value: str | None = None) -> Finding:
    return Finding(topic=scope, claim=f"finding for {scope}", source=source, value=value)


def _spawn_recording(calls: list[str]):
    async def spawn(subtask):
        calls.append(f"{subtask.role}:{subtask.scope}")
        return findings_to_json([_finding(subtask.scope)])

    return spawn


# --- CLI end-to-end: a single blocking final result -------------------------


def test_cli_blocks_and_prints_one_final_result(capsys):
    calls: list[str] = []

    async def synth(findings):
        return "final synthesised answer"

    rc = cli.main(["Tell me about quokkas"], spawn_fn=_spawn_recording(calls), synthesize_fn=synth)
    out = capsys.readouterr().out

    assert rc == 0
    assert calls == ["web_search:external/public information and current state of the world"]
    assert "final synthesised answer" in out
    assert "Rounds: 1" in out
    assert "Coverage gaps: none" in out


def test_cli_reports_unmet_gaps_after_refinement(capsys):
    rounds_seen = {"n": 0}

    async def synth(findings):
        rounds_seen["n"] += 1
        return "answer that never covers the criterion"

    rc = cli.main(
        ["latest online pricing", "--criteria", "unobtainium", "--max-rounds", "2"],
        spawn_fn=_spawn_recording([]), synthesize_fn=synth,
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert rounds_seen["n"] == 2          # capped — the criterion is never met
    assert "Rounds: 2" in out
    assert "Unmet coverage gaps:" in out
    assert "unobtainium" in out


def test_cli_criteria_flag_accepts_comma_and_repeats(capsys):
    async def synth(findings):
        return "covers price only"

    # find_gaps sees which criteria were threaded through: availability stays unmet.
    cli.main(
        ["q", "--criteria", "price,availability", "--criteria", "stock", "--max-rounds", "1"],
        spawn_fn=_spawn_recording([]), synthesize_fn=synth,
    )
    out = capsys.readouterr().out
    # Both the comma-split and the repeated flag reach the gap report.
    assert "availability" in out and "stock" in out
    assert "price" not in out.split("Unmet coverage gaps:")[-1]  # price WAS covered


def test_cli_json_output_is_machine_readable(capsys):
    import json

    async def synth(findings):
        return "answer-text"

    rc = cli.main(["q", "--json"], spawn_fn=_spawn_recording([]), synthesize_fn=synth)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload == {"answer": "answer-text", "rounds": 1, "gaps": []}


# --- parallel fan-out: subtasks run concurrently, not serially --------------


def test_subtasks_for_a_round_run_concurrently(capsys):
    state = {"active": 0, "max_active": 0}

    async def spawn(subtask):
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        await asyncio.sleep(0.02)         # hold the slot so a serial run would show max_active==1
        state["active"] -= 1
        return findings_to_json([_finding(subtask.scope)])

    async def synth(findings):
        return "merged"

    # A two-angle question decomposes into two researcher subtasks (web_search + doc_search).
    cli.main(
        ["Compare our internal policy docs with the latest online news"],
        spawn_fn=spawn, synthesize_fn=synth,
    )
    assert state["max_active"] == 2       # both subtasks were in flight at once (gather fan-out)


# --- live gating: no key, not dry-run -> clean refusal ----------------------


def test_live_run_without_api_key_refuses(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cli.main(["a question"])         # no injected spawn_fn, no --dry-run
    err = capsys.readouterr().err

    assert rc == 2
    assert "ANTHROPIC_API_KEY" in err
    assert "--dry-run" in err


def test_dry_run_works_fully_offline(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cli.main(["Tell me about quokkas", "--dry-run"])  # real synth + fake spawner
    out = capsys.readouterr().out

    assert rc == 0
    assert "dry-run" in out               # the simulated finding's source/claim is rendered
    assert "Rounds: 1" in out


# --- provenance survives the JSON bridge ------------------------------------


def test_synthesize_fn_preserves_conflicting_sources_side_by_side():
    # Two sources report different values for the same topic on the same (absent) date -> a
    # genuine conflict that synthesis must surface side by side, never collapse.
    a = Finding(topic="refund window", claim="30 days", source="policy-A", value="30")
    b = Finding(topic="refund window", claim="14 days", source="policy-B", value="14")
    findings = {
        "doc_search:internal": findings_to_json([a]),
        "web_search:external": findings_to_json([b]),
    }
    answer = asyncio.run(make_synthesize_fn()(findings))

    assert "contested" in answer
    assert "policy-A" in answer and "policy-B" in answer
    assert "30" in answer and "14" in answer


def test_findings_json_round_trip_and_tolerant_parsing():
    import json

    original = [_finding("scope-1"), _finding("scope-2", source="other://x", value="42")]
    restored = findings_from_json(findings_to_json(original))
    assert [f.model_dump() for f in restored] == [f.model_dump() for f in original]
    # Every degenerate blob is a valid-empty result, not a crash (the synthesis step must never
    # die mid-run on a bad blob).
    assert findings_from_json("") == []
    assert findings_from_json("not json") == []                       # not JSON at all
    assert findings_from_json('{"topic": "t"}') == []                 # valid JSON, but not a list
    assert findings_from_json('[{"topic": "x"}]') == []               # list item missing required fields
    # A malformed item is dropped; well-formed siblings still come through.
    mixed = json.dumps([_finding("ok").model_dump(mode="json"), {"topic": "bad"}])
    assert [f.topic for f in findings_from_json(mixed)] == ["ok"]


# --- augmentation is single-sourced; the wiring test guards the live path ----


def test_with_finding_is_single_source_for_subagent_augmentation():
    base = subagent("web_search")
    aug = _with_finding(base)
    # record_finding added to the role's tiny toolset; the role tools are preserved.
    assert aug.tools == base.tools + (RECORD_FINDING_TOOL,)
    # The shared, purpose-built instructions are appended (not the tool's own description).
    assert FINDING_INSTRUCTIONS in aug.prompt
    # finding_enabled_specs() (asserted offline) is built from the SAME helper the live
    # build_spawn_options() path uses, so the invariant view can't drift from production.
    by_name = {s.name: s for s in finding_enabled_specs()}
    assert by_name["web_search"] == aug


# --- the real spawn loop is now drivable offline (collector + timeout) -------


def test_make_spawn_fn_drives_the_collector_offline():
    seen: list[FindingCollector] = []

    def fake_wiring(subtask, model):
        collector = FindingCollector()
        seen.append(collector)
        return collector, object()                # opaque options stand-in, never touched offline

    async def fake_query(*, prompt, options):
        # Stand in for the SDK: the subagent calls record_finding once, then the turn ends.
        seen[-1].add({"topic": "t", "claim": "c", "source": "s"})
        return
        yield                                      # noqa: unreachable — makes this an async generator

    spawn = make_spawn_fn(query_fn=fake_query, wiring_factory=fake_wiring)
    blob = asyncio.run(spawn(Subtask(role="web_search", scope="sc", prompt="p")))

    assert [f.claim for f in findings_from_json(blob)] == ["c"]


def test_make_spawn_fn_times_out_without_hanging_and_returns_partial():
    def fake_wiring(subtask, model):
        return FindingCollector(), object()

    async def slow_query(*, prompt, options):
        await asyncio.sleep(10)                    # never finishes within the timeout
        yield

    spawn = make_spawn_fn(query_fn=slow_query, wiring_factory=fake_wiring,
                          per_subtask_timeout=0.01)
    # Returns (does not hang or raise) with whatever was collected — here, nothing.
    blob = asyncio.run(spawn(Subtask(role="web_search", scope="sc", prompt="p")))
    assert findings_from_json(blob) == []


# --- wiring invariant: coordinator owns Task; subagents stay role-scoped -----


def test_coordinator_only_tool_is_task_and_subagents_get_record_finding():
    # The coordinator that drives the live spawn still delegates with Task only.
    assert COORDINATOR.tools == ("Task",)

    by_name = {spec.name: spec for spec in finding_enabled_specs()}

    # The merge-only synthesis role gains no tools (it does no research/recording).
    assert by_name["synthesis"].tools == subagent("synthesis").tools == ()

    # Every researcher keeps its tiny role-scoped set and gains exactly record_finding.
    for name in ("web_search", "doc_search", "document_analysis"):
        base = subagent(name).tools
        enabled = by_name[name].tools
        assert enabled == base + (RECORD_FINDING_TOOL,)
        assert len(base) <= 3             # role-scoped: still small (selection reliability)


def test_format_result_renders_answer_rounds_and_gaps():
    from research.coordinator import ResearchResult

    result = ResearchResult(answer="the answer", rounds=2, gaps=["x", "y"])
    text = format_result(result)
    assert "the answer" in text and "Rounds: 2" in text
    assert "  - x" in text and "  - y" in text
