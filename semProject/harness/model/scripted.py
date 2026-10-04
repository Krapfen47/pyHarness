"""A fake model that replies from a script. Used by the tests and for dry runs.

The handout: "Use scripted replies for repeatable controller tests." A real
model gives different answers from run to run and needs a running server. A
script gives the SAME answers every time, so a failing test always points at
our code, never at the model's mood.
"""

import json
import time

from harness.model.base import Message, OnToken


class ScriptExhausted(RuntimeError):
    """The controller asked for more replies than the script contains."""


class ScriptedModel:
    """Returns the scripted replies in order. Fits the ModelClient protocol.

    Replies may be strings (sent exactly as written, so tests can send broken
    JSON on purpose) or dicts (turned into JSON for convenience).
    """

    # pace: seconds to wait between streamed pieces. 0 (the default, used by
    # all tests) means instant. The GUI's "scripted demo" run uses a small
    # value so you can watch the reply being "typed", like a real model's.
    def __init__(self, replies: list[str | dict], repeat_last: bool = False, pace: float = 0.0):
        self.replies = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        # repeat_last=True simulates a model stuck in a loop: it keeps sending
        # the same request forever. The action-limit test relies on this.
        self.repeat_last = repeat_last
        self.pace = pace
        # A copy of what the model was shown on every call. Tests read this to
        # check e.g. that a tool result really came back to the model.
        self.calls: list[list[Message]] = []

    def request_action(self, messages: list[Message], on_token: OnToken | None = None) -> str:
        # Copy the list: the controller keeps appending to the original, and we
        # want a snapshot of what the model saw at THIS moment.
        self.calls.append([dict(m) for m in messages])
        index = len(self.calls) - 1
        if index < len(self.replies):
            reply = self.replies[index]
        elif self.repeat_last and self.replies:
            reply = self.replies[-1]
        else:
            raise ScriptExhausted(f"script has only {len(self.replies)} replies")
        if on_token:
            # Pretend to stream: hand the reply over in small pieces, the way
            # a real model does. Lets the GUI be tested without Ollama.
            for start in range(0, len(reply), 12):
                on_token("content", reply[start:start + 12])
                if self.pace:
                    time.sleep(self.pace)
        return reply

    @property
    def last_observation(self) -> dict:
        """The newest tool result the model was shown, parsed back from JSON."""
        return json.loads(self.calls[-1][-1]["content"])
