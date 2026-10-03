"""The tool registry: which tools exist, what arguments they take, and one
pipeline that every request goes through (carried over from the lab's
Runtime.dispatch / execute).

    validate(action)         is it a known tool with exactly the right arguments?
        -> InvalidRequest       (nothing runs; the model must ask again)
    run(action)              call the tool
        -> {"status": "ok",     "output": ...}   it worked
        -> {"status": "denied", "output": why}   policy said no
        -> {"status": "error",  "output": why}   allowed, but it failed

The registry is a table. Everything else is driven by it: the tool list in
the prompt, the argument check, the call. Adding a tool means adding one
entry, not another `if tool == ...` branch somewhere.
"""

from collections.abc import Callable
from dataclasses import dataclass

from harness.execution.base import UNAVAILABLE, ExecutionEnvironment
from harness.limits import Limits
from harness.tools.errors import Denied, InvalidRequest, ToolError
from harness.tools.repo import RepositoryTools


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str  # shown to the model
    params: tuple[str, ...]  # exact argument names; all arguments are strings
    function: Callable[..., object]


class Toolbox:
    def __init__(
        self,
        repo: RepositoryTools,
        execution: ExecutionEnvironment,
        checks: dict[str, str],
        limits: Limits,
    ):
        self.repo = repo
        self.execution = execution
        # Only these check names may be run by the model. The acceptance check
        # is deliberately NOT in here (see task.toml): the model works on the
        # task like a developer would, and the harness grades it afterwards
        # with a test the model never saw and cannot change.
        self.checks = dict(checks)
        self.limits = limits
        specs = [
            ToolSpec("list_files", "List the repository's files.", (), repo.list_files),
            ToolSpec("read_file", "Read a UTF-8 text file.", ("path",), repo.read_file),
            ToolSpec("search_files", "Find lines containing literal text.", ("query",),
                     repo.search_files),
            ToolSpec("edit_file", "Replace `old` with `new` in a file; `old` must occur "
                     "exactly once.", ("path", "old", "new"), repo.edit_file),
            ToolSpec("write_file", "Create a NEW file. Fails if it exists.",
                     ("path", "content"), repo.write_file),
            ToolSpec("run_check", "Run a configured check in the sandbox; returns its exit "
                     "code and output.", ("name",), self.run_check),
        ]
        self.specs = {spec.name: spec for spec in specs}

    def describe(self) -> str:
        """The tool list for the system prompt."""
        lines = [f"- {s.name}({', '.join(s.params)}): {s.description}"
                 for s in self.specs.values()]
        if self.checks:
            lines.append("Checks you can run with run_check:")
            lines += [f"  - {name}: `{command}`" for name, command in self.checks.items()]
        return "\n".join(lines)

    # Pure checking, no side effects. The controller calls this BEFORE anything
    # runs, which is what the handout's "invalid request" test wants:
    # "Unknown tools or invalid arguments produce a clear error without
    # executing an action."
    def validate(self, action: dict) -> None:
        tool, args = action.get("tool"), action.get("args", {})
        if not isinstance(tool, str) or tool not in self.specs:
            raise InvalidRequest(f"unknown tool: {tool!r}. Available: {sorted(self.specs)}")
        spec = self.specs[tool]
        if not isinstance(args, dict) or set(args) != set(spec.params):
            raise InvalidRequest(f"{tool} takes exactly these arguments: {list(spec.params)}")
        for name, value in args.items():
            if not isinstance(value, str):
                raise InvalidRequest(f"argument {name!r} must be a string")
            if len(value) > self.limits.max_arg_chars:
                raise InvalidRequest(f"argument {name!r} is longer than "
                                     f"{self.limits.max_arg_chars} characters")

    # One place turns the three exception labels into results. OSError (disk,
    # permissions) and UnicodeError (file isn't UTF-8 text) are errors too: a
    # strange file must not crash the whole run.
    def run(self, action: dict) -> dict:
        self.validate(action)  # cheap, and protects callers that skipped it
        spec = self.specs[action["tool"]]
        try:
            # function(**args) spreads the dict into keyword arguments:
            # {"path": "x"} -> read_file(path="x"). Safe because validate()
            # just checked the keys are exactly the expected names.
            output = spec.function(**action.get("args", {}))
        except Denied as exc:
            return {"status": "denied", "output": str(exc)}
        except ToolError as exc:
            return {"status": "error", "output": str(exc)}
        except (OSError, UnicodeError) as exc:
            return {"status": "error", "output": f"{type(exc).__name__}: {exc}"}
        return {"status": "ok", "output": output}

    # The model picks a check by NAME; the command behind it comes from the
    # task file. So the model can never write its own shell command, which
    # removes a whole class of attacks and needs no human approval prompt.
    # A failing check is still status "ok": the tool worked, and "tests
    # fail, here's why" is exactly the information the model needs.
    def run_check(self, name: str) -> dict:
        if name not in self.checks:
            raise Denied(f"{name!r} is not a configured check. Available: {sorted(self.checks)}")
        result = self.execution.run_check(name)
        if result.status == UNAVAILABLE:
            raise ToolError(f"check {name!r} could not run: {result.output}")
        return {"check": name, "status": result.status, "exit_code": result.exit_code,
                "output": result.output, "truncated": result.truncated}
