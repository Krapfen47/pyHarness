"""Run one external program with a time limit and an output limit
(carried over from the lab's run_command / kill_tree).

Two problems this solves:

1. Output. `subprocess.run(capture_output=True)` collects ALL output in memory
   before we see any of it. A program printing forever would fill the RAM.
   So a helper thread reads the output in small chunks and raises a flag as
   soon as there is more than we allow.

2. Stopping. A program can start child programs (docker starts a container,
   pytest may start more processes). Killing only the parent leaves the
   children running and maybe still writing files. So we kill the whole
   process TREE, and the caller can add its own cleanup (`on_stop`; Docker
   uses it to remove the container).
"""

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from harness.limits import clip

POLL_SECONDS = 0.2  # how often the main thread looks at the clock and the flags
CHUNK = 4096


@dataclass
class ProcessResult:
    exit_code: int | None  # None if we had to kill it
    output: str  # stdout and stderr merged, clipped to the limit
    truncated: bool  # output was shortened
    stop_reason: str | None  # None = finished by itself; "timeout" or "output_limit"
    duration: float


def run_process(
    argv: list[str],
    timeout: float,
    max_output: int,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    on_stop: Callable[[], None] | None = None,
) -> ProcessResult:
    """Run `argv` (a list, never a shell string) and always come back in time."""
    # A list of arguments, not one string: no shell is involved, so spaces or
    # characters like ; | & in an argument can't turn into extra commands.
    #
    # Own process group: lets us kill the tree later, and on Windows it also
    # stops Ctrl+C from hitting the child directly (we want to handle Ctrl+C
    # ourselves and clean up properly).
    if os.name == "nt":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}
    started = time.monotonic()
    process = subprocess.Popen(
        argv, cwd=cwd, env=env,
        stdin=subprocess.DEVNULL,  # a program waiting for keyboard input can't hang us
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # one merged stream
        **group,
    )

    output = bytearray()
    too_much = threading.Event()  # a thread-safe True/False flag

    # Runs in a background thread so the main thread is free to watch the clock.
    def read_output() -> None:
        while chunk := process.stdout.read1(CHUNK):
            output.extend(chunk)
            if len(output) > max_output:
                too_much.set()  # only raise the flag; the main thread does the killing
                return

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    def stop() -> None:
        if on_stop is not None:
            on_stop()  # e.g. `docker rm -f <container>` (the client alone isn't enough)
        kill_tree(process)

    # We wait in short steps instead of one long process.wait(timeout): on
    # Windows a long wait can't be interrupted by Ctrl+C, so the user would
    # be stuck until the timeout. Short steps keep Ctrl+C responsive.
    stop_reason = None
    deadline = started + timeout
    try:
        while True:
            try:
                process.wait(timeout=POLL_SECONDS)
                break  # finished by itself
            except subprocess.TimeoutExpired:
                pass
            if too_much.is_set():
                stop_reason = "output_limit"
                break
            if time.monotonic() > deadline:
                stop_reason = "timeout"
                break
    except KeyboardInterrupt:
        stop()  # clean up, then let Ctrl+C continue upwards to the controller
        raise
    if stop_reason:
        stop()

    reader.join(timeout=5)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    text, truncated = clip(output.decode("utf-8", errors="replace"), max_output)
    return ProcessResult(
        exit_code=None if stop_reason else process.returncode,
        output=text,
        truncated=truncated,
        stop_reason=stop_reason,
        duration=time.monotonic() - started,
    )


# `docker run ...` or `python -m pytest` may start children. Killing only the
# parent would leave them running. So kill the whole tree:
# - Linux/macOS: the process leads its own group (start_new_session) -> killpg.
# - Windows has no process groups in that sense; `taskkill /T` kills the
#   process and all its children, `/F` forces it.
def kill_tree(process: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           capture_output=True, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass  # it ended on its own in the meantime
