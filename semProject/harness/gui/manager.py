"""Runs one HarnessRun at a time in a background thread, and fans its events out.

Why a background thread? The web server must keep answering the browser
(stream events, accept the Stop button) while the run is busy for minutes
waiting on the model or a check. The run is ordinary blocking code, so it
gets a thread of its own, like a worker thread in Java/C#.

Why only one run at a time? Each run uses the GPU (the model) and Docker
(the checks). Two at once would just make both slow, and the demo confusing.

Getting events from the run thread to the browser:

    run thread                      web server (asyncio event loop)
    ----------                      -------------------------------
    emit(event) ──> publish() ──> loop.call_soon_threadsafe(queue.put)
                                         └──> one asyncio.Queue per open
                                              browser tab ──> SSE ──> browser

asyncio queues are NOT thread-safe, so the run thread never touches them
directly. call_soon_threadsafe() asks the event loop to do the put() itself,
on its own thread. (Same idea as Dispatcher.Invoke in C#, or postMessage
from a web worker in JS.)
"""

import asyncio
import threading
from dataclasses import asdict
from pathlib import Path

from harness.controller import Cancelled
from harness.events import TRANSIENT, EventStream, Logger, new_run_id
from harness.runner import SETUP_ERRORS, HarnessRun, RunRequest

# Put into a browser's queue when it falls too far behind (see Subscriber).
# Its stream then ends, and the browser reconnects and catches up.
OVERFLOW = {"type": "_overflow"}


class RunBusy(RuntimeError):
    """A run is already in progress."""


class LiveRun:
    def __init__(self, run_id: str, harness: HarnessRun, emit):
        self.run_id = run_id
        self.harness = harness
        self.emit = emit
        self.events: list[dict] = []  # every stored event so far, for tabs that join late
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()


class Subscriber:
    """One open browser tab: its event loop and its own queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        self.loop = loop
        self.queue = queue

    def deliver(self, event: dict) -> None:
        """Called on the run thread. Hands the event to the loop's thread."""
        try:
            self.loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:
            pass  # the server is shutting down and its loop is closed

    def _put(self, event: dict) -> None:  # runs on the loop's thread
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # A tab that doesn't read (e.g. frozen) must not let memory grow
            # forever. Make room for one marker that ends its stream.
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(OVERFLOW)


class RunManager:
    def __init__(self, runs_dir: Path, harness_factory=HarnessRun):
        self.runs_dir = runs_dir
        # harness_factory: tests pass one that builds a HarnessRun with a fake sandbox.
        self.harness_factory = harness_factory
        self.current: LiveRun | None = None  # the running run, or the last one
        self.subscribers: set[Subscriber] = set()
        # Protects `current`, each run's event list and `subscribers`, which
        # the run thread and the web server's threads both use.
        self.lock = threading.Lock()

    # ---- starting and stopping ----

    def start(self, request: RunRequest) -> str:
        with self.lock:
            if self.current is not None and self.current.running:
                raise RunBusy(f"run {self.current.run_id} is still in progress")
            run_id = new_run_id(request.mode)
            logger = Logger(self.runs_dir / f"{run_id}.jsonl")
            live: LiveRun | None = None

            def publish(event: dict) -> None:
                self.publish(live, event)

            stream = EventStream(run_id, [logger.write, publish])
            live = LiveRun(run_id, self.harness_factory(request, stream.emit), stream.emit)
            live.thread = threading.Thread(target=self._work, args=(live, logger, request),
                                           name=f"run-{run_id}", daemon=True)
            self.current = live
        live.thread.start()
        return run_id

    def _work(self, live: LiveRun, logger: Logger, request: RunRequest) -> None:
        """The body of the run thread."""
        try:
            # First event: what the user asked for (so the log records it too).
            live.emit({"type": "launch", "request": asdict(request)})
            live.harness.execute()
        except (*SETUP_ERRORS, Cancelled):
            pass  # already reported as events by HarnessRun
        except Exception as exc:  # a bug: still tell the browser, never die silently
            live.emit({"type": "error", "message": f"internal error: {type(exc).__name__}: {exc}"})
            live.emit({"type": "finished", "status": "error", "passed": False})
        finally:
            logger.close()

    def stop(self, run_id: str) -> bool:
        """Press Stop. Returns False if that run isn't running."""
        live = self.current
        if live is None or live.run_id != run_id or not live.running:
            return False
        live.harness.stop()
        return True

    def shutdown(self, timeout: float = 20) -> None:
        """Server is quitting: stop a running run and give it time to clean up."""
        live = self.current
        if live is not None and live.running:
            live.harness.stop()
            live.thread.join(timeout)

    # ---- events ----

    def publish(self, live: LiveRun, event: dict) -> None:
        with self.lock:
            if event["type"] not in TRANSIENT:
                live.events.append(event)
            subscribers = list(self.subscribers)
        for subscriber in subscribers:
            subscriber.deliver(event)

    def subscribe(self, subscriber: Subscriber) -> list[dict]:
        """Register a browser tab. Returns the current run's events so far.

        Both happen under the lock, so no event can fall into the gap between
        "copied the old events" and "registered for new ones".
        """
        with self.lock:
            self.subscribers.add(subscriber)
            return list(self.current.events) if self.current else []

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self.lock:
            self.subscribers.discard(subscriber)

    def active_run(self) -> str | None:
        live = self.current
        return live.run_id if live is not None and live.running else None
