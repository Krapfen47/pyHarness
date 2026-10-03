"""Real Docker runs. Slow-ish and they need Docker + network for the first clone,
so they are skipped by default. Run them with:

    uv run pytest -m docker

The last test is the handout's "Bug fix" test, done with the scripted reference
replies instead of a live model: the acceptance check fails on the starting
code and passes after the change, and the existing tests still pass.
"""

import json
from pathlib import Path

import pytest

from harness.controller import FINAL, AgentController
from harness.execution import FAILED, PASSED, TIMED_OUT, DockerSandbox, image_tag
from harness.limits import Limits
from harness.model import ScriptedModel
from harness.task import load_task
from harness.tools import PathGuard, RepositoryTools, Toolbox
from harness.verification import Verification
from harness.workspace import Workspace

pytestmark = pytest.mark.docker  # every test in this file gets the "docker" label

TASK_DIR = Path(__file__).resolve().parents[1] / "tasks" / "cosmic-batchref"


@pytest.fixture(scope="module")
def task():
    task = load_task(TASK_DIR)
    probe = DockerSandbox(TASK_DIR, {}, image_tag(task), Limits())
    if probe.problem():
        pytest.skip(f"Docker not usable: {probe.problem()}")
    probe.ensure_image(task.dockerfile)
    return task


def sandbox_with(task, workspace, commands, limits=None):
    return DockerSandbox(workspace, commands, image_tag(task), limits or Limits(),
                         env=task.env, acceptance_dir=task.acceptance_dir)


def test_container_has_no_network_and_cannot_write_the_code(task, tmp_path):
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    sandbox = sandbox_with(task, tmp_path, {
        "write": "python -c \"open('/work/code.py', 'w').write('hacked')\"",
        "network": "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\"",
        "whoami": "id -u",
    })
    assert sandbox.run_check("write").status == FAILED
    assert (tmp_path / "code.py").read_text() == "x = 1\n"
    assert sandbox.run_check("network").status == FAILED
    who = sandbox.run_check("whoami")
    assert who.status == PASSED and who.output.strip() == "1000"  # not root (0)


def test_stuck_check_times_out_and_leaves_no_container(task, tmp_path):
    sandbox = sandbox_with(task, tmp_path, {"hang": "python -c 'import time; time.sleep(120)'"},
                           Limits(check_timeout=5))
    result = sandbox.run_check("hang")
    assert result.status == TIMED_OUT
    sandbox.stop_processes()
    left = sandbox._docker("ps", "--all", "--quiet", "--filter",
                           f"label=harness.session={sandbox.session}", timeout=30)
    assert left.stdout.strip() == ""


def test_bug_fix_end_to_end_with_scripted_model(task, tmp_path):
    workspace = Workspace.create(task.repo_url, task.commit, tmp_path, name="e2e")
    limits = Limits()
    sandbox = DockerSandbox.for_task(task, workspace.path, limits)
    guard = PathGuard(workspace.path, task.writable)
    verification = Verification(sandbox, workspace, list(task.verification), guard)

    # Before: the acceptance check catches the bug, the old tests pass.
    before = {c.name: c.status for c in verification.run_acceptance_checks()}
    assert before == {"acceptance": FAILED, "regression": PASSED, "scope": PASSED}

    # The scripted "model" applies the reference fix through the normal tools.
    replies = json.loads((TASK_DIR / "reference_script.json").read_text(encoding="utf-8"))
    toolbox = Toolbox(RepositoryTools(guard, limits), sandbox, task.agent_checks, limits)
    outcome = AgentController(ScriptedModel(replies), toolbox, limits).run_task(task.request)
    assert outcome.stop_reason == FINAL

    # After: everything passes, and only the intended file changed.
    report = verification.report()
    assert {c.name: c.status for c in report.checks} == {
        "acceptance": PASSED, "regression": PASSED, "scope": PASSED}
    assert report.passed
    assert report.changed_files == ["src/allocation/service_layer/handlers.py"]
    sandbox.stop_processes()
