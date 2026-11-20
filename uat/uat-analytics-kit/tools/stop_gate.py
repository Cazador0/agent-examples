#!/usr/bin/env python3
"""Optional Stop hook: do not let a run end while the ledger fails validation.

OPT-IN. Nothing uses this until you add the hook shown in the README.

Claude Code sends the hook's input as JSON on stdin. Exit code 2 blocks the
stop and sends stderr back to the agent as its next instruction; exit code 0
lets the run end.

Loop guard: when the input says stop_hook_active is true, the agent is already
continuing because of a stop hook, so this script lets it stop. Without that,
a ledger the agent cannot repair would keep the run alive forever.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        event = {}
    if event.get("stop_hook_active"):
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".")
    script = root / ".claude" / "skills" / "uat-ledger" / "scripts" / "uat_ledger.py"
    bugs = root / "ledger" / "bugs.jsonl"
    if not script.exists() or not bugs.exists() or bugs.stat().st_size == 0:
        return 0                                  # nothing to check yet
    run = subprocess.run([sys.executable, str(script), "validate", "--root", str(root)],
                         capture_output=True, text=True)
    if run.returncode == 0:
        return 0
    try:
        errors = json.loads(run.stdout).get("errors", [])
    except Exception:
        errors = [run.stdout.strip() or run.stderr.strip()]
    shown = "\n".join(f"- {e}" for e in errors[:15])
    more = f"\n(and {len(errors) - 15} more)" if len(errors) > 15 else ""
    sys.stderr.write("The ledger does not validate. Fix these, run the validator again, then finish. "
                     "If one cannot be fixed, say so under limitations.\n" + shown + more + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
