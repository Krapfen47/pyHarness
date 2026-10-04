"""Shared test fixtures.

pytest finds this file automatically. A "fixture" is a function that builds
something a test needs; a test asks for it just by naming it as a parameter
(e.g. `def test_x(repo, toolbox):`). pytest builds a fresh one for every
test, so tests can't influence each other.

None of the core tests need Docker, Ollama or the network (handout: "Core
tests must run without a live account or API key"). Docker tests live in
test_docker_integration.py and only run with `uv run pytest -m docker`.
"""

import json
from pathlib import Path

import pytest

from harness.execution.base import PASSED, CheckResult
from harness.limits import Limits
from harness.tools import PathGuard, RepositoryTools, Toolbox
from harness.workspace import run_git

PRICING = "def total(prices):\n    return sum(prices)\n"


class FakeExecution:
    """Stands in for the Docker sandbox: returns prepared results, records calls."""

    def __init__(self, results: dict[str, CheckResult] | None = None):
        self.results = results or {}
        self.calls: list[str] = []
        self.stopped = False

    def run_check(self, name: str) -> CheckResult:
        self.calls.append(name)
        return self.results.get(name) or CheckResult(name, PASSED, 0, "3 passed")

    def stop_processes(self) -> None:
        self.stopped = True


def write_files(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny repository, plus a 'secret' file next to it (outside the repo)."""
    root = tmp_path / "repo"
    write_files(root, {
        "src/shop/__init__.py": "",
        "src/shop/pricing.py": PRICING,
        "tests/test_pricing.py": "from shop.pricing import total\n",
        "README.md": "# Shop\n",
        ".env": "API_KEY=do-not-leak\n",
        ".git/config": "[core]\n",
    })
    (tmp_path / "outside.txt").write_text("host secret", encoding="utf-8")
    return root


@pytest.fixture
def limits() -> Limits:
    # Small limits so the limit tests are quick and easy to reason about.
    return Limits(max_actions=4, max_retries=2, max_denied=2,
                  max_output_chars=200, max_observation_chars=600)


@pytest.fixture
def execution() -> FakeExecution:
    return FakeExecution()


@pytest.fixture
def guard(repo: Path) -> PathGuard:
    return PathGuard(repo, ("src/shop",))


@pytest.fixture
def toolbox(guard: PathGuard, limits: Limits, execution: FakeExecution) -> Toolbox:
    return Toolbox(RepositoryTools(guard, limits), execution, {"tests": "pytest -q"}, limits)


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file's bytes, to prove later that nothing changed."""
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---- a whole task (for the runner and GUI tests) ----

class FakeSandbox:
    """Has every method the runner uses on DockerSandbox; runs nothing."""

    image = "fake-image"

    def __init__(self, results: dict[str, CheckResult] | None = None):
        self.results = results or {}
        self.calls: list[str] = []
        self.stopped = 0

    def problem(self):
        return None

    def ensure_image(self, dockerfile, on_build=None):
        return False

    def mark_unavailable(self, reason):
        pass

    def run_check(self, name):
        self.calls.append(name)
        return self.results.get(name) or CheckResult(name, PASSED, 0, "1 passed", duration=0.1)

    def stop_processes(self):
        self.stopped += 1


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """A local origin repository plus a task.toml pointing at it."""
    origin = tmp_path / "origin"
    (origin / "src").mkdir(parents=True)
    (origin / "src" / "calc.py").write_text("def add(a, b):\n    return a - b\n",
                                            encoding="utf-8")
    run_git("init", "--quiet", cwd=origin)
    run_git("add", ".", cwd=origin)
    run_git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one", cwd=origin)
    commit = run_git("rev-parse", "HEAD", cwd=origin).strip()

    task = tmp_path / "task"
    task.mkdir()
    (task / "task.toml").write_text(f"""
name = "calc-bug"
[repository]
url = {str(origin)!r}
commit = "{commit}"
[task]
request = "add() subtracts. Fix it."
writable = ["src"]
[checks]
tests = "pytest -q"
[verification]
acceptance = "pytest -q /acceptance"
""", encoding="utf-8")
    (task / "reference_script.json").write_text(json.dumps(FIX), encoding="utf-8")
    return task


FIX = [
    {"tool": "edit_file", "args": {"path": "src/calc.py", "old": "a - b", "new": "a + b"}},
    {"tool": "run_check", "args": {"name": "tests"}},
    {"final": "Fixed add()."},
]
