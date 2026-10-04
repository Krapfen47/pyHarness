"""The whole run (setup -> agent loop -> verification) as the CLI and GUI use it.

Real git (a tiny local repository), but a scripted model and a fake sandbox,
so no Docker, Ollama or network is needed.
"""

import json
import threading
from pathlib import Path

import pytest
from conftest import FIX, FakeSandbox

from harness.controller import Cancelled
from harness.execution.base import FAILED, UNAVAILABLE, CheckResult
from harness.runner import HarnessRun, RunRequest
from harness.task import TaskError


def script_file(tmp_path: Path, replies: list) -> str:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(replies), encoding="utf-8")
    return str(path)


def run(request: RunRequest, sandbox: FakeSandbox) -> tuple[list[dict], object]:
    events: list[dict] = []
    harness = HarnessRun(request, events.append, sandbox_factory=lambda *args: sandbox)
    return events, harness


def test_a_run_goes_through_every_phase_and_is_verified(task_dir, tmp_path):
    sandbox = FakeSandbox()
    request = RunRequest(task=str(task_dir), script=script_file(tmp_path, FIX),
                         workdir=str(tmp_path / "work"))
    events, harness = run(request, sandbox)
    result = harness.execute()

    assert result.report.passed and result.exit_code == 0
    assert result.outcome.stop_reason == "final"
    assert result.report.changed_files == ["src/calc.py"]
    assert "+    return a + b" in result.report.diff
    # The phases, in order (only the first event of each kind).
    kinds = list(dict.fromkeys(e["type"] for e in events))
    assert kinds[:4] == ["setup", "start", "context", "model_call"]
    assert kinds[-5:] == ["verify_start", "check_start", "check_end", "verification", "finished"]
    assert [e["step"] for e in events if e["type"] == "setup"] == [
        "task", "workspace", "sandbox", "model"]
    assert events[-1] == {"type": "finished", "status": "verified", "passed": True,
                          "stop_reason": "final"}
    # The model ran "tests"; verification ran "acceptance"; containers cleaned up.
    assert sandbox.calls == ["tests", "acceptance"]
    assert sandbox.stopped >= 1


def test_a_failing_check_means_not_verified(task_dir, tmp_path):
    sandbox = FakeSandbox({"acceptance": CheckResult("acceptance", FAILED, 1, "1 failed")})
    request = RunRequest(task=str(task_dir), script=script_file(tmp_path, FIX),
                         workdir=str(tmp_path / "work"))
    events, harness = run(request, sandbox)
    result = harness.execute()
    assert not result.report.passed
    assert events[-1]["status"] == "not_verified"


def test_baseline_verifies_without_a_model(task_dir, tmp_path):
    sandbox = FakeSandbox()
    events, harness = run(RunRequest(task=str(task_dir), mode="baseline",
                                     workdir=str(tmp_path / "work")), sandbox)
    result = harness.execute()
    assert result.outcome is None
    assert not any(e["type"].startswith("model") for e in events)
    start = next(e for e in events if e["type"] == "start")
    assert start["mode"] == "baseline" and start["model"] is None
    assert sandbox.calls == ["acceptance"]


def test_stop_ends_the_run_and_skipped_checks_stay_visible(task_dir, tmp_path):
    sandbox = FakeSandbox()
    # A slow scripted model (pace) that would loop forever without Stop.
    request = RunRequest(task=str(task_dir), workdir=str(tmp_path / "work"), pace=0.01,
                         script=script_file(tmp_path, [{"tool": "list_files", "args": {}}]))
    events, harness = run(request, sandbox)

    def press_stop_after_first_result(event):
        events.append(event)
        if event["type"] == "result":
            threading.Thread(target=harness.stop).start()

    harness.emit = press_stop_after_first_result
    result = harness.execute()

    assert result.outcome.stop_reason == "cancelled"
    assert events[-1]["status"] == "cancelled"
    assert any(e["type"] == "stop_requested" for e in events)
    acceptance = next(c for c in result.report.checks if c.name == "acceptance")
    assert acceptance.status == UNAVAILABLE  # skipped, and says so
    assert not result.report.passed
    assert sandbox.calls == []  # no check ran after Stop


def test_stop_during_setup_raises_cancelled(task_dir, tmp_path):
    events, harness = run(RunRequest(task=str(task_dir), workdir=str(tmp_path / "work")),
                          FakeSandbox())
    harness.cancel.set()
    with pytest.raises(Cancelled):
        harness.execute()
    assert events[-1]["status"] == "cancelled"


def test_setup_error_is_reported_as_an_event(tmp_path):
    events, harness = run(RunRequest(task=str(tmp_path / "missing")), FakeSandbox())
    with pytest.raises(TaskError):
        harness.execute()
    assert [e["type"] for e in events] == ["error", "finished"]
    assert "task file not found" in events[0]["message"]
