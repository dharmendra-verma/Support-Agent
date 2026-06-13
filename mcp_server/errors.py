"""Structured error responses for the MCP tools (SA-11).

A generic "operation failed" gives the agent nothing to act on, and masking a failure as an
empty result produces confidently-wrong "no records found" answers. Every *failure* returns
an MCP ``isError`` envelope with a category, an ``isRetryable`` flag, and a human-readable
(non-leaky) message — so the agent can decide: retry transient, explain business, don't
retry validation with the same input.

A genuine empty result (a successful query with no matches) is **not** an error — it is a
normal result, distinct from an access failure (timeout/auth).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class ErrorCategory(str, Enum):
    TRANSIENT = "transient"    # timeout / backend unavailable — retry may succeed
    VALIDATION = "validation"  # bad input — retrying the SAME input won't help
    BUSINESS = "business"      # policy/business rule — not retryable; explain to the customer
    PERMISSION = "permission"  # auth/access denied — not retryable as-is


# Default retryability per category — only transient failures are worth retrying.
_RETRYABLE = {
    ErrorCategory.TRANSIENT: True,
    ErrorCategory.VALIDATION: False,
    ErrorCategory.BUSINESS: False,
    ErrorCategory.PERMISSION: False,
}


@dataclass
class ToolError:
    category: ErrorCategory
    message: str                       # for the agent — decision-enabling, no internal leaks
    customer_message: str | None = None  # safe to show the customer (business errors)
    is_retryable: bool | None = None

    def __post_init__(self) -> None:
        if self.is_retryable is None:
            self.is_retryable = _RETRYABLE[self.category]

    def to_result(self) -> dict:
        out = {
            "isError": True,
            "errorCategory": self.category.value,
            "isRetryable": self.is_retryable,
            "message": self.message,
        }
        if self.customer_message:
            out["customerMessage"] = self.customer_message
        return out


# Typed failures the tools raise; the decorator maps them to envelopes.
class ValidationFailure(Exception):
    """Bad input — retrying with the same input won't help."""


class BusinessRuleViolation(Exception):
    def __init__(self, message: str, customer_message: str):
        super().__init__(message)
        self.customer_message = customer_message


class TransientFailure(Exception):
    """Timeout / backend temporarily unavailable."""


class PermissionFailure(Exception):
    """Auth/access denied."""


# --- chaos injection (fault-injection testing) ------------------------------
# Map tool name -> category to force a failure of that kind on the next call(s).
_CHAOS: dict[str, ErrorCategory] = {}
_CHAOS_MESSAGES = {
    ErrorCategory.TRANSIENT: "backend temporarily unavailable; please retry",
    ErrorCategory.PERMISSION: "not authorized to perform this operation",
    ErrorCategory.VALIDATION: "the request was invalid",
    ErrorCategory.BUSINESS: "the request violates a business rule",
}


def inject(tool_name: str, category: ErrorCategory) -> None:
    _CHAOS[tool_name] = category


def clear_chaos() -> None:
    _CHAOS.clear()


def tool_errors(func: Callable[..., dict]) -> Callable[..., dict]:
    """Wrap a tool handler so raised failures (and chaos injections) become structured
    ``isError`` envelopes. Success and valid empty results pass through unchanged."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict:
        injected = _CHAOS.get(func.__name__)
        if injected is not None:
            return ToolError(injected, _CHAOS_MESSAGES[injected]).to_result()
        try:
            return func(*args, **kwargs)
        except ValidationFailure as exc:
            return ToolError(ErrorCategory.VALIDATION, str(exc)).to_result()
        except BusinessRuleViolation as exc:
            return ToolError(ErrorCategory.BUSINESS, str(exc),
                             customer_message=exc.customer_message).to_result()
        except TransientFailure as exc:
            return ToolError(ErrorCategory.TRANSIENT, str(exc)).to_result()
        except PermissionFailure as exc:
            return ToolError(ErrorCategory.PERMISSION, str(exc)).to_result()

    return wrapper


def agent_should_retry(result: dict) -> bool:
    """The retry policy the agent loop honors: retry iff the failure is marked retryable.
    A non-error result (including a valid empty result) is never 'retried'."""
    return bool(result.get("isError")) and bool(result.get("isRetryable"))
