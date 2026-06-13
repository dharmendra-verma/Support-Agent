"""Agent SDK hooks: refund-threshold interception + result normalization (SA-15).

Two deterministic policy hooks, enforced in the tool-dispatch layer (maps to the
claude-agent-sdk PreToolUse / PostToolUse hook API):

- **PreToolUse** — block ``process_refund`` above the autonomous limit ($500) and redirect
  to ``escalate_to_human``. Deterministic, so it blocks 100% of attempts (a prompt
  instruction would only block *most*).
- **PostToolUse** — normalize heterogeneous tool output (Unix timestamps -> ISO 8601,
  numeric/variant status codes -> canonical strings) BEFORE the model sees it. Lossless:
  the original values are preserved under a ``raw`` key.
"""
from __future__ import annotations

import copy
import datetime
from dataclasses import dataclass
from typing import Any

from mcp_server.backend import REFUND_AUTO_APPROVE_LIMIT as REFUND_LIMIT

# Fields treated as timestamps when normalizing tool results.
TIMESTAMP_FIELDS = ("created_at", "updated_at", "ordered_at", "shipped_at", "timestamp", "date")

# Numeric and variant status codes -> canonical lowercase strings.
CANONICAL_STATUS = {
    "0": "pending", "1": "processing", "2": "shipped", "3": "delivered", "4": "cancelled",
    "proc": "processing", "processing": "processing",
    "ship": "shipped", "shipped": "shipped",
    "deliv": "delivered", "delivered": "delivered",
    "pending": "pending", "cancelled": "cancelled", "canceled": "cancelled",
}


# --- PreToolUse: refund-threshold interception ------------------------------


@dataclass
class Decision:
    allow: bool
    reason: str = ""
    redirect: str | None = None


def refund_threshold_decision(tool_name: str, tool_input: dict, limit: float = REFUND_LIMIT) -> Decision:
    """Deny a ``process_refund`` above ``limit`` and redirect to escalation; else allow."""
    if tool_name == "process_refund":
        amount = tool_input.get("amount")
        if amount is not None and amount > limit:
            return Decision(
                allow=False,
                reason=f"refund of {amount} exceeds the ${limit:.0f} autonomous limit; "
                       "route to escalate_to_human for human approval",
                redirect="escalate_to_human",
            )
    return Decision(allow=True)


# --- PostToolUse: lossless normalization ------------------------------------


def _to_iso(value: Any) -> str | None:
    """Unix epoch (int/float) or ISO-ish string -> ISO 8601 UTC; else None."""
    if isinstance(value, bool):  # bool is an int subclass — never a timestamp
        return None
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc).isoformat()
    return None


def _normalize_dict(d: dict) -> None:
    """Normalize timestamp + status fields in-place, stashing originals under ``raw``."""
    raw: dict[str, Any] = {}
    for f in TIMESTAMP_FIELDS:
        if f in d:
            iso = _to_iso(d[f])
            if iso is not None and iso != d[f]:
                raw[f] = d[f]
                d[f] = iso
    if "status" in d:
        canon = CANONICAL_STATUS.get(str(d["status"]).strip().lower())
        if canon is not None and canon != d["status"]:
            raw["status"] = d["status"]
            d["status"] = canon
    if raw:
        existing = d.get("raw")
        d["raw"] = {**(existing if isinstance(existing, dict) else {}), **raw}


def normalize_result(result: Any) -> Any:
    """Return a normalized copy of a tool result (top level + known nested records).
    Non-dict results pass through unchanged."""
    if not isinstance(result, dict):
        return result
    out = copy.deepcopy(result)
    _normalize_dict(out)
    for nested in ("order", "customer", "refund"):
        if isinstance(out.get(nested), dict):
            _normalize_dict(out[nested])
    return out


# --- dispatch integration (hooks in the loop) -------------------------------


def hooked_dispatch(tool_name: str, tool_input: dict, *, handlers: dict, limit: float = REFUND_LIMIT) -> dict:
    """Apply the PreToolUse gate, run the handler only if allowed, then PostToolUse
    normalization. An over-limit refund NEVER reaches the handler."""
    decision = refund_threshold_decision(tool_name, tool_input, limit)
    if not decision.allow:
        return {"ok": False, "error": "blocked_by_policy",
                "redirect": decision.redirect, "detail": decision.reason}
    return normalize_result(handlers[tool_name](**tool_input))


# --- claude-agent-sdk hook adapters -----------------------------------------
# Shaped for the SDK PreToolUse/PostToolUse hook API. Plain async (no SDK import), so the
# decision wiring is unit-testable; build_hooks_config() does the SDK-specific wiring.


async def pre_tool_use_hook(input_data: dict, *_: Any) -> dict:
    decision = refund_threshold_decision(input_data.get("tool_name", ""),
                                         input_data.get("tool_input") or {})
    if not decision.allow:
        return {"decision": "block", "reason": decision.reason, "redirect": decision.redirect}
    return {}


async def post_tool_use_hook(input_data: dict, *_: Any) -> dict:
    result = input_data.get("tool_response", input_data.get("tool_result"))
    return {"updated_tool_result": normalize_result(result)}


def build_hooks_config() -> Any:
    """Wire the hooks into ClaudeAgentOptions(hooks=...) — lazy import (SDK not in CI)."""
    from claude_agent_sdk import HookMatcher

    return {
        "PreToolUse": [HookMatcher(matcher="process_refund", hooks=[pre_tool_use_hook])],
        "PostToolUse": [HookMatcher(hooks=[post_tool_use_hook])],
    }
