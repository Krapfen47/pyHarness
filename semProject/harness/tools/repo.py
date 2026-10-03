"""Repository tools: list, read, search, edit, create (carried over from the lab).

Every path argument goes through PathGuard first. None of these functions
decides on its own what is allowed; they only do the work once the guard said
yes. That split ("the guard decides, the tool does") keeps the security rules
in one file that is easy to review and test.
"""

import os
from pathlib import Path

from harness.limits import Limits, clip
from harness.tools.errors import ToolError
from harness.tools.lint import new_problems
from harness.tools.paths import PathGuard

# Folders that are never interesting and often huge.
SKIP_DIRS = {"__pycache__", "node_modules"}


class RepositoryTools:
    def __init__(self, guard: PathGuard, limits: Limits):
        self.guard = guard
        self.limits = limits

    # Walks the tree WITHOUT following symlinked folders and skips hidden
    # folders (.git, .venv). `dirs[:] = ...` edits the list os.walk is about to
    # visit; that in-place assignment is how you prune an os.walk.
    def walk_files(self):
        """Yield repository-relative file paths, sorted, hidden things skipped."""
        root = self.guard.root
        for folder, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
            for name in sorted(files):
                if not name.startswith("."):
                    yield (Path(folder) / name).relative_to(root).as_posix()

    def list_files(self) -> dict:
        files = []
        for path in self.walk_files():
            if len(files) == self.limits.max_files:
                return {"files": files, "truncated": True}
            files.append(path)
        return {"files": files, "truncated": False}

    # newline="" means "give me the file exactly as it is": Python would
    # otherwise silently turn Windows line endings (\r\n) into \n. If we did
    # that, an edit would rewrite every line ending and the diff would show
    # the whole file as changed.
    def read_file(self, path: str) -> dict:
        full = self.guard.resolve(path)
        if not full.is_file():
            raise ToolError(f"not a file: {path}")
        with open(full, encoding="utf-8", newline="") as file:
            content = file.read(self.limits.max_output_chars + 1)  # +1 tells us there's more
        content, truncated = clip(content, self.limits.max_output_chars)
        return {"path": path, "content": content, "truncated": truncated}

    # Plain text search (not regex: a regex from the model could be slow on
    # purpose, and plain text is what small models get right anyway).
    # Binary or very large files are skipped instead of crashing the search.
    def search_files(self, query: str) -> dict:
        if not query:
            raise ToolError("query must not be empty")
        matches = []
        for path in self.walk_files():
            full = self.guard.root / path
            if full.is_symlink() or full.stat().st_size > self.limits.max_file_bytes:
                continue
            try:
                text = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # a binary file
            for number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    if len(matches) == self.limits.max_matches:
                        return {"matches": matches, "truncated": True}
                    matches.append({"path": path, "line": number, "text": line.strip()[:200]})
        return {"matches": matches, "truncated": False}

    # `old` must occur EXACTLY once. This forces the model to quote a unique
    # piece of code, so it can't change the wrong spot by accident. When it
    # fails, the error says how to fix it (re-read the file), which is what
    # small models need to recover.
    def edit_file(self, path: str, old: str, new: str) -> str:
        full = self.guard.resolve_writable(path)
        if not full.is_file():
            raise ToolError(f"not a file: {path} (use write_file to create a new file)")
        if full.stat().st_size > self.limits.max_file_bytes:
            raise ToolError(f"{path} is too large to edit")
        with open(full, encoding="utf-8", newline="") as file:
            text = file.read()
        # Special case: an EMPTY file (like many __init__.py) has no text to
        # quote, so `old` = "" means "fill the empty file". Without this,
        # neither edit_file nor write_file could ever put text into it.
        if not old:
            if text:
                raise ToolError("old must not be empty (old='' only works on an empty file)")
            with open(full, "w", encoding="utf-8", newline="") as file:
                file.write(new)
            return f"edited {path}" + lint_report(path, text, new)
        count = text.count(old)
        if count != 1:
            raise ToolError(
                f"old text occurs {count} times in {path}; it must occur exactly once. "
                "Re-read the file and copy the exact lines, including indentation."
            )
        updated = text.replace(old, new, 1)
        with open(full, "w", encoding="utf-8", newline="") as file:
            file.write(updated)
        return f"edited {path}" + lint_report(path, text, updated)

    # Mode "x" = create, fail if it exists. The operating system does that
    # check and the creation as one step; a separate `if exists(): ...` could
    # be fooled if something changed the folder in between.
    def write_file(self, path: str, content: str) -> str:
        full = self.guard.resolve_writable(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(full, "x", encoding="utf-8", newline="") as file:
                file.write(content)
        except FileExistsError:
            raise ToolError(f"{path} already exists; use edit_file to change it") from None
        return f"created {path}" + lint_report(path, "", content)


# The edit is kept even if it has problems: the model may be halfway through a
# change that needs two edits (e.g. first use a name, then define it). We only
# make sure it KNOWS, instead of finding out much later from a failing test.
def lint_report(path: str, before: str, after: str) -> str:
    if not path.endswith(".py"):
        return ""
    problems = new_problems(before, after, path)
    if not problems:
        return ""
    lines = "\n".join(f"  {p}" for p in problems)
    return (f"\nWARNING: the file was saved, but this change introduced problems that "
            f"will make the code fail when it runs:\n{lines}\nFix them next.")
