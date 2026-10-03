"""Handout test "Failed command": a nonzero exit code and its output stay
visible, and the run does not claim that checks passed."""

import sys

from conftest import FakeExecution

from harness.controller import FINAL, AgentController
from harness.execution import FAILED, PASSED, UNAVAILABLE, CheckResult, run_process
from harness.model import ScriptedModel
from harness.tools import PathGuard, RepositoryTools, Toolbox
from harness.verification import Verification

FAILING = CheckResult("tests", FAILED, 1, "E   AssertionError: assert 3 == 4\n1 failed")


class NoChanges:
    """A DiffSource for tests: nothing changed."""

    def changed_files(self):
        return []

    def diff(self):
        return ""


def make_toolbox(repo, limits, execution):
    guard = PathGuard(repo, ("src/shop",))
    return Toolbox(RepositoryTools(guard, limits), execution, {"tests": "pytest"}, limits)


def test_failed_check_is_shown_to_the_model_with_exit_code_and_output(repo, limits):
    execution = FakeExecution({"tests": FAILING})
    model = ScriptedModel([{"tool": "run_check", "args": {"name": "tests"}},
                           {"final": "All tests pass!"}])  # the model lies
    outcome = AgentController(model, make_toolbox(repo, limits, execution), limits).run_task("x")

    shown = model.last_observation["output"]
    assert shown["status"] == FAILED
    assert shown["exit_code"] == 1
    assert "AssertionError" in shown["output"]
    assert outcome.stop_reason == FINAL  # the model CLAIMS success...

    # ...but verification runs the check itself and reports the truth.
    report = Verification(execution, NoChanges(), ["tests"]).report()
    assert report.passed is False
    assert report.checks[0].status == FAILED
    assert report.checks[0].exit_code == 1
    assert "AssertionError" in report.checks[0].output


def test_unavailable_check_never_counts_as_passed():
    execution = FakeExecution({
        "acceptance": CheckResult("acceptance", UNAVAILABLE, None, "Docker is not running"),
        "regression": CheckResult("regression", PASSED, 0, "26 passed"),
    })
    report = Verification(execution, NoChanges(), ["acceptance", "regression"]).report()
    assert report.passed is False
    assert [c.status for c in report.checks] == [UNAVAILABLE, PASSED]


def test_unavailable_check_is_an_error_for_the_model(repo, limits):
    execution = FakeExecution({"tests": CheckResult("tests", UNAVAILABLE, None, "no Docker")})
    result = make_toolbox(repo, limits, execution).run(
        {"tool": "run_check", "args": {"name": "tests"}})
    assert result["status"] == "error"
    assert "could not run" in result["output"]


def test_no_checks_at_all_is_not_a_pass():
    assert Verification(FakeExecution(), NoChanges(), []).report().passed is False


def test_real_process_keeps_exit_code_and_output():
    script = "print('boom'); import sys; sys.exit(3)"
    result = run_process([sys.executable, "-c", script], timeout=30, max_output=1000)
    assert result.exit_code == 3
    assert "boom" in result.output
    assert result.stop_reason is None


def test_changes_outside_the_writable_area_fail_the_scope_check(repo):
    class Sneaky(NoChanges):
        def changed_files(self):
            return ["src/shop/pricing.py", "tests/test_pricing.py"]

    guard = PathGuard(repo, ("src/shop",))
    report = Verification(FakeExecution(), Sneaky(), [], guard).report()
    [scope] = report.checks
    assert scope.status == FAILED
    assert "tests/test_pricing.py" in scope.output
    assert report.passed is False
