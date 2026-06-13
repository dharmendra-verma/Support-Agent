"""Tests for tool distribution + tool_choice strategies (SA-13)."""
from __future__ import annotations

from agent import tooling


# --- tool_choice builders ---------------------------------------------------


def test_tool_choice_builder_shapes():
    assert tooling.auto() == {"type": "auto"}
    assert tooling.any_tool() == {"type": "any"}
    assert tooling.none() == {"type": "none"}
    assert tooling.force("get_customer") == {"type": "tool", "name": "get_customer"}


# --- per-role tool distribution (small, role-relevant) ----------------------


def test_roles_are_small_for_selection_reliability():
    for role, names in tooling.ROLE_TOOLS.items():
        assert len(names) <= 5, f"{role} has {len(names)} tools (>5 hurts selection)"


def test_verification_role_has_only_get_customer():
    schemas = tooling.tools_for("verification")
    assert [s["name"] for s in schemas] == ["get_customer"]


def test_refunds_role_has_the_action_tools():
    names = {s["name"] for s in tooling.tools_for("refunds")}
    assert names == {"get_customer", "lookup_order", "process_refund", "escalate_to_human"}


def test_tools_for_returns_full_schemas():
    schema = tooling.tools_for("verification")[0]
    assert "description" in schema and "input_schema" in schema


# --- constrained workflow: verification forced first ------------------------


def test_refund_workflow_forces_verification_first():
    steps = tooling.refund_workflow_steps()
    assert steps[0]["step"] == "verify"
    assert steps[0]["tool_choice"] == {"type": "tool", "name": "get_customer"}
    # step 1 only exposes the verification tool, so nothing else can run first
    assert [t["name"] for t in steps[0]["tools"]] == ["get_customer"]


def test_workflow_second_step_requires_a_tool_no_text():
    steps = tooling.refund_workflow_steps()
    assert steps[1]["tool_choice"] == {"type": "any"}  # must act, never a text-only reply


def test_workflow_steps_are_chained_turns():
    # forced/any choice only governs one response → distinct steps, each its own turn
    steps = tooling.refund_workflow_steps()
    assert [s["step"] for s in steps] == ["verify", "find_order", "resolve"]


# --- scoped narrow tool -----------------------------------------------------


def test_check_refund_status_schema_is_narrow():
    schema = tooling.CHECK_REFUND_STATUS_SCHEMA
    assert schema["name"] == "check_refund_status"
    assert set(schema["input_schema"]["properties"]) == {"order_id"}
    assert "lookup_order" in schema["description"]  # states the boundary vs the generic tool


def test_check_refund_status_returns_only_status():
    out = tooling.check_refund_status("12345")
    assert out["ok"] is True
    assert out == {"ok": True, "order_id": "12345", "status": "shipped"}  # no items/total


def test_check_refund_status_propagates_not_found():
    out = tooling.check_refund_status("0000")
    assert out["ok"] is False and out["error"] == "not_found"  # not a confidently-wrong empty


# --- co-registration: every advertised tool is runnable ---------------------


def test_every_offered_schema_has_a_handler():
    """Guard: never advertise a tool the dispatcher can't run."""
    for schema in tooling.ALL_SCHEMAS:
        assert schema["name"] in tooling.HANDLERS, f"{schema['name']} has no handler"


def test_handlers_dispatch_the_scoped_tool():
    assert tooling.HANDLERS["check_refund_status"]("12345")["status"] == "shipped"
