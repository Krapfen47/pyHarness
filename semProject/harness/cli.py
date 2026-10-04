"""Command-line interface: the only part that talks to the human in a terminal.

    uv run semProject/main.py run      --task semProject/tasks/cosmic-batchref
    uv run semProject/main.py baseline --task semProject/tasks/cosmic-batchref
    uv run semProject/main.py gui

`run`       clones a fresh workspace, lets the model work, then verifies.
`baseline`  clones a fresh workspace and ONLY verifies. On the starting code the
            acceptance check must fail (that proves the check detects the bug);
            with `--patch reference_fix.patch` it must pass.
`gui`       starts the web interface (see harness/gui/) instead.

The run itself lives in runner.py. This file only reads the arguments and
turns the run's events into lines of text: arguments, printing, colors.
The controller, tools and sandbox never print. That split means the core can
be tested without a terminal, and the GUI shows exactly the same run.
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from harness.controller import FINAL, RunOutcome
from harness.events import EventStream, Logger, new_run_id
from harness.execution.base import PASSED
from harness.limits import Limits
from harness.model.ollama import DEFAULT_MODEL
from harness.runner import RUNS_DIR, SETUP_ERRORS, HarnessRun, RunRequest
from harness.verification import VerificationReport

# ---- output helpers ----

class Style:
    """ANSI colors, only when printing to a real terminal (not into a file)."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def green(self, text: str) -> str:
        return self(text, "32")

    def red(self, text: str) -> str:
        return self(text, "31")

    def yellow(self, text: str) -> str:
        return self(text, "33")

    def cyan(self, text: str) -> str:
        return self(text, "36")

    def bold(self, text: str) -> str:
        return self(text, "1")


def short(value: object, limit: int = 140) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "..."


# ---- the user interface ----

class ConsoleUI:
    """The handout's UserInterface: submit_task() in, show_result() out."""

    def __init__(self):
        # Color only for a real terminal, and never if NO_COLOR is set (a
        # common convention). os.system("") is an old trick that switches
        # older Windows consoles into "understand color codes" mode.
        color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        if color and os.name == "nt":
            os.system("")
        self.s = Style(color)

    @staticmethod
    def submit_task(argv: list[str] | None = None) -> argparse.Namespace:
        """Read what the user wants from the command line."""
        parser = argparse.ArgumentParser(prog="harness",
                                         description="Stage 1 coding harness")
        commands = parser.add_subparsers(dest="command", required=True)

        run = commands.add_parser("run", help="let the model work on the task, then verify")
        run.add_argument("--task", required=True, help="task folder or task.toml")
        run.add_argument("--model", default=None,
                         help=f"Ollama model (default: $OLLAMA_MODEL or {DEFAULT_MODEL})")
        run.add_argument("--script", help="JSON file of scripted replies instead of a model")
        run.add_argument("--max-actions", type=int, default=Limits.max_actions)
        run.add_argument("--workdir", help="where workspaces are created")

        base = commands.add_parser("baseline", help="verify the starting code, no model")
        base.add_argument("--task", required=True)
        base.add_argument("--patch", help="apply this patch first (e.g. a reference fix)")
        base.add_argument("--workdir")

        gui = commands.add_parser("gui", help="start the web interface")
        gui.add_argument("--port", type=int, default=8765)
        gui.add_argument("--no-browser", action="store_true",
                         help="don't open a browser window automatically")
        return parser.parse_args(argv)

    # ---- progress ----

    def show(self, text: str = "") -> None:
        print(text, flush=True)

    def event(self, event: dict) -> None:
        """Called for every event of the run: print one line for the ones a human needs."""
        s, kind = self.s, event.get("type")
        turn = f"[{event.get('turn', '-'):>2}]"
        if kind == "setup":
            self.show_setup(event)
        elif kind == "verify_start":
            self.show("\nverifying in fresh sandbox containers ...")
        elif kind == "request":
            action = event["action"]
            self.show(f"{turn} -> {s.cyan(action['tool'])} {short(action.get('args', {}))}")
        elif kind == "result":
            result, pad = event["result"], " " * len(turn)
            status = result["status"]
            colored = {"ok": s.green, "denied": s.red, "error": s.yellow}[status](status)
            output = result["output"]
            if event["tool"] == "run_check" and isinstance(output, dict):
                detail = f"check {output['check']}: {output['status']} (exit {output['exit_code']})"
            else:
                detail = short(output)
            self.show(f"{pad} <- {colored}: {detail}")
        elif kind == "invalid":
            self.show(f"{turn} {s.yellow('!! invalid reply')}: {event['error']}")
        elif kind == "repeat":
            self.show(f"{' ' * len(turn)}    {s.yellow('(repeated request: model was told so)')}")
        elif kind == "stop":
            self.show(f"== stopped: {event['stop_reason']} after {event['turns']} turn(s)")
        # Everything else (model_token, model_reply, observation, ...) is
        # still in the log file and the GUI; the terminal stays readable.

    def show_setup(self, event: dict) -> None:
        step, status = event["step"], event["status"]
        if step == "task":
            self.show(f"task:      {event['task']} @ {event['commit'][:12]}")
        elif step == "workspace":
            self.show(f"workspace: {event['path']}")
        elif step == "sandbox" and status == "building":
            self.show(f"sandbox:   building image {event['image']} "
                      "(first run only, may take minutes)")
        elif step == "sandbox" and status == "ok":
            self.show(f"sandbox:   {event['image']}")
        elif step == "sandbox":
            self.show(self.s.red(f"sandbox:   UNAVAILABLE - {event['detail']}"))
        elif step == "patch":
            self.show(f"patch:     applied {event['patch']}")
        elif step == "model":
            self.show(f"model:     {event['model']}\n")

    # ---- the result ----

    def show_diff(self, diff: str) -> None:
        if not diff.strip():
            self.show("  (no changes)")
            return
        for line in diff.splitlines():
            if line.startswith(("+++", "---")):
                line = self.s.bold(line)
            elif line.startswith("+"):
                line = self.s.green(line)
            elif line.startswith("-"):
                line = self.s.red(line)
            elif line.startswith("@@"):
                line = self.s.cyan(line)
            self.show("  " + line)

    def show_report(self, report: VerificationReport) -> None:
        s = self.s
        self.show(s.bold("\nChanged files:"))
        for path in report.changed_files or ["(none)"]:
            self.show(f"  {path}")
        self.show(s.bold("\nDiff:"))
        self.show_diff(report.diff)
        self.show(s.bold("\nChecks (run by the harness, not the model):"))
        for check in report.checks:
            label = f"{check.status.upper():<11}"
            label = s.green(label) if check.status == PASSED else s.red(label)
            exit_info = "" if check.exit_code is None else f" exit {check.exit_code}"
            self.show(f"  {label} {check.name}{exit_info}  ({check.duration}s)")
            if check.status != PASSED:
                # The tail of the output is where pytest puts its summary.
                for line in check.output.strip().splitlines()[-15:]:
                    self.show(f"      {line}")
        verdict = (s.green("VERIFIED: every check passed") if report.passed
                   else s.red("NOT VERIFIED: at least one check did not pass"))
        self.show(f"\n{s.bold('Verdict:')} {verdict}")

    def show_result(self, outcome: RunOutcome, report: VerificationReport) -> None:
        s = self.s
        self.show(s.bold("\n=== Result ==="))
        # The model's claim and the harness's verdict are shown SEPARATELY and
        # labelled, so nobody mistakes "the model said so" for "it's true".
        if outcome.stop_reason == FINAL:
            self.show(f"Model says it is done (unverified claim):\n  {outcome.final_message}")
        else:
            self.show(s.yellow(f"Run stopped early: {outcome.stop_reason} ({outcome.reason})"))
        self.show(f"Turns {outcome.turns} | actions {outcome.actions} | retries "
                  f"{outcome.retries} | denied {outcome.denied} | errors {outcome.errors}"
                  f" | repeats {outcome.repeats}")
        self.show_report(report)


# ---- commands ----

def request_from(opts: argparse.Namespace) -> RunRequest:
    """Translate command-line options into the runner's RunRequest."""
    if opts.command == "baseline":
        return RunRequest(task=opts.task, mode="baseline", patch=opts.patch,
                          workdir=opts.workdir)
    return RunRequest(task=opts.task, mode="run", model=opts.model, script=opts.script,
                      max_actions=opts.max_actions, workdir=opts.workdir)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # settings like OLLAMA_MODEL from the .env file, if there is one
    # Never crash on a character the console can't show (old Windows code pages).
    sys.stdout.reconfigure(errors="replace")
    opts = ConsoleUI.submit_task(argv)
    if opts.command == "gui":
        # Imported only here, so the plain CLI never loads the web server.
        from harness.gui.server import serve
        return serve(port=opts.port, open_browser=not opts.no_browser)

    run_id = new_run_id(opts.command)
    logger = Logger(RUNS_DIR / f"{run_id}.jsonl")
    ui = ConsoleUI()
    # Every event goes to the log file AND to the console printer.
    events = EventStream(run_id, [logger.write, ui.event])
    ui.show(f"log:       {logger.path}")
    try:
        result = HarnessRun(request_from(opts), events.emit).execute()
        if result.outcome is None:
            ui.show_report(result.report)
        else:
            ui.show_result(result.outcome, result.report)
        return result.exit_code
    except SETUP_ERRORS as exc:
        # Setup problems: a clear message instead of a stack trace.
        ui.show(ui.s.red(f"error: {exc}"))
        return 2
    except KeyboardInterrupt:
        ui.show("\n== cancelled")
        return 130  # the conventional exit code for "stopped by Ctrl+C"
    finally:
        logger.close()
