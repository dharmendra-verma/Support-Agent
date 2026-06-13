"""Document extractor (SA-17).

Runs extraction via the Messages API tool_use pattern: the model is given the extract_*
tools and must *call* the right one; the structured result is read from the returned
``tool_use`` block and validated against the Pydantic model. ``tool_choice`` is forced when
the document type is known, and ``"any"`` when it must be inferred across schemas.

The live model call needs an API key (skipped offline). The contract — tool defs,
tool_choice selection, and parsing/validation of a tool_use block — is fully unit-tested.
"""
from __future__ import annotations

from typing import Any

from extraction.schemas import DOC_MODELS, tool_defs, tool_name

# Normalization rules the model must follow (currencies, dates, categoricals).
NORMALIZATION_PROMPT = (
    "Extract the document's fields by calling the matching extract_* tool. Rules:\n"
    "- Use null for any field the document does not contain. NEVER fabricate or guess a value.\n"
    "- Currencies: ISO 4217 code (USD, EUR, GBP); use 'other' with currency_other for anything "
    "else, or 'unclear' if ambiguous. Amounts as plain decimals (e.g. 1234.50) — no currency "
    "symbols and no thousands separators.\n"
    "- Dates: ISO 8601 (YYYY-MM-DD).\n"
    "- Categorical fields: use 'unclear' when the document is ambiguous, and 'other' (with the "
    "matching *_other detail field) when no listed value fits."
)


def tool_choice(doc_type: str | None) -> dict:
    """Forced tool when the type is known; ``any`` (must call some extract_*) when unknown."""
    if doc_type:
        return {"type": "tool", "name": tool_name(doc_type)}
    return {"type": "any"}


def parse_extraction(response: Any, doc_type: str | None = None):
    """Read the structured result from the response's tool_use block and validate it against
    the matching Pydantic model. The doc type is inferred from the tool name when not given."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            resolved = doc_type or block.name.removeprefix("extract_")
            model = DOC_MODELS[resolved]
            return model.model_validate(block.input)
    raise ValueError("response contained no tool_use block")


def extract(document: str, *, doc_type: str | None = None, client: Any = None,
            model: str = "claude-sonnet-4-6"):
    """Extract structured data from a document. ``client`` is injectable for tests."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=NORMALIZATION_PROMPT,
        tools=tool_defs(),
        tool_choice=tool_choice(doc_type),
        messages=[{"role": "user", "content": document}],
    )
    return parse_extraction(resp, doc_type)
