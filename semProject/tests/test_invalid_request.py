"""Handout test "Invalid request": unknown tools or invalid arguments produce a
clear error without executing an action."""

import pytest
from conftest import snapshot

from harness.controller import FINAL, RETRY_LIMIT, AgentController
from harness.model import ScriptedModel
from harness.tools import InvalidRequest


@pytest.mark.parametrize("reply, expected_error", [
    ('{"tool": "delete_repo", "args": {}}', "unknown tool"),
    ('{"tool": "read_file", "args": {}}', "takes exactly these arguments"),
    ('{"tool": "read_file", "args": {"path": "a.py", "mode": "w"}}', "takes exactly"),
    ('{"tool": "read_file", "args": {"path": 42}}', "must be a string"),
    ('{"tool": "edit_file", "args": "src/shop/pricing.py"}', "takes exactly"),
    ("I will now read the file.", "not valid JSON"),
    ('["read_file", "a.py"]', "one JSON object"),
    ('{"tool": "list_files", "final": "done"}', "expected"),
    ('{"final": ""}', "non-empty"),
])
def test_invalid_reply_is_rejected_before_anything_runs(
        toolbox, limits, execution, repo, reply, expected_error):
    before = snapshot(repo)
    model = ScriptedModel([reply, {"final": "giving up"}])
    events = []
    outcome = AgentController(model, toolbox, limits, emit=events.append).run_task("x")

    # Nothing ran: no tool request event, no check, no file changed.
    assert "request" not in [e["type"] for e in events]
    assert execution.calls == []
    assert snapshot(repo) == before
    # The model got a clear error and a second chance, which was counted.
    error = model.calls[1][-1]["content"]
    assert expected_error in error
    assert outcome.retries == 1
    assert outcome.actions == 0
    assert outcome.stop_reason == FINAL


def test_validate_action_raises_for_unknown_tool(toolbox, limits):
    controller = AgentController(ScriptedModel([]), toolbox, limits)
    with pytest.raises(InvalidRequest, match="unknown tool: 'shell'"):
        controller.validate_action('{"tool": "shell", "args": {"command": "rm -rf /"}}')


def test_unknown_check_name_is_denied_and_never_reaches_the_sandbox(toolbox, execution):
    result = toolbox.run({"tool": "run_check", "args": {"name": "rm -rf /"}})
    assert result["status"] == "denied"
    assert execution.calls == []


def test_too_many_invalid_replies_stop_the_run(toolbox, limits):
    model = ScriptedModel(["not json"], repeat_last=True)
    outcome = AgentController(model, toolbox, limits).run_task("x")

    assert outcome.stop_reason == RETRY_LIMIT
    assert outcome.retries == limits.max_retries + 1
    assert len(model.calls) == limits.max_retries + 1
