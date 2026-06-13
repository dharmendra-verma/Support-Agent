"""Escalation criteria + structured human handoff (SA-16).

Escalation is decided by **categorical rules**, not sentiment or self-reported confidence.
Valid triggers (and ONLY these):
  1. the customer explicitly asks for a human  -> escalate immediately
  2. a policy gap / ambiguity (request outside what tools+policy allow)
  3. no meaningful progress after genuine attempts

A frustrated-but-resolvable case is RESOLVED first (acknowledge + offer a fix); it only
escalates if the customer reiterates wanting a human. Frustration alone never escalates —
over-escalation kills first-contact resolution. The same criteria are stated for the model
in ``prompts/system.md``; this module is the deterministic, testable encoding.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field


class Route(str, Enum):
    ESCALATE = "escalate"
    RESOLVE = "resolve"


@dataclass
class CaseSignals:
    """Categorical signals extracted from a case (NOT sentiment scores / confidences)."""

    explicit_human_request: bool = False  # customer asked for a person
    policy_gap: bool = False              # request outside policy or ambiguous
    no_progress: bool = False             # genuine attempts exhausted, stuck
    frustrated: bool = False              # sentiment — informs tone, never the decision alone
    customer_reiterated: bool = False     # asked again after we offered a resolution
    resolvable: bool = True               # tools/policy can resolve it


@dataclass
class EscalationDecision:
    route: Route
    reason: str


def classify_escalation(s: CaseSignals) -> EscalationDecision:
    """Apply the categorical escalation rules. Order matters: an explicit human request is
    honored before anything else."""
    if s.explicit_human_request:
        return EscalationDecision(Route.ESCALATE, "customer explicitly requested a human")
    if s.policy_gap:
        return EscalationDecision(Route.ESCALATE, "policy gap or ambiguity beyond tool authority")
    if s.no_progress:
        return EscalationDecision(Route.ESCALATE, "no meaningful progress after genuine attempts")
    if s.frustrated and s.customer_reiterated:
        return EscalationDecision(Route.ESCALATE, "customer reiterated wanting a human after an offer")
    # Frustrated-but-resolvable, or any plain resolvable case → resolve (sentiment and
    # confidence are deliberately NOT triggers).
    return EscalationDecision(Route.RESOLVE, "resolvable within tools and policy")


class HandoffPayload(BaseModel):
    """Structured context a human agent needs to act without re-asking the customer."""

    customer_id: str
    issue_summary: str
    root_cause: str
    actions_attempted: list[str]
    recommended_action: str
    amounts: dict[str, float] = Field(default_factory=dict)

    def to_context(self) -> str:
        """Render for the escalate_to_human tool's ``context`` argument."""
        lines = [
            f"customer: {self.customer_id}",
            f"issue: {self.issue_summary}",
            f"root cause: {self.root_cause}",
            f"actions attempted: {'; '.join(self.actions_attempted) or 'none'}",
            f"recommended action: {self.recommended_action}",
        ]
        if self.amounts:
            lines.append("amounts: " + ", ".join(f"{k}={v}" for k, v in self.amounts.items()))
        return "\n".join(lines)


def build_handoff(
    *,
    customer_id: str,
    issue_summary: str,
    root_cause: str,
    actions_attempted: list[str],
    recommended_action: str,
    amounts: dict[str, float] | None = None,
) -> HandoffPayload:
    """Construct a validated handoff payload (raises pydantic ValidationError if incomplete)."""
    return HandoffPayload(
        customer_id=customer_id,
        issue_summary=issue_summary,
        root_cause=root_cause,
        actions_attempted=actions_attempted,
        recommended_action=recommended_action,
        amounts=amounts or {},
    )
