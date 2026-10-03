"""Load a task definition (task.toml) into one typed object.

A task file answers the questions the handout asks before any agent runs:
which repository, which exact starting commit, what is the request, which
files may change, and which checks prove the result. Keeping this in a file
(not in Python code) means a new target repo needs no code changes, and the
grader can read the whole setup in one place.

TOML is a simple config format (like an .ini file with types). Python 3.11+
can read it without extra packages (`tomllib`).
"""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class TaskError(ValueError):
    """The task file is missing something or contradicts itself."""


@dataclass(frozen=True)
class TaskSpec:
    name: str
    folder: Path  # the folder that holds task.toml; relative paths start here
    repo_url: str  # a git URL or a local path; both work with `git clone`
    commit: str  # the exact starting commit, so every run starts identically
    request: str  # the bug-fix / feature request we hand to the model
    writable: tuple[str, ...]  # folders/files the agent may change (an allow-list)
    dockerfile: Path  # builds the sandbox image the checks run in
    env: dict[str, str] = field(default_factory=dict)  # extra variables inside the sandbox
    agent_checks: dict[str, str] = field(default_factory=dict)  # name -> command; model may run
    verification: dict[str, str] = field(default_factory=dict)  # name -> command; harness runs
    acceptance_dir: Path | None = None  # mounted read-only; never inside the workspace

    @property
    def all_checks(self) -> dict[str, str]:
        """Every named command the sandbox knows. Who may run which is decided elsewhere."""
        return {**self.agent_checks, **self.verification}


def load_task(path: str | Path) -> TaskSpec:
    """Read `task.toml` (or a folder containing one) and check it is complete."""
    path = Path(path)
    if path.is_dir():
        path = path / "task.toml"
    if not path.is_file():
        raise TaskError(f"task file not found: {path}")
    folder = path.parent.resolve()

    # "rb" because tomllib wants bytes; it handles the UTF-8 decoding itself.
    with open(path, "rb") as file:
        try:
            data = tomllib.load(file)
        except tomllib.TOMLDecodeError as exc:
            raise TaskError(f"{path}: {exc}") from None

    # Small helper so every missing key gives the same clear message instead
    # of a bare KeyError deep in the code.
    def need(section: str, key: str) -> object:
        try:
            return data[section][key]
        except (KeyError, TypeError):
            raise TaskError(f"{path}: missing [{section}] {key}") from None

    repo_url = str(need("repository", "url"))
    # A relative local path (used by the tests) is relative to the task folder.
    if not _looks_like_url(repo_url) and not Path(repo_url).is_absolute():
        repo_url = str((folder / repo_url).resolve())

    writable = tuple(str(p).strip("/") for p in need("task", "writable"))
    if not writable or any(not p for p in writable):
        raise TaskError(f"{path}: [task] writable must list at least one non-empty path")

    agent_checks = {k: str(v) for k, v in data.get("checks", {}).items()}
    verification = {k: str(v) for k, v in data.get("verification", {}).items()}
    if not verification:
        raise TaskError(f"{path}: [verification] needs at least one check")
    # One name must mean one command, otherwise "tests passed" would be ambiguous.
    clash = {n for n in agent_checks.keys() & verification.keys()
             if agent_checks[n] != verification[n]}
    if clash:
        raise TaskError(f"{path}: check names used twice with different commands: {clash}")

    sandbox = data.get("sandbox", {})
    acceptance = sandbox.get("acceptance_dir")
    return TaskSpec(
        name=str(data.get("name", folder.name)),
        folder=folder,
        repo_url=repo_url,
        commit=str(need("repository", "commit")),
        request=str(need("task", "request")).strip(),
        writable=writable,
        dockerfile=folder / sandbox.get("dockerfile", "Dockerfile"),
        env={k: str(v) for k, v in sandbox.get("env", {}).items()},
        agent_checks=agent_checks,
        verification=verification,
        acceptance_dir=(folder / acceptance).resolve() if acceptance else None,
    )


def _looks_like_url(text: str) -> bool:
    return "://" in text or text.startswith("git@")
