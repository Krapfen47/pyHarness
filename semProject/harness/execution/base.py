"""What "running a check" means, independent of HOW it is run.

The controller, the toolbox and the verification step only know this
interface. The real implementation runs the check in Docker (sandbox.py); the
tests use a fake that returns prepared results. Same idea as ModelClient: a
small interface is the seam that lets core tests run without Docker.
"""

from dataclasses import asdict, dataclass
from typing import Protocol

# Every possible outcome of a check. Only "passed" counts as passing. Anything
# else (including "we could not even run it") is NOT a pass. The handout:
# "Keep failed or unavailable checks visible even if the model says it is done."
PASSED = "passed"  # exit code 0
FAILED = "failed"  # ran, exit code not 0 (e.g. a test failed)
TIMED_OUT = "timed_out"  # took longer than the limit and was stopped
STOPPED = "stopped"  # produced more output than allowed and was stopped
UNAVAILABLE = "unavailable"  # could not run at all (no Docker, image missing, ...)


@dataclass
class CheckResult:
    name: str
    status: str
    exit_code: int | None  # None when there is no real exit code (unavailable, killed)
    output: str  # already clipped to the output limit
    truncated: bool = False  # True if `output` was shortened
    duration: float = 0.0  # seconds

    @property
    def passed(self) -> bool:
        return self.status == PASSED

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionEnvironment(Protocol):
    def run_check(self, name: str) -> CheckResult:
        """Run the configured command called `name` in a contained environment."""
        ...

    def stop_processes(self) -> None:
        """Stop everything this environment started. Safe to call any time."""
        ...
