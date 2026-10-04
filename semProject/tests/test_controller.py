"""Handout test "Controller": a scripted model reply calls the correct tool and
receives its result."""

import json
import threading

from conftest import PRICING

from harness.controller import CANCELLED, FINAL, MODEL_ERROR, AgentController
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

    # model_token events (the streamed pieces) are left out here; their
    # number depends on how long the reply is.
    assert [e["type"] for e in events if e["type"] != "model_token"] == [
        "context",
        "model_call", "model_reply", "request", "result", "observation",  # turn 1
        "model_call", "model_reply",  # turn 2: the final answer
        "stop",
    ]
    assert events[-1]["stop_reason"] == FINAL


def test_events_show_what_the_model_saw_and_said(toolbox, limits):
    events = []
    model = ScriptedModel([{"tool": "list_files", "args": {}}, {"final": "done"}])
    AgentController(model, toolbox, limits, emit=events.append).run_task("Look around")
    by_type = {}
    for event in events:
        by_type.setdefault(event["type"], []).append(event)

    # The opening messages are exactly the ones the model got on turn 1.
    assert by_type["context"][0]["messages"] == model.calls[0]
    # Glued together, the streamed pieces of turn 1 are the full raw reply.
    pieces = "".join(e["text"] for e in by_type["model_token"] if e["turn"] == 1)
    assert pieces == by_type["model_reply"][0]["reply"] == model.replies[0]
    # The observation event is exactly the message the model saw next.
    assert by_type["observation"][0]["content"] == model.calls[1][-1]["content"]
    assert by_type["result"][0]["budget"]["actions"] == 1


def test_invalid_reply_reports_which_gate_failed(toolbox, limits):
    events = []
    model = ScriptedModel(["not json", {"tool": "shell", "args": {}},
                           {"tool": "read_file", "args": {}}, {"final": "done"}])
    AgentController(model, toolbox, limits, emit=events.append).run_task("x")
    assert [e["gate"] for e in events if e["type"] == "invalid"] == ["json", "tool", "args"]


def test_stop_flag_ends_the_run_before_the_next_turn(toolbox, limits):
    cancel = threading.Event()

    class StopsDuringFirstReply(ScriptedModel):
        def request_action(self, messages, on_token=None):
            cancel.set()  # the user presses Stop while the model is answering
            return super().request_action(messages)

    model = StopsDuringFirstReply([{"tool": "list_files", "args": {}}], repeat_last=True)
    outcome = AgentController(model, toolbox, limits, cancel=cancel).run_task("x")
    assert outcome.stop_reason == CANCELLED
    assert len(model.calls) == 1  # no second model call after Stop


def test_stop_during_streaming_aborts_the_reply(toolbox, limits):
    cancel = threading.Event()

    class SlowModel:
        def request_action(self, messages, on_token=None):
            on_token("content", '{"tool": ')
            cancel.set()  # Stop pressed in the middle of the reply
            on_token("content", '"list_files", "args": {}}')  # raises Cancelled
            raise AssertionError("the reply should have been aborted")

    events = []
    outcome = AgentController(SlowModel(), toolbox, limits, emit=events.append,
                              cancel=cancel).run_task("x")
    assert outcome.stop_reason == CANCELLED
    assert outcome.actions == 0
    # What the model had written before Stop is kept, for the log and the GUI.
    aborted = next(e for e in events if e["type"] == "model_aborted")
    assert aborted["partial"] == '{"tool": '


def test_a_model_error_keeps_the_reason_on_its_turn(toolbox, limits):
    events = []
    AgentController(ScriptedModel([]), toolbox, limits, emit=events.append).run_task("x")
    aborted = next(e for e in events if e["type"] == "model_aborted")
    assert aborted["turn"] == 1 and "ScriptExhausted" in aborted["reason"]


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
