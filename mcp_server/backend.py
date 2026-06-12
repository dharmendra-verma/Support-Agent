"""Mock backend for the ResolveDesk MCP tools — seeded customers & orders.

In-memory JSON-style fixtures (no external DB), deterministic for tests. Lookups
raise a typed ``NotFoundError`` so the tools can surface structured, decision-enabling
errors instead of stack traces.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Refunds at or under this amount are auto-approved; above it they need a human
# (escalate_to_human). Real enforcement lands as a hook in SA-14; here it just
# shapes the tool's structured result.
REFUND_AUTO_APPROVE_LIMIT = 500.0


class NotFoundError(Exception):
    """Requested customer or order does not exist."""


@dataclass
class Backend:
    customers: dict[str, dict] = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)
    refunds: list[dict] = field(default_factory=list)
    escalations: list[dict] = field(default_factory=list)

    @classmethod
    def seeded(cls) -> "Backend":
        customers = {
            "C-1001": {"customer_id": "C-1001", "name": "Jane Doe",
                       "email": "jane@example.com", "tier": "gold"},
            "C-1002": {"customer_id": "C-1002", "name": "Raj Patel",
                       "email": "raj@example.com", "tier": "standard"},
        }
        orders = {
            "12345": {"order_id": "12345", "customer_id": "C-1001", "status": "shipped",
                      "items": ["Widget"], "total": 120.0},
            "98765": {"order_id": "98765", "customer_id": "C-1002", "status": "processing",
                      "items": ["Gadget", "Cable"], "total": 640.0},
        }
        return cls(customers=customers, orders=orders)

    def get_customer(self, identifier: str) -> dict:
        """By customer id (e.g. 'C-1001') or email (case-insensitive)."""
        if identifier in self.customers:
            return self.customers[identifier]
        for c in self.customers.values():
            if c["email"].lower() == identifier.strip().lower():
                return c
        raise NotFoundError(f"no customer matching {identifier!r}")

    def get_order(self, order_id: str) -> dict:
        """By order number; a leading '#' and surrounding space are tolerated."""
        oid = order_id.lstrip("#").strip()
        if oid in self.orders:
            return self.orders[oid]
        raise NotFoundError(f"no order with id {order_id!r}")

    def record_refund(self, order_id: str, amount: float, reason: str) -> dict:
        order = self.get_order(order_id)  # raises NotFoundError on bad order
        rec = {
            "order_id": order["order_id"], "amount": amount, "reason": reason,
            "auto_approved": amount <= REFUND_AUTO_APPROVE_LIMIT,
        }
        self.refunds.append(rec)
        return rec

    def record_escalation(self, reason: str, context: str) -> dict:
        ticket = {
            "ticket_id": f"ESC-{len(self.escalations) + 1:04d}",
            "reason": reason, "context": context,
        }
        self.escalations.append(ticket)
        return ticket
