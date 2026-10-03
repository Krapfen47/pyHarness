"""Lint on edit: after every change to a .py file, look for mistakes the edit
just introduced, and tell the model right away.

Why: in our first real runs, the 7B model kept using a name it had never
defined or imported (e.g. raising InvalidBatchRef in one file but defining it
in another). The existing tests didn't touch that code path, so they still
passed and the model believed it was done. A static check spots this the
moment the edit is made. Harnesses like SWE-agent do the same.

pyflakes only PARSES the code (reads it like a text), it never runs it. That
is why it is safe to use on the host, outside the sandbox.

Two choices keep the feedback useful for a small model:
- only serious problems (undefined names, syntax errors), no style nits;
- only problems that are NEW after the edit. Old problems in the file are
  not the model's fault and would only distract it.
"""

from collections import Counter

import pyflakes.api
import pyflakes.messages as pm

# Problems that almost always mean "this code will crash when it runs".
SERIOUS = (pm.UndefinedName, pm.UndefinedLocal, pm.UndefinedExport)


class _Collector:
    """pyflakes reports through an object with these three methods."""

    def __init__(self):
        self.problems: list[tuple[int, str]] = []  # (line number, description)

    def unexpectedError(self, filename, message):  # noqa: N802 (name set by pyflakes)
        self.problems.append((0, f"could not check the file: {message}"))

    def syntaxError(self, filename, message, lineno, offset, text):  # noqa: N802
        self.problems.append((lineno or 0, f"syntax error: {message}"))

    def flake(self, message):
        if isinstance(message, SERIOUS):
            self.problems.append((message.lineno, message.message % message.message_args))


def find_problems(code: str, filename: str = "file.py") -> list[tuple[int, str]]:
    collector = _Collector()
    pyflakes.api.check(code, filename, collector)
    return collector.problems


def new_problems(before: str, after: str, filename: str = "file.py") -> list[str]:
    """Problems in `after` that weren't already in `before`, as 'line N: ...' texts.

    Compared by description only (not line number), because an edit that adds
    lines at the top shifts every old problem to a new line number. Counter
    is a multiset: two old "undefined name 'x'" plus one new one = one new.
    """
    old = Counter(text for _, text in find_problems(before, filename))
    found = []
    for line, text in find_problems(after, filename):
        if old[text] > 0:
            old[text] -= 1
        else:
            found.append(f"line {line}: {text}")
    return found
