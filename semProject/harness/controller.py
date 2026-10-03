"""The agent loop (carried over from the lab's run_agent, plus counters and limits).

The handout's Figure 3, in code:

    messages = [rules, task]
    loop:
        reply  = model.request_action(messages)   ask the model for an action
        action = validate_action(reply)           check shape, tool, arguments
        if action is "final" -> stop              (the model THINKS it's done)
        result = toolbox.run(action)              run it, or get "denied"/"error"
        append reply + result to messages         return the result to the model
    stop on: final answer, a limit, a model error, or Ctrl+C

A language model has no memory between calls. Every turn it gets the whole
conversation again and replies with ONE next step. The "agent" is nothing
more than this loop growing that list of messages.

The rule from the lab still holds: the model PROPOSES, the harness DECIDES.
This file never touches files itself; it only routes requests through the
checks in Toolbox / PathGuard and counts what happens.

Why this loop always ends: every turn either ends the run, adds 1 to
`actions`, or adds 1 to `retries`. Both have a hard limit. So the number of
model calls is at most max_actions + max_retries + 1, no matter what the
model does.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass

from harness.context import build_messages
from harness.limits import Limits, clip
from harness.model.base import Message, ModelClient
from harness.tools.errors import InvalidRequest
from harness.tools.toolbox import Toolbox

# How a run can end. Only "final" means the model claims success, and even
# that is checked afterwards by verification.py.
FINAL = "final"
ACTION_LIMIT = "action_limit"
RETRY_LIMIT = "retry_limit"
DENIED_LIMIT = "denied_limit"
MODEL_ERROR = "model_error"
CANCELLED = "cancelled"

# Tools that change files. After one of them succeeds, earlier results (file
# contents, test output) may be outdated, so repeating a request is fine again.
WRITE_TOOLS = {"edit_file", "write_file"}


@dataclass
class RunOutcome:
    stop_reason: str
    reason: str  # one sentence for humans
    final_message: str | None  # the model's own summary, if it gave one
    turns: int  # model calls
    actions: int  # tool requests that passed validation (ok, error or denied)
    retries: int  # unusable replies the model had to redo
    denied: int  # requests our policy refused
    errors: int  # allowed requests that failed (file not found, ...)
    repeats: int = 0  # requests identical to an earlier one, with no file change in between

    def to_dict(self) -> dict:
        return asdict(self)


Event = dict
Emit = Callable[[Event], None]

# Small models easily get stuck in a cycle (read file, run tests, read file,
# run tests, ...). Repeating an action when no file changed in between can't
# give a new answer, so we tell the model that, in plain words. It's only a
# hint; the hard stop is still the action limit.
REPEAT_NOTE = ("You already made this exact request and no file has changed since, so the "
               "result is the same as before. Do something different: fix the problem the "
               "last check output shows, or give a final answer.")


class AgentController:
    def __init__(self, model: ModelClient, toolbox: Toolbox, limits: Limits,
                 emit: Emit | None = None):
        self.model = model
        self.toolbox = toolbox
        self.limits = limits
        # emit: an optional "listener" for progress events. The CLI prints
        # and logs them; tests can collect them in a list. The controller
        # itself never prints, so it stays easy to test.
        self.emit = emit or (lambda event: None)

    # ---- step 2 of the loop: is this reply a valid action? ----

    def validate_action(self, reply: str) -> dict:
        """Turn the model's text into an action dict, or raise InvalidRequest.

        Checks, in order: valid JSON; a JSON object (`[1,2]` and `"hi"` are
        valid JSON too); one of the two allowed shapes; and for tools, a known
        tool with exactly the right arguments (Toolbox.validate). Nothing runs
        here, so a bad reply can't have side effects.
        """
        try:
            action = json.loads(reply)
        except json.JSONDecodeError as exc:
            raise InvalidRequest(f"reply is not valid JSON: {exc}") from None
        if not isinstance(action, dict):
            raise InvalidRequest("reply must be one JSON object")

        if set(action) == {"final"}:  # set(dict) = the set of its keys
            if not isinstance(action["final"], str) or not action["final"].strip():
                raise InvalidRequest('"final" must be a non-empty string')
            return action
        if "tool" in action and set(action) <= {"tool", "args"}:  # <= on sets: "subset of"
            self.toolbox.validate(action)
            return action
        raise InvalidRequest('expected {"tool": ..., "args": {...}} or {"final": "..."}')

    # ---- the loop ----

    def run_task(self, request: str, context: str = "") -> RunOutcome:
        messages = build_messages(request, self.toolbox.describe(), context)
        turns = actions = retries = denied = errors = repeats = 0
        # Every request made since the last successful file change, as text.
        # A set gives a fast "have we seen this before?" check.
        seen_since_change: set[str] = set()

        # Every exit goes through here: build the outcome, emit a "stop"
        # event, return. One helper means no exit can forget the log entry.
        def finish(stop_reason: str, reason: str, final: str | None = None) -> RunOutcome:
            outcome = RunOutcome(stop_reason, reason, final, turns, actions, retries,
                                 denied, errors, repeats)
            self.emit({"type": "stop", **outcome.to_dict()})
            return outcome

        while True:
            turns += 1
            # 1. Ask the model. KeyboardInterrupt (Ctrl+C) is not an Exception
            # subclass, precisely so a careless `except Exception` can't
            # swallow it; it needs its own clause.
            try:
                reply = self.model.request_action(messages)
            except KeyboardInterrupt:
                return finish(CANCELLED, "interrupted by the user")
            except Exception as exc:
                return finish(MODEL_ERROR, f"{type(exc).__name__}: {exc}")
            # Keep the reply even if it's broken: the model should see what it
            # said, followed by the error explaining what was wrong with it.
            messages.append({"role": "assistant", "content": reply})

            # 2. Check it. A bad reply costs a retry, and the model is told why.
            try:
                action = self.validate_action(reply)
            except InvalidRequest as exc:
                retries += 1
                self.emit({"type": "invalid", "turn": turns, "error": str(exc),
                           "reply": reply[:500]})
                if retries > self.limits.max_retries:
                    return finish(RETRY_LIMIT, f"{retries} unusable replies")
                messages.append(self.observation({"status": "invalid", "error": str(exc)}))
                continue

            # 3. A final answer ends the loop. It's a claim, not proof.
            if "final" in action:
                return finish(FINAL, "the model says it is done", action["final"])

            # 4. Action limit. Checked BEFORE running, so the limit really
            # stops further actions instead of reporting them afterwards.
            if actions >= self.limits.max_actions:
                return finish(ACTION_LIMIT, f"reached the limit of {actions} actions")
            actions += 1

            # 5. Run it. The toolbox shouldn't raise, but if it has a bug, the
            # crash becomes an error result instead of killing the run.
            self.emit({"type": "request", "turn": turns, "action": action})
            try:
                result = self.toolbox.run(action)
            except KeyboardInterrupt:
                return finish(CANCELLED, "interrupted during a tool call")
            except Exception as exc:
                result = {"status": "error", "output": f"harness failure: {exc}"}
            self.emit({"type": "result", "turn": turns, "tool": action["tool"],
                       "result": result})

            if result["status"] == "denied":
                denied += 1
                if denied > self.limits.max_denied:
                    return finish(DENIED_LIMIT, f"{denied} requests were denied")
            elif result["status"] == "error":
                errors += 1

            # Repeat detection. sort_keys makes the text identical for identical
            # requests, whatever order the model wrote the arguments in.
            key = json.dumps(action, sort_keys=True)
            observation = {"tool": action["tool"], **result}
            if key in seen_since_change:
                repeats += 1
                observation["note"] = REPEAT_NOTE
                self.emit({"type": "repeat", "turn": turns, "tool": action["tool"]})
            seen_since_change.add(key)
            if action["tool"] in WRITE_TOOLS and result["status"] == "ok":
                seen_since_change.clear()  # files changed: old results are outdated now

            # 6. Return the result to the model, so it can pick the next step.
            messages.append(self.observation(observation))

    # Tool results go back as a "user" message containing JSON labelled
    # untrusted_data. If a tool forgot to clip its output, the safety net
    # here still keeps the message within the limit, and says so.
    def observation(self, payload: dict) -> Message:
        text = json.dumps({"source": "untrusted_data", **payload}, ensure_ascii=False)
        if len(text) > self.limits.max_observation_chars:
            output = payload.get("output")
            output = output if isinstance(output, str) else json.dumps(output,
                                                                        ensure_ascii=False)
            clipped, _ = clip(output, self.limits.max_output_chars)
            payload = {**payload, "output": clipped, "truncated": True}
            text = json.dumps({"source": "untrusted_data", **payload}, ensure_ascii=False)
        return {"role": "user", "content": text}
