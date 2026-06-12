# Agent architecture (the two-path rule)

**Agentic work → Claude Agent SDK.** Production agent loops run through
`claude_agent_sdk` (`query`/`ClaudeSDKClient`, `ClaudeAgentOptions`, in-process
`@tool` + `create_sdk_mcp_server`). Do **not** hand-roll a `stop_reason` loop in
production code.

**Non-agentic work → direct Claude Messages API.** Single-shot calls (classify,
extract, summarize) use the `anthropic` SDK directly. `src/agent/loop.py` is the one
sanctioned hand-rolled loop, kept as a reference/teaching implementation.

**Anti-patterns (rejected in review):**
- Parsing the model's prose to decide completion. Drive control flow on `stop_reason`
  (reference loop) or `ResultMessage` (SDK), never on "I'm done" text.
- Iteration cap as the primary stop condition — it is a *logged safety net* only.
- Defining a tool's schema/handler twice; one source of truth, projected into both paths.

**Tokens/usage:** accounted in exactly one place per conversation. Don't double-count.
