#!/usr/bin/env python
"""InstructionsLoaded hook — SA-25 verification aid.

Claude Code fires the `InstructionsLoaded` event whenever a CLAUDE.md or
`.claude/rules/*.md` file is pulled into context. This hook appends one line per
load to `.claude/instructions-loaded.log` (gitignored) so we can prove which
memory/rules files loaded and *why* (`load_reason`: session_start, include,
nested_traversal, path_glob_match, compact).

The hook event arrives as JSON on stdin. We log the whole event verbatim so the
record is correct regardless of field-name changes across versions.

To disable: remove the InstructionsLoaded entry from .claude/settings.local.json
(the personal, gitignored file where this hook is registered — see
docs/claude-code-setup.md §4).
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys


def main() -> None:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {"_unparsed_stdin": raw}

    log_path = pathlib.Path(__file__).resolve().parents[1] / "instructions-loaded.log"
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {json.dumps(event, default=str, ensure_ascii=False)}\n")


if __name__ == "__main__":
    main()
