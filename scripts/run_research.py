"""Live CLI runner for the multi-agent research coordinator (SA-39).

A user runs this with a research question; the process **blocks** while
``research.coordinator.run_research`` decomposes it, spawns role-scoped subagents in parallel
(one ``Task`` per subtask, fanned out concurrently by ``asyncio.gather``), synthesises their
findings, and refines any unmet criteria. When every subagent across every round has returned,
the final source-attributed answer, the rounds taken, and any unmet coverage gaps are printed.

This is a thin ``asyncio.run`` shell over ``run_research`` (the orchestration lives there; the
real SDK adapters live in ``research.runner``). Live runs need ``ANTHROPIC_API_KEY`` and lazily
import the SDK (same pattern as ``scripts/run_backlog.py``); ``--dry-run`` exercises the whole
flow offline with a fake spawner.

Usage:
    python -m scripts.run_research "What is the latest on X?" --criteria price --criteria eta
    python -m scripts.run_research "..." --dry-run --json
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from research.runner import (
    dry_run_spawn_fn,
    format_result,
    make_spawn_fn,
    make_synthesize_fn,
)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="run_research", description="Run a research question through the coordinator.")
    ap.add_argument("question", help="the research question to answer")
    ap.add_argument("--max-rounds", type=int, default=3,
                    help="refinement-round cap — a safety net, not the primary stop (default 3)")
    ap.add_argument("--criteria", action="append", default=[],
                    help="a coverage criterion the answer must satisfy; repeatable or "
                         "comma-separated. Unmet criteria drive refinement rounds and are "
                         "reported as gaps.")
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="per-subtask timeout in seconds — a hung subagent never hangs the CLI")
    ap.add_argument("--dry-run", action="store_true",
                    help="run fully offline with a fake spawner (no SDK, no API key)")
    ap.add_argument("--json", action="store_true", help="emit the result as JSON")
    return ap


def _parse_criteria(values: list[str]) -> list[str]:
    """Flatten repeated and comma-separated ``--criteria`` into a clean list."""
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def main(argv: list[str] | None = None, *, spawn_fn=None, synthesize_fn=None) -> int:
    """Parse args, build the spawn/synthesise pair, and block on ``run_research``.

    ``spawn_fn``/``synthesize_fn`` are injectable so tests drive the CLI end-to-end with fakes,
    fully offline. When not injected: ``synthesize_fn`` is the real (deterministic) synthesiser;
    ``spawn_fn`` is the fake dry-run spawner under ``--dry-run``, otherwise the live SDK spawner
    gated on ``ANTHROPIC_API_KEY``.
    """
    args = _build_parser().parse_args(argv)
    criteria = _parse_criteria(args.criteria)

    if synthesize_fn is None:
        synthesize_fn = make_synthesize_fn()
    if spawn_fn is None:
        if args.dry_run:
            spawn_fn = dry_run_spawn_fn
        elif not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set; pass --dry-run for an offline demo.",
                  file=sys.stderr)
            return 2
        else:
            spawn_fn = make_spawn_fn(per_subtask_timeout=args.timeout)

    # Import here so the module loads without the SDK on the path; run_research itself is
    # SDK-free, but keeping the import local mirrors the lazy pattern everywhere else.
    from research.coordinator import run_research

    result = asyncio.run(run_research(
        args.question,
        spawn_fn=spawn_fn,
        synthesize_fn=synthesize_fn,
        criteria=criteria,
        max_rounds=args.max_rounds,
    ))
    print(format_result(result, as_json=args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
