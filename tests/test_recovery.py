"""Crash-recovery tests (SA-24): manifest persistence, kill-and-resume, scratchpads, phase
summaries. Fully offline; uses tmp_path for all on-disk state."""
from __future__ import annotations

import asyncio
import json

from research.manifest import (
    DONE,
    PENDING,
    RunManifest,
    load_manifest,
    resume_prompt,
    save_manifest,
)
from research.schemas import ContentType, Finding
from research.state import Scratchpad, next_phase_context, phase_summary


def mk(topic="t", claim="c", source="s"):
    return Finding(topic=topic, claim=claim, source=source, content_type=ContentType.OTHER)


# --- manifest persistence round-trip ----------------------------------------


def test_manifest_round_trips_through_disk(tmp_path):
    m = RunManifest.new("run-1", "what is X?", [("web", "a"), ("doc", "b")])
    m.mark_done("a", [mk(claim="found A", source="src-a")])
    save_manifest(m, tmp_path / "m.json")

    loaded = load_manifest(tmp_path / "m.json")
    assert loaded.run_id == "run-1" and loaded.query == "what is X?"
    a = next(t for t in loaded.tasks if t.scope == "a")
    assert a.status == DONE and a.findings[0].claim == "found A"
    assert next(t for t in loaded.tasks if t.scope == "b").status == PENDING


def test_save_is_atomic_no_temp_left_and_valid_json(tmp_path):
    m = RunManifest.new("run-1", "q", [("web", "a")])
    save_manifest(m, tmp_path / "m.json")
    # No temp file orphaned, and the target parses cleanly (atomic replace completed).
    assert not (tmp_path / "m.json.tmp").exists()
    json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))


def test_pending_and_completed_partition(tmp_path):
    m = RunManifest.new("r", "q", [("web", "a"), ("web", "b"), ("web", "c")])
    m.mark_done("b", [mk()])
    assert [t.scope for t in m.pending()] == ["a", "c"]
    assert [t.scope for t in m.completed()] == ["b"]
    assert not m.is_complete()


# --- kill-and-resume integration --------------------------------------------


def test_kill_and_resume_does_not_redo_completed_subtasks(tmp_path):
    path = tmp_path / "manifest.json"
    executed: list[str] = []

    async def execute(task, *, crash_on=None):
        executed.append(task.scope)
        if crash_on == task.scope:
            raise RuntimeError("simulated crash / context exhaustion")
        return [mk(claim=f"finding for {task.scope}", source=task.scope)]

    async def run(manifest, *, crash_on=None):
        # Checkpoint after EACH completed task, so a mid-run crash leaves earlier work saved.
        for task in list(manifest.pending()):
            findings = await execute(task, crash_on=crash_on)
            manifest.mark_done(task.scope, findings)
            save_manifest(manifest, path)
        return manifest

    # First run: crashes while processing "b" (after "a" was checkpointed).
    m = RunManifest.new("run-1", "q", [("web", "a"), ("web", "b"), ("web", "c")])
    save_manifest(m, path)
    try:
        asyncio.run(run(m, crash_on="b"))
    except RuntimeError:
        pass
    assert executed == ["a", "b"]                     # got through a, died on b

    # --- process restarts: reload manifest from disk ---
    resumed = load_manifest(path)
    assert [t.scope for t in resumed.completed()] == ["a"]   # a survived the crash
    assert [t.scope for t in resumed.pending()] == ["b", "c"]

    executed.clear()
    asyncio.run(run(resumed))                          # clean resume, no crash
    assert executed == ["b", "c"]                      # "a" is NOT redone
    assert resumed.is_complete()
    # All three findings present end-to-end.
    assert {f.claim for f in resumed.completed_findings()} == {
        "finding for a", "finding for b", "finding for c"}


def test_resume_prompt_injects_prior_findings(tmp_path):
    m = RunManifest.new("run-1", "original question", [("web", "a"), ("web", "b")])
    m.mark_done("a", [mk(claim="A is true", source="src-a")])
    m.phase_summaries.append("phase 1 covered the basics")
    prompt = resume_prompt(m, m.pending()[0])
    assert "original question" in prompt
    assert "A is true" in prompt and "src-a" in prompt        # prior findings injected
    assert "do NOT re-derive" in prompt
    assert "phase 1 covered the basics" in prompt


# --- scratchpad files -------------------------------------------------------


def test_scratchpad_persists_and_reads_back_key_findings(tmp_path):
    pad = Scratchpad(tmp_path / "web_search.md")
    pad.record(mk(claim="market is $2B", source="report.pdf"))
    pad.record(mk(claim="growth is 10%", source="news.com"))
    pad.note("hypothesis: demand is seasonal")

    # A fresh handle (as after a context reset) reads the durable file.
    reopened = Scratchpad(tmp_path / "web_search.md")
    keys = reopened.key_findings()
    assert "market is $2B [report.pdf]" in keys
    assert "growth is 10% [news.com]" in keys
    assert "hypothesis: demand is seasonal" in keys


def test_scratchpad_missing_file_reads_empty(tmp_path):
    assert Scratchpad(tmp_path / "none.md").key_findings() == []


# --- phase summaries injected into next phase -------------------------------


def test_phase_summary_condenses_and_caps(tmp_path):
    findings = [mk(claim=f"fact {i}", source=f"s{i}") for i in range(7)]
    summary = phase_summary("exploration", findings, max_items=3)
    assert "Phase 'exploration' (7 findings)" in summary
    assert "fact 0 [s0]" in summary
    assert "(+4 more)" in summary                     # elision is disclosed, not silent
    assert "fact 6" not in summary                    # capped


def test_phase_summary_empty():
    assert phase_summary("p", []) == "Phase 'p': no findings."


def test_next_phase_context_assembles_summaries():
    ctx = next_phase_context(["phase 1: A", "phase 2: B"])
    assert "carried forward" in ctx
    assert "- phase 1: A" in ctx and "- phase 2: B" in ctx
    assert next_phase_context([]) == ""
