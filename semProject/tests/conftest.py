"""Shared test fixtures.

pytest finds this file automatically. A "fixture" is a function that builds
something a test needs; a test asks for it just by naming it as a parameter
(e.g. `def test_x(repo, toolbox):`). pytest builds a fresh one for every
test, so tests can't influence each other.

None of the core tests need Docker, Ollama or the network (handout: "Core
tests must run without a live account or API key"). Docker tests live in
test_docker_integration.py and only run with `uv run pytest -m docker`.
"""

from pathlib import Path

import pytest

from harness.execution.base import PASSED, CheckResult
from harness.limits import Limits
from harness.tools import PathGuard, RepositoryTools, Toolbox

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
