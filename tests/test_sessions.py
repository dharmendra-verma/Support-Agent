"""Tests for session resumption & forking (SA-9).

All offline: persistence, fork independence, the stale-context decision (proven
deterministically per the risk note), and targeted re-analysis.
"""
from __future__ import annotations

import pytest

from agent.sessions import (
    CaseSummary,
    Session,
    SessionNotFound,
    SessionStore,
    continue_session,
    is_stale,
)


def make_session(name="case1"):
    return Session(
        name=name,
        messages=[{"role": "assistant", "content": "Your order 12345 is processing."}],
        summary=CaseSummary(customer_id="C-1001", order_id="12345",
                            notes=["customer asked about delivery"]),
        snapshots={"order:12345": {"status": "processing"}},
    )


# --- persistence / resume-by-name -------------------------------------------


def test_save_and_resume_round_trip(tmp_path):
    store = SessionStore(tmp_path)
    store.save(make_session())
    again = store.resume("case1")
    assert again.summary.customer_id == "C-1001"
    assert again.snapshots == {"order:12345": {"status": "processing"}}
    assert again.messages[0]["content"].startswith("Your order")


def test_resume_missing_raises(tmp_path):
    with pytest.raises(SessionNotFound):
        SessionStore(tmp_path).resume("nope")


# --- fork independence -------------------------------------------------------


def test_fork_is_independent(tmp_path):
    store = SessionStore(tmp_path)
    store.save(make_session())
    fork = store.fork("case1", "case1-alt")
    fork.messages.append({"role": "user", "content": "try a full refund instead"})
    fork.summary.notes.append("exploring refund path")
    store.save(fork)

    original = store.resume("case1")
    assert len(original.messages) == 1                      # original untouched on disk
    assert "exploring refund path" not in original.summary.notes
    assert len(store.resume("case1-alt").messages) == 2     # fork has its own state


# --- stale-context decision (the subtle bug + the fix) ----------------------


def test_stale_context_starts_fresh_with_durable_facts_only():
    s = make_session()
    current = {"order:12345": {"status": "shipped"}}  # world changed since the snapshot

    assert is_stale(s, current) is True

    mode, fresh = continue_session(s, current)
    assert mode == "fresh"
    fresh_ctx = " ".join(m["content"] for m in fresh.messages)
    assert "processing" not in fresh_ctx     # stale value dropped
    assert "12345" in fresh_ctx              # durable fact retained
    assert "Re-fetch" in fresh_ctx           # told to re-fetch volatile data


def test_resume_path_replays_prior_context_including_stale_value():
    """Exercises the resume branch: when NOT stale, continue_session returns the original
    session, whose history still carries the prior tool result. This is the meaningful
    contrast to the fresh path — a naive resume of a *stale* session would replay this."""
    s = make_session()
    current = {"order:12345": {"status": "processing"}}  # unchanged → resume is correct here
    assert is_stale(s, current) is False
    mode, sess = continue_session(s, current)
    assert mode == "resume" and sess is s
    assert "processing" in " ".join(m["content"] for m in sess.messages)


def test_continue_persists_fresh_when_store_given(tmp_path):
    store = SessionStore(tmp_path)
    s = make_session()
    _, fresh = continue_session(s, {"order:12345": {"status": "shipped"}}, store=store)
    assert store.exists(fresh.name)  # fresh session was saved for later resume


# --- targeted re-analysis + summary serialization ---------------------------


def test_inform_changes_appends_targeted_notice():
    s = make_session()
    s.inform_changes(["order 12345 now shipped", "tracking number issued"])
    last = s.messages[-1]
    assert last["role"] == "user"
    assert "order 12345 now shipped" in last["content"]
    assert "Re-analyze only what's affected" in last["content"]


def test_case_summary_prompt_has_durable_facts_and_refetch_note():
    p = CaseSummary(customer_id="C-1001", order_id="12345",
                    durable_facts={"plan": "gold"}, notes=["VIP"]).to_prompt()
    assert "C-1001" in p and "12345" in p and "gold" in p and "VIP" in p
    assert "Re-fetch" in p
