"""Check the result ourselves instead of believing the model.

When the model says {"final": "Fixed it, all tests pass"}, that is a CLAIM.
Small models say this even when they never ran a test. So after the loop
stops (for ANY reason, also limits or errors) the harness:

1. runs the verification checks from the task file in fresh sandbox
   containers: the hidden acceptance check plus the existing regression tests;
2. checks that every changed file is inside the writable area ("scope");
3. collects the real diff from git.

The overall verdict is "passed" only if every single check passed. A check
that failed, timed out or could not run at all ("unavailable") makes the
verdict "not passed", no matter what the model said. This is the handout's
"Keep failed or unavailable checks visible even if the model says it is done."
"""

from dataclasses import dataclass, field
from typing import Protocol

from harness.execution.base import FAILED, PASSED, CheckResult, ExecutionEnvironment
from harness.tools.paths import PathGuard


class DiffSource(Protocol):
    """Anything that can tell us what changed. The real one is Workspace."""

    def changed_files(self) -> list[str]: ...
    def diff(self) -> str: ...


@dataclass
class VerificationReport:
    checks: list[CheckResult]
    changed_files: list[str] = field(default_factory=list)
    diff: str = ""

    @property
    def passed(self) -> bool:
        # `bool(self.checks)`: zero checks is NOT a pass. "Nothing was checked"
        # must never look like "everything is fine".
        return bool(self.checks) and all(check.passed for check in self.checks)


class Verification:
    def __init__(
        self,
        execution: ExecutionEnvironment,
        workspace: DiffSource,
        check_names: list[str],
        guard: PathGuard | None = None,
    ):
        self.execution = execution
        self.workspace = workspace
        self.check_names = list(check_names)
        self.guard = guard

    def run_acceptance_checks(self) -> list[CheckResult]:
        results = [self.execution.run_check(name) for name in self.check_names]
        if self.guard is not None:
            results.append(self.check_scope())
        return results

    # Defense in depth: the file tools already refuse writes outside the
    # writable area, so this should always pass. We check anyway, from a
    # different angle (git's view of the result instead of the tools' view).
    # If one layer has a bug, the other one still catches it.
    def check_scope(self) -> CheckResult:
        outside = [f for f in self.workspace.changed_files() if not self.guard.is_writable(f)]
        if outside:
            return CheckResult("scope", FAILED, None,
                               "changed outside the writable area: " + ", ".join(outside))
        return CheckResult("scope", PASSED, None,
                           f"all changes are inside {list(self.guard.writable)}")

    def show_diff(self) -> str:
        return self.workspace.diff()

    def report(self) -> VerificationReport:
        checks = self.run_acceptance_checks()
        return VerificationReport(checks, self.workspace.changed_files(), self.show_diff())
