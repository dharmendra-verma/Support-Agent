"""Structured error tests (SA-11): the 4 categories, retryability, fault injection, and the
crucial distinction between an access failure and a valid empty result.
"""
from __future__ import annotations

import pytest

from mcp_server import server
from mcp_server.errors import (
    ErrorCategory,
    ToolError,
    agent_should_retry,
    clear_chaos,
    inject,
)


@pytest.fixture(autouse=True)
def _no_chaos():
    clear_chaos()
    yield
    clear_chaos()


# --- envelope shape + per-category retryability -----------------------------


@pytest.mark.parametrize("category,retryable", [
    (ErrorCategory.TRANSIENT, True),
    (ErrorCategory.VALIDATION, False),
    (ErrorCategory.BUSINESS, False),
    (ErrorCategory.PERMISSION, False),
])
def test_envelope_metadata_per_category(category, retryable):
    out = ToolError(category, "msg").to_result()
    assert out["isError"] is True
    assert out["errorCategory"] == category.value
    assert out["isRetryable"] is retryable
    assert out["message"] == "msg"


# --- validation ------------------------------------------------------------


def test_validation_error_on_bad_input():
    out = server.lookup_order("")
    assert out["isError"] and out["errorCategory"] == "validation"
    assert out["isRetryable"] is False  # same input won't help


def test_refund_non_positive_amount_is_validation():
    out = server.process_refund("12345", 0, "x")
    assert out["errorCategory"] == "validation"


# --- business --------------------------------------------------------------


def test_business_error_not_retryable_with_customer_message():
    out = server.process_refund("12345", 200.0, "overpay")  # 200 <= $500 but > order total 120
    assert out["isError"] and out["errorCategory"] == "business"
    assert out["isRetryable"] is False
    assert "customerMessage" in out
    # customer-facing text must not leak internals (amounts/ids are fine; no raw dumps)
    assert "Traceback" not in out["customerMessage"]


# --- access failure vs valid empty result ----------------------------------


def test_not_found_is_a_valid_empty_result_not_an_error():
    out = server.get_customer("nobody@nowhere.com")  # query succeeded, no match
    assert "isError" not in out
    assert out["ok"] is False and out["error"] == "not_found"


def test_transient_access_failure_is_error_and_retryable():
    inject("lookup_order", ErrorCategory.TRANSIENT)
    out = server.lookup_order("12345")
    assert out["isError"] and out["errorCategory"] == "transient"
    assert out["isRetryable"] is True


def test_permission_access_failure_is_error_not_retryable():
    inject("get_customer", ErrorCategory.PERMISSION)
    out = server.get_customer("C-1001")
    assert out["isError"] and out["errorCategory"] == "permission"
    assert out["isRetryable"] is False


# --- agent retry policy per category ----------------------------------------


def test_agent_retry_policy():
    inject("lookup_order", ErrorCategory.TRANSIENT)
    assert agent_should_retry(server.lookup_order("12345")) is True          # retry transient
    clear_chaos()
    assert agent_should_retry(server.process_refund("12345", 200.0, "x")) is False  # explain business
    assert agent_should_retry(server.lookup_order("")) is False              # never retry validation
    assert agent_should_retry(server.get_customer("nobody@x.com")) is False  # empty result, not a retry


# --- success unchanged ------------------------------------------------------


def test_success_paths_have_no_iserror():
    assert "isError" not in server.get_customer("C-1001")
    assert "isError" not in server.lookup_order("12345")
    assert "isError" not in server.process_refund("12345", 40.0, "ok")
