"""Programmatic prerequisite gate (SA-14).

Deterministic enforcement in the **tool-dispatch layer**, not the prompt. Financial /
data tools (`lookup_order`, `process_refund`) are blocked until `get_customer` has
verified a *single* customer in this session. A prompt instruction ("always verify
first") has a non-zero failure rate; a dispatch-layer gate is 0% by construction —
the model literally cannot reach the tool until the prerequisite is met.

Verification is never heuristic: an ambiguous match (more than one customer) returns a
request for additional identifiers instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

# Tools that require a verified customer first. get_customer is the verifier itself;
# escalate_to_human is intentionally NOT gated (a human handoff must always be reachable).
GATED_TOOLS = frozenset({"lookup_order", "process_refund"})


@dataclass
class SessionGate:
    """Per-session state: which customer (if any) has been verified."""

    verified_customer_id: str | None = None

    def verify(self, matches: list[dict]) -> dict:
        """Process a customer lookup result. Sets verification only on a *unique* match.

        - 0 matches  -> not_found (no verification)
        - >1 matches -> ambiguous; ask for a unique identifier (NEVER pick one)
        - 1 match    -> verified; record the id (a re-verify switches customers)
        """
        if not matches:
            return {"ok": False, "error": "not_found", "verified": False,
                    "detail": "no customer matched; ask for a customer id or email"}
        if len(matches) > 1:
            return {"ok": False, "error": "ambiguous_customer", "verified": False,
                    "detail": "multiple customers match; ask for a unique id or email — do not guess",
                    "candidates": [m["customer_id"] for m in matches]}
        self.verified_customer_id = matches[0]["customer_id"]
        return {"ok": True, "verified": True, "customer": matches[0]}

    def check(self, tool_name: str) -> dict | None:
        """Return a structured *block* result if the tool is gated and no customer is
        verified yet; otherwise None (the call is allowed)."""
        if tool_name in GATED_TOOLS and self.verified_customer_id is None:
            return {"ok": False, "error": "prerequisite_unmet", "missing": "verified_customer",
                    "detail": f"verify the customer with get_customer before calling {tool_name}"}
        return None

    def reset(self) -> None:
        """Clear verification (e.g. on an explicit customer switch / new session)."""
        self.verified_customer_id = None


def guarded_dispatch(
    gate: SessionGate,
    name: str,
    tool_input: dict[str, Any],
    *,
    handlers: dict[str, Callable[..., dict]],
    resolve_customers: Callable[[str], list[dict]],
) -> dict:
    """Run a tool through the gate — this is the enforcement point.

    - ``get_customer`` -> verify (sets/updates session verification)
    - a gated tool with no verified customer -> structured block (handler NOT called)
    - anything else -> dispatch to the handler
    """
    if name == "get_customer":
        return gate.verify(resolve_customers(tool_input.get("identifier", "")))
    blocked = gate.check(name)
    if blocked is not None:
        return blocked
    return handlers[name](**tool_input)


def backend_resolver(backend: Any) -> Callable[[str], list[dict]]:
    """Default customer resolver over a seeded backend: matches by exact customer id,
    exact email (case-insensitive), or name substring — so a bare name can be ambiguous."""

    def resolve(identifier: str) -> list[dict]:
        ident = (identifier or "").strip()
        if not ident:
            return []
        matches = []
        for c in backend.customers.values():
            if (ident == c["customer_id"]
                    or ident.lower() == c["email"].lower()
                    or ident.lower() in c["name"].lower()):
                matches.append(c)
        return matches

    return resolve
