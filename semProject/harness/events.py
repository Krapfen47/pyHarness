"""Events: the one way the harness reports what it is doing.

Every part of a run (setup, the agent loop, verification) describes each step
as a small dict, an "event", e.g.

    {"type": "request", "turn": 2, "action": {"tool": "read_file", ...}}

and hands it to `emit`. It never prints anything itself. Whoever is
interested LISTENS: the CLI prints a line, the Logger appends it to the run's
JSONL file, the GUI pushes it to the browser. This is the "observer" pattern
(an event bus / event emitter, like `EventTarget` in the browser or C# events).

Why it matters: the CLI, the log file, and the GUI all show the SAME stream,
so they can't disagree about what happened. And the GUI's History view
simply replays a log file through the same code that draws a live run.

EventStream adds three fields to every event before passing it on:
    seq      1, 2, 3, ... (order, and "which events have I already seen?")
    time     when it happened
    run_id   which run it belongs to (also the log file's name)
"""

import json
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

Listener = Callable[[dict], None]

# Events that matter only while a run is LIVE. The model's reply arrives as
# hundreds of small model_token pieces; the complete text follows in one
# model_reply event, so storing every piece in the log would only bloat it.
TRANSIENT = {"model_token"}


def new_run_id(mode: str) -> str:
    """e.g. "20261003-191123-run". It is also the log file's name."""
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{mode}"


class EventStream:
    """Numbers each event and passes it to every listener, in order."""

    def __init__(self, run_id: str, listeners: list[Listener] | None = None):
        self.run_id = run_id
        self.listeners = list(listeners or [])
        self._seq = 0
        # Two threads may emit at once (the run itself, and the GUI's Stop
        # button). The lock makes "take the next number + notify everyone"
        # one indivisible step, so listeners always see events in seq order.
        self._lock = threading.Lock()

    def emit(self, event: dict) -> None:
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "time": datetime.now().isoformat(timespec="milliseconds"),
                     "run_id": self.run_id, **event}
            for listener in self.listeners:
                listener(event)


class Logger:
    """Writes every event as one JSON line, so a run can be replayed and compared later.

    Line-buffered (buffering=1): each line hits the disk immediately, so the
    log is complete even if the run is killed halfway.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, event: dict) -> None:
        if event.get("type") in TRANSIENT:
            return
        if "time" not in event:
            event = {"time": datetime.now().isoformat(timespec="seconds"), **event}
        self.file.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")

    def close(self) -> None:
        self.file.close()
