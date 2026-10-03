"""Command-line interface: the only part that talks to the human.

    uv run semProject/main.py run      --task semProject/tasks/cosmic-batchref
    uv run semProject/main.py baseline --task semProject/tasks/cosmic-batchref

`run`       clones a fresh workspace, lets the model work, then verifies.
`baseline`  clones a fresh workspace and ONLY verifies. On the starting code the
            acceptance check must fail (that proves the check detects the bug);
            with `--patch reference_fix.patch` it must pass.

Everything that involves the terminal lives here: arguments, printing, colors,
the log file. The controller, tools and sandbox never print. That split means
the core can be tested without a terminal, and a web UI could replace this
file later without touching anything else.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from harness.context import describe_repository
from harness.controller import FINAL, AgentController, RunOutcome
from harness.execution.base import PASSED
from harness.execution.sandbox import DockerSandbox, SandboxError
from harness.limits import Limits
from harness.model.ollama import DEFAULT_MODEL, OllamaModel
from harness.model.scripted import ScriptedModel
from harness.task import TaskError, load_task
from harness.tools.paths import PathGuard
from harness.tools.repo import RepositoryTools
from harness.tools.toolbox import Toolbox
from harness.verification import Verification, VerificationReport
from harness.workspace import Workspace, WorkspaceError

PROJECT_DIR = Path(__file__).resolve().parents[1]  # .../semProject
RUNS_DIR = PROJECT_DIR / "runs"  # JSONL logs (git-ignored)


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


class Logger:
    """Writes every event as one JSON line, so a run can be replayed and compared later.

    Line-buffered (buffering=1): each line hits the disk immediately, so the
    log is complete even if the run is killed halfway.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, event: dict) -> None:
        event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        self.file.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")

    def close(self) -> None:
        self.file.close()


# ---- the user interface ----

class ConsoleUI:
    """The handout's UserInterface: submit_task() in, show_result() out."""

    def __init__(self, logger: Logger | None = None):
        # Color only for a real terminal, and never if NO_COLOR is set (a
        # common convention). os.system("") is an old trick that switches
        # older Windows consoles into "understand color codes" mode.
        color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        if color and os.name == "nt":
            os.system("")
        self.s = Style(color)
        self.logger = logger

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
        return parser.parse_args(argv)

    # ---- progress ----

    def show(self, text: str = "") -> None:
        print(text, flush=True)

    def event(self, event: dict) -> None:
        """Called by the controller for every step: log it and print one line."""
        if self.logger:
            self.logger.write(event)
        s, kind = self.s, event.get("type")
        turn = f"[{event.get('turn', '-'):>2}]"
        if kind == "request":
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

def prepare(task_path: str, workdir: str | None, ui: ConsoleUI, limits: Limits):
    """Shared setup: load task, clone workspace, get the sandbox image ready."""
    task = load_task(task_path)
    parent = Path(workdir or os.environ.get("HARNESS_WORKDIR")
                  or Path(tempfile.gettempdir()) / "harness-runs")
    ui.show(f"task:      {task.name} @ {task.commit[:12]}")
    workspace = Workspace.create(task.repo_url, task.commit, parent)
    ui.show(f"workspace: {workspace.path}")
    sandbox = DockerSandbox.for_task(task, workspace.path, limits)
    problem = sandbox.problem()
    if problem:
        # We keep going: the run itself can still happen, but every check
        # will be reported as UNAVAILABLE, and the verdict can't be "verified".
        ui.show(ui.s.red(f"sandbox:   UNAVAILABLE - {problem}"))
    else:
        try:
            sandbox.ensure_image(task.dockerfile, on_build=lambda image: ui.show(
                f"sandbox:   building image {image} (first run only, may take minutes)"))
            ui.show(f"sandbox:   {sandbox.image}")
        except SandboxError as exc:
            ui.show(ui.s.red(f"sandbox:   UNAVAILABLE - {exc}"))
            sandbox.mark_unavailable("the sandbox image could not be built (see above)")
    guard = PathGuard(workspace.path, task.writable)
    return task, workspace, sandbox, guard


def run(opts: argparse.Namespace, ui: ConsoleUI) -> int:
    limits = Limits(max_actions=opts.max_actions)
    task, workspace, sandbox, guard = prepare(opts.task, opts.workdir, ui, limits)
    repo = RepositoryTools(guard, limits)
    toolbox = Toolbox(repo, sandbox, task.agent_checks, limits)

    if opts.script:
        replies = json.loads(Path(opts.script).read_text(encoding="utf-8"))
        model, model_name = ScriptedModel(replies), f"script:{opts.script}"
    else:
        model = OllamaModel(opts.model)
        model_name = model.model_name
    ui.show(f"model:     {model_name}\n")
    ui.event({"type": "start", "task": task.name, "commit": task.commit, "model": model_name,
              "workspace": str(workspace.path), "limits": limits.__dict__})

    listing = repo.list_files()
    context = describe_repository(listing["files"], task.writable, listing["truncated"])
    controller = AgentController(model, toolbox, limits, emit=ui.event)
    # try/finally: whatever happens (an error, Ctrl+C), no container survives.
    try:
        outcome = controller.run_task(task.request, context)
        ui.show("\nverifying in fresh sandbox containers ...")
        report = Verification(sandbox, workspace, list(task.verification), guard).report()
    finally:
        sandbox.stop_processes()
    ui.event({"type": "verification", "passed": report.passed,
              "checks": [c.to_dict() for c in report.checks],
              "changed_files": report.changed_files, "diff": report.diff})
    ui.show_result(outcome, report)
    return 0 if report.passed else 1


def baseline(opts: argparse.Namespace, ui: ConsoleUI) -> int:
    limits = Limits()
    task, workspace, sandbox, guard = prepare(opts.task, opts.workdir, ui, limits)
    if opts.patch:
        workspace.apply_patch(Path(opts.patch))
        ui.show(f"patch:     applied {opts.patch}")
    ui.show("\nverifying in fresh sandbox containers ...")
    try:
        report = Verification(sandbox, workspace, list(task.verification), guard).report()
    finally:
        sandbox.stop_processes()
    ui.show_report(report)
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    load_dotenv()  # settings like OLLAMA_MODEL from the .env file, if there is one
    # Never crash on a character the console can't show (old Windows code pages).
    sys.stdout.reconfigure(errors="replace")
    opts = ConsoleUI.submit_task(argv)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    logger = Logger(RUNS_DIR / f"{run_id}-{opts.command}.jsonl")
    ui = ConsoleUI(logger)
    ui.show(f"log:       {logger.path}")
    try:
        return {"run": run, "baseline": baseline}[opts.command](opts, ui)
    except (TaskError, WorkspaceError, SandboxError) as exc:
        # Setup problems: a clear message instead of a stack trace.
        ui.show(ui.s.red(f"error: {exc}"))
        return 2
    except KeyboardInterrupt:
        ui.show("\n== cancelled")
        return 130  # the conventional exit code for "stopped by Ctrl+C"
    finally:
        logger.close()
