"""The disposable copy of the target repository the agent works on.

The handout: "Use a disposable copy of the target repository." Each run gets
a fresh `git clone` in its own folder, checked out at the exact starting
commit from the task file. So:

- every run starts from the same code (repeatable, comparable runs);
- the original repository is never touched;
- git itself tells us afterwards what changed (`git diff`), we don't have to
  trust the model's summary.

The copy has no remote ("origin" is removed right after cloning), so there is
nowhere to push to. Push, merge and deploy are not just "not offered as a
tool": they are impossible from here.

Note: git runs on the host, on files the model edited. That is OK because the
model can't write hidden files (PathGuard blocks anything starting with "."),
so it can't plant a .gitattributes or .git/config that would make git run
commands. We also pass --no-ext-diff / --no-textconv to be safe.
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path


class WorkspaceError(RuntimeError):
    """Cloning or inspecting the workspace failed."""


def run_git(*args: str, cwd: Path | None = None, timeout: float = 300) -> str:
    # GIT_TERMINAL_PROMPT=0: if a URL needed a password, fail instead of
    # waiting forever for someone to type one.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WorkspaceError(f"git {args[0]} failed: {exc}") from None
    if done.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args[:2])} failed: {done.stderr.strip()}")
    return done.stdout


class Workspace:
    def __init__(self, path: Path, base_commit: str):
        self.path = Path(path)
        self.base_commit = base_commit

    @classmethod
    def create(cls, repo_url: str, commit: str, parent: Path, name: str = "") -> "Workspace":
        """Clone `repo_url` into a new folder under `parent` and check out `commit`."""
        run_id = name or datetime.now().strftime("%Y%m%d-%H%M%S")
        path = Path(parent).resolve() / run_id / "repo"
        if path.exists():
            raise WorkspaceError(f"workspace already exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

        # core.autocrlf=false: Git for Windows would otherwise convert line
        # endings to \r\n on checkout. The Linux container and the model both
        # expect the files exactly as they are in the repository (\n).
        run_git("clone", "--quiet", "--no-checkout", "-c", "core.autocrlf=false",
                repo_url, str(path))
        run_git("checkout", "--quiet", "--detach", commit, cwd=path)
        # Store the full commit id, even if the task file used a short one.
        full_commit = run_git("rev-parse", "HEAD", cwd=path).strip()
        run_git("remote", "remove", "origin", cwd=path)  # nothing to push to
        return cls(path, full_commit)

    # "intent to add" tells git about NEW files without staging their content.
    # Without it, `git diff` would ignore files the agent created.
    def _track_new_files(self) -> None:
        run_git("add", "--intent-to-add", "--", ".", cwd=self.path)

    def changed_files(self) -> list[str]:
        self._track_new_files()
        out = run_git("diff", "--name-only", "--no-ext-diff", cwd=self.path)
        return [line for line in out.splitlines() if line]

    def diff(self) -> str:
        """Everything that changed since the starting commit, as a unified diff."""
        self._track_new_files()
        return run_git("diff", "--no-color", "--no-ext-diff", "--no-textconv", cwd=self.path)

    def apply_patch(self, patch: Path) -> None:
        """Apply a patch file (used by `baseline --patch` to test a reference fix)."""
        run_git("apply", "--whitespace=nowarn", str(Path(patch).resolve()), cwd=self.path)
