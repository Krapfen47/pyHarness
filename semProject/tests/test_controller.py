"""Handout test "Controller": a scripted model reply calls the correct tool and
receives its result."""

import json

from conftest import PRICING

from harness.controller import FINAL, MODEL_ERROR, AgentController
from harness.model import ScriptedModel


def test_scripted_reply_calls_the_tool_and_gets_the_result(toolbox, limits):
    model = ScriptedModel([
        {"tool": "read_file", "args": {"path": "src/shop/pricing.py"}},
        {"final": "Read the pricing module."},
    ])
    outcome = AgentController(model, toolbox, limits).run_task("Inspect pricing")

    assert outcome.stop_reason == FINAL
    assert outcome.final_message == "Read the pricing module."
    assert outcome.actions == 1
    # The second model call must have seen the tool result as its last message.
    observation = model.calls[1][-1]
    assert observation["role"] == "user"
    result = model.last_observation
    assert result["source"] == "untrusted_data"
    assert result["tool"] == "read_file"
    assert result["status"] == "ok"
    assert result["output"]["content"] == PRICING


def test_run_check_reaches_the_execution_environment(toolbox, limits, execution):
    model = ScriptedModel([{"tool": "run_check", "args": {"name": "tests"}}, {"final": "ok"}])
    AgentController(model, toolbox, limits).run_task("Run the tests")

    assert execution.calls == ["tests"]
    assert model.last_observation["output"]["exit_code"] == 0


def test_first_message_lists_tools_checks_and_task(toolbox, limits):
    model = ScriptedModel([{"final": "nothing to do"}])
    AgentController(model, toolbox, limits).run_task("Fix the rounding bug", "context here")

    system, task = model.calls[0]
    assert "run_check(name)" in system["content"]
    assert "tests: `pytest -q`" in system["content"]
    assert "Fix the rounding bug" in task["content"]
    assert "context here" in task["content"]


def test_every_step_is_reported_as_an_event(toolbox, limits):
    events = []
    model = ScriptedModel([{"tool": "list_files", "args": {}}, {"final": "done"}])
    AgentController(model, toolbox, limits, emit=events.append).run_task("Look around")

    assert [e["type"] for e in events] == ["request", "result", "stop"]
    assert events[-1]["stop_reason"] == FINAL


def test_repeating_a_request_without_changes_gets_a_note(toolbox, limits):
    read = {"tool": "read_file", "args": {"path": "src/shop/pricing.py"}}
    edit = {"tool": "edit_file", "args": {"path": "src/shop/pricing.py",
                                          "old": "sum(prices)", "new": "sum(prices) or 0"}}
    model = ScriptedModel([read, read, edit, read, {"final": "done"}])
    outcome = AgentController(model, toolbox, limits).run_task("x")

    notes = [("note" in json.loads(call[-1]["content"])) for call in model.calls[1:]]
    # 1st read: new. 2nd read: repeat -> note. edit: new. 3rd read: the file
    # changed in between, so it's a fair new question -> no note.
    assert notes == [False, True, False, False]
    assert outcome.repeats == 1


def test_a_model_failure_ends_the_run_cleanly(toolbox, limits):
    model = ScriptedModel([])  # no replies at all: the first call raises
    outcome = AgentController(model, toolbox, limits).run_task("anything")
    assert outcome.stop_reason == MODEL_ERROR
    assert "ScriptExhausted" in outcome.reason
    assert outcome.actions == 0
