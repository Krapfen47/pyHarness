"""One harness run from start to finish, independent of any user interface.

    setup         load the task, clone a fresh workspace, get the sandbox ready
    agent loop    the controller works on the task          (mode "run" only)
    verification  the harness checks the result itself

Both interfaces use this class: the CLI (cli.py) and the GUI (gui/). Neither
of them repeats any of these steps; they only LISTEN to the events this class
emits and show them in their own way. That's what keeps the two interfaces
from drifting apart.

The events added here (the controller and verification add their own):

    setup         one setup step: task / workspace / sandbox / patch / model
    start         everything about the run in one place (task, model, limits)
    verify_start  verification begins (the list of checks)
    verification  the full report: every check, changed files, the diff
    finished      the very last event: the verdict, or "cancelled" / "error"
    error         setup failed (no such task, git clone failed, ...)
    stop_requested  the user pressed Stop (the GUI)
"""

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness.context import describe_repository
from harness.controller import AgentController, Cancelled, Emit, RunOutcome
from harness.execution.sandbox import DockerSandbox, SandboxError
from harness.limits import Limits
from harness.model.ollama import OllamaModel
from harness.model.scripted import ScriptedModel
from harness.task import TaskError, TaskSpec, load_task
from harness.tools.paths import PathGuard
from harness.tools.repo import RepositoryTools
from harness.tools.toolbox import Toolbox
from harness.verification import Verification, VerificationReport
from harness.workspace import Workspace, WorkspaceError

PROJECT_DIR = Path(__file__).resolve().parents[1]  # .../semProject
RUNS_DIR = PROJECT_DIR / "runs"  # JSONL logs (git-ignored)
TASKS_DIR = PROJECT_DIR / "tasks"

# Setup problems that end a run before it starts, with a clear message.
SETUP_ERRORS = (TaskError, WorkspaceError, SandboxError)


@dataclass
class RunRequest:
    """Everything a user can choose for one run (CLI flags or the GUI form)."""

    task: str  # task folder or task.toml
    mode: str = "run"  # "run": model works, then verification. "baseline": verification only
    model: str | None = None  # Ollama model name (default: $OLLAMA_MODEL)
    script: str | None = None  # JSON file of scripted replies instead of a model
    pace: float = 0.0  # scripted replies: seconds between streamed pieces (demo speed)
    patch: str | None = None  # baseline only: apply this patch first (e.g. the reference fix)
    max_actions: int = Limits.max_actions
    workdir: str | None = None  # where workspaces are created


@dataclass
class RunResult:
    outcome: RunOutcome | None  # None for a baseline (no model involved)
    report: VerificationReport

    @property
    def exit_code(self) -> int:
        return 0 if self.report.passed else 1


class HarnessRun:
    # sandbox_factory: how to build the sandbox. Tests pass a fake one, so the
    # whole run can be tested without Docker (same idea as ScriptedModel).
    def __init__(self, request: RunRequest, emit: Emit,
                 sandbox_factory: Callable[..., DockerSandbox] = DockerSandbox.for_task):
        self.request = request
        self.emit = emit
        self.sandbox_factory = sandbox_factory
        # The Stop button's flag, shared with the controller and verification.
        self.cancel = threading.Event()
        # Kept so stop() can reach them from another thread.
        self.model: OllamaModel | ScriptedModel | None = None
        self.sandbox: DockerSandbox | None = None

    # ---- stopping (called from ANOTHER thread, e.g. the GUI's web server) ----

    def stop(self) -> None:
        """Ask the run to stop as soon as possible, without leaving anything behind.

        1. set the flag: the loop and verification check it between steps;
        2. cut off a reply that is streaming from Ollama right now;
        3. remove the sandbox's containers, which ends a running check.
        The run thread then notices the flag and finishes cleanly by itself.
        """
        if self.cancel.is_set():
            return
        self.cancel.set()
        self.emit({"type": "stop_requested"})
        model, sandbox = self.model, self.sandbox
        if isinstance(model, OllamaModel):
            model.cancel()
        if sandbox is not None:
            sandbox.stop_processes()

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled

    # ---- the run ----

    def execute(self) -> RunResult:
        """Run everything. Raises a SETUP_ERRORS exception or Cancelled if it can't finish."""
        try:
            return self._execute()
        except SETUP_ERRORS as exc:
            self.emit({"type": "error", "message": str(exc)})
            self.emit({"type": "finished", "status": "error", "passed": False})
            raise
        except Cancelled:
            self.emit({"type": "finished", "status": "cancelled", "passed": False})
            raise

    def _execute(self) -> RunResult:
        request = self.request
        limits = Limits(max_actions=request.max_actions)
        task, workspace, sandbox, guard = self.prepare(limits)
        # try/finally: whatever happens (an error, Ctrl+C, Stop), no container survives.
        try:
            if request.mode == "baseline":
                if request.patch:
                    workspace.apply_patch(Path(request.patch))
                    self.emit({"type": "setup", "step": "patch", "status": "ok",
                               "patch": request.patch})
                self.emit(self.start_event(task, workspace, sandbox, limits, None, None))
                outcome = None
            else:
                repo = RepositoryTools(guard, limits)
                toolbox = Toolbox(repo, sandbox, task.agent_checks, limits)
                model_name, settings = self.make_model()
                self.emit({"type": "setup", "step": "model", "status": "ok", "model": model_name})
                self.emit(self.start_event(task, workspace, sandbox, limits, model_name, settings))
                self.check_cancel()
                listing = repo.list_files()
                context = describe_repository(listing["files"], task.writable,
                                              listing["truncated"])
                controller = AgentController(self.model, toolbox, limits, emit=self.emit,
                                             cancel=self.cancel)
                outcome = controller.run_task(task.request, context)
            report = self.verify(task, sandbox, workspace, guard)
        finally:
            sandbox.stop_processes()
        if self.cancel.is_set():
            status = "cancelled"
        else:
            status = "verified" if report.passed else "not_verified"
        self.emit({"type": "finished", "status": status, "passed": report.passed,
                   "stop_reason": outcome.stop_reason if outcome else None})
        return RunResult(outcome, report)

    def prepare(self, limits: Limits) -> tuple[TaskSpec, Workspace, DockerSandbox, PathGuard]:
        """Shared setup: load task, clone workspace, get the sandbox image ready."""
        request = self.request
        task = load_task(request.task)
        self.emit({"type": "setup", "step": "task", "status": "ok", "task": task.name,
                   "commit": task.commit})
        self.check_cancel()

        parent = Path(request.workdir or os.environ.get("HARNESS_WORKDIR")
                      or Path(tempfile.gettempdir()) / "harness-runs")
        workspace = Workspace.create(task.repo_url, task.commit, parent)
        self.emit({"type": "setup", "step": "workspace", "status": "ok",
                   "path": str(workspace.path)})
        self.check_cancel()

        sandbox = self.sandbox_factory(task, workspace.path, limits)
        self.sandbox = sandbox
        problem = sandbox.problem()
        if problem:
            # We keep going: the run itself can still happen, but every check
            # will be reported as UNAVAILABLE, and the verdict can't be "verified".
            self.emit({"type": "setup", "step": "sandbox", "status": "unavailable",
                       "detail": problem})
        else:
            try:
                sandbox.ensure_image(task.dockerfile, on_build=lambda image: self.emit(
                    {"type": "setup", "step": "sandbox", "status": "building", "image": image}))
                self.emit({"type": "setup", "step": "sandbox", "status": "ok",
                           "image": sandbox.image})
            except SandboxError as exc:
                self.emit({"type": "setup", "step": "sandbox", "status": "unavailable",
                           "detail": str(exc)})
                sandbox.mark_unavailable("the sandbox image could not be built (see above)")
        self.check_cancel()
        return task, workspace, sandbox, PathGuard(workspace.path, task.writable)

    def make_model(self) -> tuple[str, dict | None]:
        """Create the model client. Returns its display name and its settings."""
        if self.request.script:
            path = Path(self.request.script)
            replies = json.loads(path.read_text(encoding="utf-8"))
            self.model = ScriptedModel(replies, pace=self.request.pace)
            # Shown as e.g. "script:semProject/tasks/x/reference_script.json".
            if path.is_absolute() and path.is_relative_to(PROJECT_DIR.parent):
                path = path.relative_to(PROJECT_DIR.parent)
            return f"script:{path.as_posix()}", None
        model = OllamaModel(self.request.model)
        self.model = model
        return model.model_name, model.settings()

    def start_event(self, task: TaskSpec, workspace: Workspace, sandbox: DockerSandbox,
                    limits: Limits, model_name: str | None, settings: dict | None) -> dict:
        """One event with everything about the run, e.g. for the GUI's "Run" tab."""
        return {
            "type": "start", "mode": self.request.mode, "task": task.name,
            "commit": task.commit, "repo_url": task.repo_url, "request": task.request,
            "writable": list(task.writable), "agent_checks": task.agent_checks,
            "verification_checks": task.verification, "model": model_name,
            "model_settings": settings, "workspace": str(workspace.path),
            "sandbox": {"image": sandbox.image, "problem": sandbox.problem()},
            "limits": limits.__dict__,
        }

    def verify(self, task: TaskSpec, sandbox: DockerSandbox, workspace: Workspace,
               guard: PathGuard) -> VerificationReport:
        self.emit({"type": "verify_start", "checks": [*task.verification, "scope"]})
        report = Verification(sandbox, workspace, list(task.verification), guard,
                              emit=self.emit, cancel=self.cancel).report()
        self.emit({"type": "verification", "passed": report.passed,
                   "checks": [c.to_dict() for c in report.checks],
                   "changed_files": report.changed_files, "diff": report.diff})
        return report
