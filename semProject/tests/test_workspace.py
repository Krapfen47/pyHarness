"""The disposable workspace (a git clone at a fixed commit) and task loading."""

from pathlib import Path

import pytest

from harness.task import TaskError, load_task
from harness.workspace import Workspace, run_git

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def origin(tmp_path) -> tuple[Path, str]:
    """A small local git repository with two commits. Returns (path, first commit)."""
    repo = tmp_path / "origin"
    repo.mkdir()
    run_git("init", "--quiet", cwd=repo)
    (repo / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    run_git("add", ".", cwd=repo)
    run_git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one", cwd=repo)
    first = run_git("rev-parse", "HEAD", cwd=repo).strip()
    (repo / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
    run_git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "two", cwd=repo)
    return repo, first


def test_workspace_starts_at_the_pinned_commit(origin, tmp_path):
    repo, first = origin
    workspace = Workspace.create(str(repo), first, tmp_path / "runs", name="run1")
    assert (workspace.path / "app.py").read_text() == "VERSION = 1\n"
    assert workspace.base_commit == first
    assert workspace.changed_files() == []
    assert workspace.diff() == ""


def test_workspace_has_no_remote_to_push_to(origin, tmp_path):
    repo, first = origin
    workspace = Workspace.create(str(repo), first, tmp_path / "runs", name="run1")
    assert run_git("remote", cwd=workspace.path).strip() == ""


def test_diff_shows_edits_and_new_files(origin, tmp_path):
    repo, first = origin
    workspace = Workspace.create(str(repo), first, tmp_path / "runs", name="run1")
    (workspace.path / "app.py").write_text("VERSION = 3\n", encoding="utf-8")
    (workspace.path / "new.py").write_text("NEW = True\n", encoding="utf-8")

    assert workspace.changed_files() == ["app.py", "new.py"]
    diff = workspace.diff()
    assert "-VERSION = 1" in diff and "+VERSION = 3" in diff
    assert "+NEW = True" in diff
    assert (repo / "app.py").read_text() == "VERSION = 2\n"  # original untouched


def test_the_example_task_loads():
    task = load_task(PROJECT / "tasks" / "cosmic-batchref")
    assert task.name == "cosmic-batchref"
    assert len(task.commit) == 40
    assert task.writable == ("src/allocation", "tests/unit")
    assert set(task.verification) == {"acceptance", "regression"}
    assert "acceptance" not in task.agent_checks  # the model can't run the hidden check
    assert task.acceptance_dir.is_dir()
    assert task.dockerfile.is_file()


def test_task_without_verification_is_rejected(tmp_path):
    (tmp_path / "task.toml").write_text(
        '[repository]\nurl = "x"\ncommit = "abc"\n'
        '[task]\nrequest = "fix it"\nwritable = ["src"]\n', encoding="utf-8")
    with pytest.raises(TaskError, match="verification"):
        load_task(tmp_path)
