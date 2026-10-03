"""THE file boundary. Every repository tool goes through this class.

A prompt that says "please stay in the folder" is a wish. This is the check.
The model's path arguments are untrusted input (the handout: "treat model
replies as untrusted"), so they are checked here, in code, every time.

Carried over from the lab's Runtime.resolve(), with one change: the lab had a
deny-list of protected files. Here we use an ALLOW-list of writable areas from
the task file. An allow-list fails safe: a file nobody thought about is
read-only by default, instead of writable by default.
"""

import os
from pathlib import Path, PurePosixPath

from harness.tools.errors import Denied


class PathGuard:
    def __init__(self, root: str | Path, writable: tuple[str, ...]):
        # resolve() turns the root into one absolute, final path (symlinks
        # followed), so every later comparison compares like with like.
        self.root = Path(root).resolve()
        self.writable = tuple(PurePosixPath(p.strip("/")).as_posix() for p in writable)

    # Four checks, in order:
    # 1. absolute paths: `anchor` is non-empty for "/etc", "C:\..", "\\server".
    #    (On Windows, is_absolute() alone would miss "/etc/passwd".)
    # 2. any part starting with "." -> blocks ".." AND hidden files like .git
    #    or .env (git config or secrets must never be readable or writable).
    # 3. resolve() follows symlinks to the real location. If that is outside
    #    the root, deny: a link inside the repo must not lead out of it.
    # 4. hidden parts again on the resolved path (a harmless-looking link
    #    could point at .git/...).
    def resolve(self, path: str) -> Path:
        """Repository-relative path -> absolute path, or raise Denied."""
        requested = Path(path)
        if not path or requested.anchor:
            raise Denied("path must be relative to the repository root, e.g. 'src/app.py'")
        if any(part.startswith(".") for part in requested.parts):
            raise Denied("'..' and hidden paths (starting with '.') are not allowed")
        full = (self.root / requested).resolve()
        if not full.is_relative_to(self.root):
            raise Denied("path leaves the repository")
        if any(part.startswith(".") for part in full.relative_to(self.root).parts):
            raise Denied("path resolves to a hidden file")
        return full

    def relative(self, full: Path) -> str:
        """Absolute path -> 'src/app.py' style, the form the model and git use."""
        return full.relative_to(self.root).as_posix()

    def resolve_writable(self, path: str) -> Path:
        """Like resolve(), but additionally the file must be in a writable area."""
        full = self.resolve(path)
        relative = self.relative(full)
        if not self.is_writable(relative):
            raise Denied(f"{relative} is outside the writable area {list(self.writable)}")
        return full

    # Checked on the RESOLVED path, so a symlink can't sneak a protected file
    # in. "src/app" allows "src/app" itself and everything below it, but not
    # "src/application" (that's why we compare with a trailing "/").
    # Windows ignores upper/lower case in paths, so there we compare casefolded:
    # otherwise "SRC/App/x.py" would slip past a check for "src/app".
    def is_writable(self, relative: str) -> bool:
        fold = str.casefold if os.name == "nt" else (lambda s: s)
        candidate = fold(relative)
        return any(
            candidate == fold(area) or candidate.startswith(fold(area) + "/")
            for area in self.writable
        )
