"""Run checks inside a locked-down Docker container.

Why a container at all? Running the tests means running the repository's
code, and that code is untrusted: the model may have just written it. A
container is a separate, throw-away mini computer with only what we hand it.
The handout says it directly: "A Git worktree alone is not a sandbox."

What every check container gets (see docker_command below for the flags):

    the code        the workspace copy, mounted READ-ONLY at /work
    the acceptance  the hidden acceptance tests, READ-ONLY at /acceptance
    scratch space   a small in-memory /tmp that vanishes with the container
    nothing else    no network, no host files, no host environment variables
                    (so no API keys), no root rights, capped memory/CPU/processes

Because nothing it can see is writable, a check cannot change the code it is
checking, and a killed check cannot leave half-written files behind.

One container per check (`--rm` deletes it afterwards): every check starts
from the same clean state, so one run can't influence the next.
"""

import hashlib
import os
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path

from harness.execution.base import (
    FAILED,
    PASSED,
    STOPPED,
    TIMED_OUT,
    UNAVAILABLE,
    CheckResult,
)
from harness.execution.process import run_process
from harness.limits import Limits
from harness.task import TaskSpec

# Where Docker Desktop puts docker.exe on Windows when it isn't on PATH
# (on this machine it is installed per-user, and PATH isn't updated until a
# new login). HARNESS_DOCKER in .env overrides everything.
_LOCAL = os.environ.get("LOCALAPPDATA", "")
_PROGRAMS = os.environ.get("ProgramFiles", r"C:\Program Files")
DOCKER_CANDIDATES = [
    Path(_LOCAL) / "Programs" / "DockerDesktop" / "resources" / "bin" / "docker.exe",
    Path(_PROGRAMS) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
]

# Resource caps for one check. Generous for a pytest run, tight enough that
# a runaway test (an endless loop, a "fork bomb") can't freeze the laptop.
MEMORY = "1g"
CPUS = "2"
PIDS = "256"  # max processes inside the container
TMPFS = "/tmp:rw,noexec,nosuid,size=256m"
USER = "1000:1000"  # a normal user, not root (the image creates it)

# `docker run` uses exit code 125 for "Docker itself failed" (bad flag, image
# missing, daemon down). That is not a test failure; it means the check never
# ran, so we must not report it as "failed tests" either.
DOCKER_ERROR = 125


class SandboxError(RuntimeError):
    """The sandbox can't be prepared (Docker missing, image build failed)."""


def find_docker() -> str | None:
    configured = os.environ.get("HARNESS_DOCKER")
    if configured:
        return configured
    found = shutil.which("docker")
    if found:
        return found
    return next((str(p) for p in DOCKER_CANDIDATES if p.is_file()), None)


class DockerSandbox:
    """Fits the ExecutionEnvironment protocol (see base.py)."""

    def __init__(
        self,
        workspace: str | Path,
        commands: dict[str, str],
        image: str,
        limits: Limits,
        env: dict[str, str] | None = None,
        acceptance_dir: str | Path | None = None,
        docker: str | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.commands = dict(commands)
        self.image = image
        self.limits = limits
        self.env = dict(env or {})
        self.acceptance_dir = Path(acceptance_dir).resolve() if acceptance_dir else None
        self.docker = docker or find_docker()
        # The environment for the docker CLI program itself, on the HOST. It
        # needs its own folder on PATH to find helper programs (e.g.
        # docker-credential-desktop). This does NOT reach the container.
        self.cli_env = dict(os.environ)
        if self.docker:
            folder = str(Path(self.docker).parent)
            self.cli_env["PATH"] = folder + os.pathsep + self.cli_env.get("PATH", "")
        # Every container of this run gets this label, so stop_processes() can
        # find ALL of them, even ones whose name we lost track of.
        self.session = uuid.uuid4().hex[:8]
        self.counter = 0
        self._problem: str | None = None  # cached reason why Docker can't be used

    @classmethod
    def for_task(cls, task: TaskSpec, workspace: str | Path, limits: Limits) -> "DockerSandbox":
        return cls(workspace, task.all_checks, image_tag(task), limits,
                   env=task.env, acceptance_dir=task.acceptance_dir)

    # ---- setup ----

    def problem(self) -> str | None:
        """None if Docker is usable, otherwise a human-readable reason."""
        if self._problem is None:
            if not self.docker:
                self._problem = "docker CLI not found (install Docker or set HARNESS_DOCKER)"
            else:
                done = self._docker("version", "--format", "{{.Server.Version}}", timeout=30)
                if done.returncode != 0:
                    detail = (done.stdout + done.stderr).strip()[-300:]
                    self._problem = f"Docker is not running: {detail}"
                else:
                    self._problem = ""  # "" = checked, no problem
        return self._problem or None

    def mark_unavailable(self, reason: str) -> None:
        """From now on, every check reports UNAVAILABLE with this reason."""
        self._problem = reason

    # The image only contains the target's DEPENDENCIES (Python + packages),
    # never its code: the code is mounted fresh for every check. So the image
    # is built once and only rebuilt when the sandbox folder changes (the tag
    # contains a fingerprint of those files).
    def ensure_image(self, dockerfile: Path, on_build=None) -> bool:
        """Build the image if it doesn't exist yet. Returns True if it built."""
        problem = self.problem()
        if problem:
            raise SandboxError(problem)
        if self._docker("image", "inspect", self.image, timeout=30).returncode == 0:
            return False
        if on_build:
            on_build(self.image)
        # Building needs the network (pip install). Running checks does not.
        result = run_process(
            [self.docker, "build", "--tag", self.image, "--file", str(dockerfile),
             str(dockerfile.parent)],
            timeout=self.limits.build_timeout, max_output=2_000_000, env=self.cli_env,
        )
        if result.exit_code != 0:
            raise SandboxError(f"image build failed:\n{result.output[-3000:]}")
        return True

    # ---- running checks ----

    def docker_command(self, container: str, command: str) -> list[str]:
        """The full `docker run` command line. Pure function: easy to test."""
        mounts = [self._mount(self.workspace, "/work")]
        if self.acceptance_dir:
            mounts.append(self._mount(self.acceptance_dir, "/acceptance"))
        # Variables are passed one by one with -e. Docker does NOT copy the
        # host's environment into a container, so secrets in our .env or
        # shell stay outside unless we hand them over here (we don't).
        env = {"HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1", **self.env}
        env_flags = [flag for key, value in env.items() for flag in ("-e", f"{key}={value}")]
        return [
            self.docker, "run", "--rm",
            "--name", container,
            "--label", f"harness.session={self.session}",
            "--network", "none",  # no internet: nothing can be downloaded or leaked
            "--read-only",  # the container's own filesystem is read-only too
            "--tmpfs", TMPFS,  # ...except a small in-memory scratch folder
            "--cap-drop", "ALL",  # drop all special Linux privileges
            "--security-opt", "no-new-privileges",  # and never regain them
            "--user", USER,  # not root
            "--memory", MEMORY, "--cpus", CPUS, "--pids-limit", PIDS,
            "--init",  # a tiny init process that cleans up zombie child processes
            *[flag for mount in mounts for flag in ("--mount", mount)],
            "--workdir", "/work",
            *env_flags,
            self.image,
            # shlex.split turns "python -m pytest -q" into a list, the way a
            # shell would, but without running a shell.
            *shlex.split(command),
        ]

    def run_check(self, name: str) -> CheckResult:
        command = self.commands.get(name)
        if command is None:
            return CheckResult(name, UNAVAILABLE, None, f"no check called {name!r}")
        problem = self.problem()
        if problem:
            return CheckResult(name, UNAVAILABLE, None, problem)

        self.counter += 1
        container = f"harness-{self.session}-{self.counter}"
        result = run_process(
            self.docker_command(container, command),
            timeout=self.limits.check_timeout,
            max_output=self.limits.max_output_chars,
            env=self.cli_env,
            # Killing the docker CLI does NOT stop the container: it runs in
            # Docker's VM, not as our child process. Removing it by name does.
            on_stop=lambda: self._remove(container),
        )

        if result.stop_reason == "timeout":
            status = TIMED_OUT
        elif result.stop_reason == "output_limit":
            status = STOPPED
        elif result.exit_code == DOCKER_ERROR:
            status = UNAVAILABLE
        elif result.exit_code == 0:
            status = PASSED
        else:
            status = FAILED
        return CheckResult(name, status, result.exit_code, result.output,
                           result.truncated, round(result.duration, 1))

    def stop_processes(self) -> None:
        """Remove every container of this session that still exists."""
        if not self.docker or self.problem():
            return
        listed = self._docker("ps", "--all", "--quiet",
                              "--filter", f"label=harness.session={self.session}", timeout=30)
        ids = listed.stdout.split()
        if ids:
            self._docker("rm", "--force", *ids, timeout=60)

    # ---- helpers ----

    def _remove(self, container: str) -> None:
        self._docker("rm", "--force", container, timeout=60)

    def _docker(self, *args: str, timeout: float) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([self.docker, *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout,
                                  env=self.cli_env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(args, 1, stdout=str(exc), stderr="")

    # --mount is stricter than -v: if the source folder doesn't exist it
    # fails instead of silently creating an empty one. Commas separate the
    # options, so a path containing one would be misread; refuse it.
    @staticmethod
    def _mount(source: Path, target: str) -> str:
        if "," in str(source):
            raise SandboxError(f"path contains a comma, can't mount it safely: {source}")
        return f"type=bind,source={source},target={target},readonly"


def image_tag(task: TaskSpec) -> str:
    """'harness-<task>:<fingerprint of the sandbox folder>'."""
    digest = hashlib.sha256()
    context = task.dockerfile.parent
    for path in sorted(p for p in context.rglob("*") if p.is_file()):
        digest.update(path.relative_to(context).as_posix().encode())
        digest.update(path.read_bytes())
    return f"harness-{task.name.lower()}:{digest.hexdigest()[:12]}"
