"""Command-line entry point for the student agent.

Run from the my-agent folder:
    python -m student_agent --root ../target-service --task "..."

The CLI is the "wiring" layer. It owns everything that involves the human:
reading arguments, asking for bash approval, printing progress, and writing
the log file. Agent logic and security live in agent.py and runtime.py, so
those stay testable without a terminal.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .agent import run_agent
from .model import OllamaModel
from .runtime import Runtime

# This file is my-agent/student_agent/cli.py, so parents[1] is my-agent and
# parents[2] is the lab package folder.
AGENT_DIR = Path(__file__).resolve().parents[1]
LAB_DIR = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = LAB_DIR / "fixtures" / "decimal-offline.txt"


def build_parser():
    parser = argparse.ArgumentParser(description="Run the Week 1 coding agent")
    parser.add_argument("--root", required=True, help="target workspace")
    parser.add_argument(
        "--mode",
        choices=("read-only", "edit"),
        default="read-only",
    )
    parser.add_argument("--tools", help="comma-separated enabled tools (default: all)")
    # Model is configurable via flag or OLLAMA_MODEL env var, never hard-coded
    # in the loop (handout requirement).
    parser.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b"),
    )
    # --offline alone uses the Decimal fixture; --offline <file> uses another one
    # (e.g. fixtures/web-injected.txt for the injection exercise).
    parser.add_argument(
        "--offline",
        nargs="?",
        const=str(DEFAULT_FIXTURE),
        metavar="FIXTURE",
        help="replace fetch_url responses with a local fixture file",
    )
    parser.add_argument("--task", required=True)
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--log", help="JSONL trace file (default: my-agent/runs/<time>.jsonl)")
    return parser


# ---- logging ----
#
# Every event from the loop (and every approval decision) goes to two places:
# - the JSONL file: one complete JSON object per line, for reading afterwards;
# - the console: one short line, so you can follow the run live.
# The log must live OUTSIDE the target, otherwise the agent's own logging would
# show up as a task change in `git status` (and the agent could read/edit it).


class Logger:
    # The file is opened on the first event, not here: a run that fails at
    # startup (e.g. a typo in --tools) leaves no empty log behind.
    def __init__(self, path):
        self.path = path
        self.file = None

    # Called like a function: this object IS the `emit` callback for run_agent.
    def __call__(self, event):
        if self.file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Line-buffered (buffering=1): each line hits the disk immediately,
            # so the log is complete even if the run is killed.
            self.file = open(self.path, "a", encoding="utf-8", buffering=1)
        event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        self.file.write(json.dumps(event, default=str) + "\n")
        print_event(event)

    def close(self):
        if self.file is not None:
            self.file.close()


def short(value, limit=160):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "..."


def print_event(event):
    kind = event.get("type")
    turn = f"[turn {event.get('turn')}]"
    if kind == "request":
        action = event["action"]
        print(f"{turn} -> {action['tool']} {short(action.get('args', {}))}")
    elif kind == "result":
        result = event["result"]
        print(f"{' ' * len(turn)} <- {result['status']}: {short(result['output'])}")
    elif kind == "parse_error":
        print(f"{turn} !! unusable reply: {event['error']}")
    elif kind == "approval":
        print(f"   approval: {'APPROVED' if event['approved'] else 'denied'}")
    elif kind == "stop":
        print(f"== stopped: {event['termination']} after {event['turns']} turn(s)")


# ---- bash approval ----
#
# The runtime calls approve(command, cwd) before every bash command. It has to
# be a real human decision:
# - show the complete command and the working directory;
# - only the exact answer "yes" approves. Empty input, "y", "Yes", anything
#   else means denied;
# - EOF (stdin closed or piped empty) means denied. input() raises EOFError then.
# The model never sees this prompt and cannot answer it: its replies only ever
# go through parse_action -> runtime.execute, never to input().


def make_approver(emit):
    def approve(command, cwd):
        print("\n  The agent wants to run a bash command:")
        print(f"    command: {command}")
        print(f"    cwd:     {cwd}")
        try:
            answer = input("  Approve this command only? Type yes: ")
        except EOFError:
            answer = ""
        approved = answer == "yes"
        emit({"type": "approval", "command": command, "cwd": cwd, "approved": approved})
        return approved

    return approve


# ---- main ----


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # Check the setup before anything runs, and fail with a clear message.
    # parser.error() prints the usage text plus the message, then exits.
    root = Path(args.root).resolve()
    if not root.is_dir():
        parser.error(f"--root is not a directory: {root}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = Path(args.log or AGENT_DIR / "runs" / f"{timestamp}.jsonl").resolve()
    if log_path.is_relative_to(root):
        parser.error("--log must be outside the target workspace")

    enabled = None
    if args.tools:
        enabled = [name.strip() for name in args.tools.split(",") if name.strip()]

    logger = Logger(log_path)
    try:
        # Runtime raises ValueError for unknown tool names, e.g. a typo in --tools.
        try:
            runtime = Runtime(
                root,
                mode=args.mode,
                enabled=enabled,
                approve=make_approver(logger),
                offline=args.offline,
            )
        except ValueError as exc:
            parser.error(str(exc))

        # Record the configuration first: useful when comparing runs later
        # (e.g. the injection run before and after your defenses).
        logger({
            "type": "start", "model": args.model, "mode": args.mode, "root": str(root),
            "tools": sorted(runtime.enabled), "offline": args.offline, "task": args.task,
        })
        print(f"model={args.model} mode={args.mode} root={root}")
        print(f"log: {log_path}\n")

        outcome = run_agent(
            OllamaModel(args.model), runtime, args.task,
            max_turns=args.max_turns, emit=logger,
        )
    except KeyboardInterrupt:
        # run_agent already turns Ctrl+C into "cancelled" during model and tool
        # calls. This catches it anywhere else (e.g. while printing).
        print("\n== stopped: cancelled")
        return 130  # conventional exit code for "killed by Ctrl+C"
    finally:
        # `finally` runs no matter how we leave the try block: the log is
        # always closed properly.
        logger.close()

    # A final answer is the model's CLAIM. Say so, so nobody mistakes it for a
    # verified result. You check with git diff and the tests yourself.
    if outcome["termination"] == "final":
        print(f"\nModel's final answer (unverified):\n{outcome['final']}")
    else:
        print(f"\nNo final answer: {outcome.get('reason', outcome['termination'])}")
    return 0 if outcome["termination"] == "final" else 1


if __name__ == "__main__":
    sys.exit(main())
