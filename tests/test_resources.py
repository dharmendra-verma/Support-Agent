"""Tests for the policy catalog resources + MCP config scoping (SA-12)."""
from __future__ import annotations

import json
from pathlib import Path

from mcp_server.backend import REFUND_AUTO_APPROVE_LIMIT
from mcp_server.resources import (
    POLICY_CATALOG,
    REFUND_POLICY_URI,
    RETURNS_POLICY_URI,
    refund_policy,
    register_resources,
    returns_policy,
)


# --- catalog content (rendered from the same constants the tools enforce) ----


def test_refund_policy_states_limit_and_verify_first():
    text = refund_policy()
    assert f"${REFUND_AUTO_APPROVE_LIMIT:.0f}" in text     # limit not drifted from backend
    assert "escalate_to_human" in text
    assert "exceed the order total" in text
    assert "verified" in text


def test_returns_policy_states_window():
    text = returns_policy()
    assert "30 days" in text and "non-returnable" in text


def test_catalog_uris_are_stable():
    assert REFUND_POLICY_URI == "resolvedesk://policy/refund"
    assert RETURNS_POLICY_URI == "resolvedesk://policy/returns"
    assert {uri for uri, _ in POLICY_CATALOG.values()} == {REFUND_POLICY_URI, RETURNS_POLICY_URI}


def test_register_resources_on_real_fastmcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP("test")
    register_resources(mcp)  # must not raise; registers both policy resources


# --- project-scoped .mcp.json: valid, env-expanded, no committed secrets -----


def test_mcp_json_is_valid_and_uses_env_expansion_without_secrets():
    cfg = json.loads(Path(".mcp.json").read_text(encoding="utf-8"))
    server = cfg["mcpServers"]["resolvedesk"]
    assert server["type"] == "stdio"
    assert server["args"] == ["-m", "mcp_server.server"]
    token = server["env"]["RESOLVEDESK_API_TOKEN"]
    assert token.startswith("${") and token.endswith("}")  # placeholder, not a real secret


def test_mcp_json_has_no_obvious_committed_secret():
    raw = Path(".mcp.json").read_text(encoding="utf-8")
    for leak in ("sk-ant-", "Bearer ", "AKIA"):
        assert leak not in raw
