"""Every number that keeps a run bounded, in one place.

Why one file: the handout asks us to "enforce action and output limits". If the
numbers were spread over ten files, nobody (including you in three weeks) could
say what the limits actually are. `frozen=True` means no code can quietly
change a limit halfway through a run.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    # ---- the agent loop (controller.py) ----
    # A "turn" costs one model call. Every turn either runs a tool (an action),
    # gets rejected as unusable (a retry), or ends the run. So these three
    # numbers together put a hard ceiling on how long a run can take.
    max_actions: int = 30  # tool calls the model may make in one run
    max_retries: int = 6  # unusable replies: bad JSON, unknown tool, wrong arguments
    max_denied: int = 6  # requests our policy refused, e.g. a path outside the repo

    # ---- output that goes back to the model ----
    # Small local models have a small "context window" (how much text they can
    # see at once). One huge tool result would push the task description out
    # of it, so every result is cut to this size and marked as shortened.
    max_output_chars: int = 12_000
    # Hard cap for one whole message back to the model, as a safety net in
    # case a tool forgets to clip. Bigger than the one above because putting
    # text into JSON adds escape characters (a newline becomes "\n").
    max_observation_chars: int = 24_000

    # ---- repository tools (tools/repo.py) ----
    max_files: int = 300  # entries returned by list_files
    max_matches: int = 50  # hits returned by search_files
    max_arg_chars: int = 20_000  # longest argument the model may send (e.g. new code)
    max_file_bytes: int = 200_000  # bigger files are not searched or edited

    # ---- execution (execution/) ----
    check_timeout: float = 180.0  # seconds for one check (a pytest run) in Docker
    build_timeout: float = 900.0  # seconds for building the sandbox image once


SHORTENED = "\n[... output shortened: only the first {limit} characters are shown]"


def clip(text: str, limit: int) -> tuple[str, bool]:
    """Cut `text` to at most `limit` characters and say whether anything was cut.

    The visible marker matters as much as the cut itself: without it, the
    model (or a human reading the log) would believe it saw everything and
    could draw wrong conclusions from half a test report.
    """
    if len(text) <= limit:
        return text, False
    return text[:limit] + SHORTENED.format(limit=limit), True
