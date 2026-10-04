"""Past runs: read the JSONL logs in semProject/runs/ for the GUI's History view.

A log file IS the run: replaying its events through the GUI redraws the run
exactly as it looked live (minus the streamed tokens, which aren't stored).
"""

import json
import re
from pathlib import Path

# A run id is also the log file's name, e.g. "20261003-191123-run". Checking
# the exact shape means a request can never smuggle in a path like "../../x".
RUN_ID = re.compile(r"^\d{8}-\d{6}-(run|baseline)$")


def read_events(path: Path) -> list[dict]:
    """All events of one log file. Skips a broken line (e.g. a half-written last line)."""
    events = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # Logs written before the GUI existed have no seq / run_id; add them, so
    # the browser can treat old and new logs the same way.
    for number, event in enumerate(events, start=1):
        event.setdefault("seq", number)
        event.setdefault("run_id", path.stem)
    return events


def summarize(run_id: str, events: list[dict]) -> dict:
    """One line for the History list: what ran, and how it ended."""
    def last(kind: str) -> dict:
        return next((e for e in reversed(events) if e.get("type") == kind), {})

    start, stop, verification, finished = last("start"), last("stop"), last("verification"), \
        last("finished")
    if finished:
        status = finished.get("status")
    elif verification:
        status = "verified" if verification.get("passed") else "not_verified"
    else:
        status = "incomplete"  # e.g. the process was killed halfway
    return {
        "run_id": run_id,
        "mode": run_id.rsplit("-", 1)[-1],
        "time": events[0].get("time") if events else None,
        "task": start.get("task"),
        "model": start.get("model"),
        "status": status,
        "stop_reason": stop.get("stop_reason"),
        "turns": stop.get("turns"),
        "events": len(events),
    }


def list_runs(runs_dir: Path) -> list[dict]:
    """Every run with a log, newest first. Empty logs are left out."""
    runs = []
    for path in sorted(runs_dir.glob("*.jsonl"), reverse=True):
        if RUN_ID.match(path.stem):
            events = read_events(path)
            if events:
                runs.append(summarize(path.stem, events))
    return runs


def load_run(runs_dir: Path, run_id: str) -> list[dict] | None:
    """All events of one run, or None if there is no such run."""
    if not RUN_ID.match(run_id):
        return None
    path = runs_dir / f"{run_id}.jsonl"
    return read_events(path) if path.is_file() else None
