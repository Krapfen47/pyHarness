"""Handout tests "Action limit" and "Output limit", plus the other limits:
denied actions, timeouts, and stopping a stuck command without leftovers."""

import dataclasses
import sys
import time

import pytest

from harness.controller import ACTION_LIMIT, DENIED_LIMIT, AgentController
from harness.execution import run_process
from harness.limits import Limits, clip
from harness.model import ScriptedModel

READ = {"tool": "read_file", "args": {"path": "src/shop/pricing.py"}}


# ---- action limit ----

def test_a_repeating_reply_hits_the_action_limit(toolbox, limits):
    events = []
    model = ScriptedModel([READ], repeat_last=True)  # a model stuck in a loop
    outcome = AgentController(model, toolbox, limits, emit=events.append).run_task("x")

    assert outcome.stop_reason == ACTION_LIMIT
    assert outcome.actions == limits.max_actions
    # Exactly max_actions tools ran; the request after that was NOT executed.
    assert sum(e["type"] == "request" for e in events) == limits.max_actions
    assert len(model.calls) == limits.max_actions + 1


def test_repeated_denied_requests_stop_the_run(toolbox, limits):
    model = ScriptedModel([{"tool": "read_file", "args": {"path": "../outside.txt"}}],
                          repeat_last=True)
    outcome = AgentController(model, toolbox, limits).run_task("x")
    assert outcome.stop_reason == DENIED_LIMIT
    assert outcome.denied == limits.max_denied + 1


# ---- output limit ----

def test_clip_marks_shortened_text():
    text, cut = clip("x" * 50, 10)
    assert cut is True
    assert text.startswith("x" * 10)
    assert "output shortened" in text
    assert clip("short", 10) == ("short", False)


def test_large_file_is_bounded_and_marked(toolbox, repo, limits):
    (repo / "src/shop/big.py").write_text("# filler\n" * 1000, encoding="utf-8")
    output = toolbox.run({"tool": "read_file", "args": {"path": "src/shop/big.py"}})["output"]
    assert output["truncated"] is True
    assert "output shortened" in output["content"]
    assert len(output["content"]) < limits.max_output_chars + 100


def test_large_process_output_is_bounded_and_stops_the_process():
    # Prints forever. Without a limit this would never end and fill the memory.
    script = "while True: print('spam' * 100)"
    started = time.monotonic()
    result = run_process([sys.executable, "-c", script], timeout=60, max_output=5_000)
    assert result.stop_reason == "output_limit"
    assert result.truncated is True
    assert "output shortened" in result.output
    assert len(result.output) < 5_100
    assert time.monotonic() - started < 30  # stopped long before the timeout


def test_observation_safety_net_bounds_any_tool_output(limits):
    class HugeToolbox:  # a buggy tool that forgot to clip its output
        def describe(self):
            return "- huge(): returns a lot"

        def validate(self, action):
            pass

        def run(self, action):
            return {"status": "ok", "output": "y" * 100_000}

    model = ScriptedModel([{"tool": "huge", "args": {}}, {"final": "done"}])
    AgentController(model, HugeToolbox(), limits).run_task("x")
    message = model.calls[1][-1]["content"]
    assert len(message) <= limits.max_observation_chars
    assert model.last_observation["truncated"] is True


# ---- timeouts and stopping ----

def test_stuck_command_is_stopped_without_leftover_children_or_writes(tmp_path):
    # The parent starts a CHILD that waits 2 s and then writes a file, then the
    # parent itself hangs. We give up after 1 s. If only the parent were
    # killed, the orphaned child would still write the file later.
    marker = tmp_path / "late-write.txt"
    child = f"import time; time.sleep(2); open({str(marker)!r}, 'w').write('too late')"
    parent = (f"import subprocess, sys, time; "
              f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(60)")

    result = run_process([sys.executable, "-c", parent], timeout=1, max_output=1000)
    assert result.stop_reason == "timeout"
    assert result.exit_code is None

    time.sleep(3)  # longer than the child would have needed
    assert not marker.exists()


def test_on_stop_hook_runs_when_a_command_is_stopped():
    stopped = []
    run_process([sys.executable, "-c", "import time; time.sleep(60)"], timeout=0.5,
                max_output=100, on_stop=lambda: stopped.append(True))
    assert stopped == [True]  # e.g. where the sandbox removes its container


def test_limits_cannot_be_changed_during_a_run():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Limits().max_actions = 1_000  # type: ignore[misc]
