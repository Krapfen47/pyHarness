"""Tool registry and permission boundary.

The runtime DECIDES. The model only produces {"tool": ..., "args": ...}; every
request goes through one pipeline, and each step can stop it:

    execute(action)
      dispatch
        1. right shape?          no -> error
        2. known tool?           no -> error
        3. allowed right now?    no -> denied   (enabled list + mode)
        4. exactly the right args, all strings, not too long?   no -> error
        5. call the tool function
             path tools: resolve() / resolve_writable()  -> denied if outside/protected
             bash: approve(command, cwd) must return True -> denied otherwise
      package as {"status": "ok" | "error" | "denied", "output": ...}

"error"  = the request was fine in principle but did not work (missing file,
           text not found, network down) -> retrying differently may help.
"denied" = policy said no -> retrying the same thing will not help.
"""

import os
import signal
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# All limits from the handout, in one place.
MAX_TEXT = 12_000  # chars per argument / read, bytes per edited file / command output
MAX_FILES = 200
MAX_MATCHES = 50
BASH_TIMEOUT = 20
FETCH_TIMEOUT = 10

READ_ONLY_TOOLS = {"list_files", "read_file", "search_files", "fetch_url"}
PROTECTED_FILES = {"orders/validation.py", "tests/test_acceptance.py", "docs/business-rules.md"}
DOCS_HOST = "docs.python.org"

# `bash` on Windows' PATH is usually the WSL launcher, so use Git Bash there.
# Override with the AGENT_BASH environment variable (e.g. once WSL works).
BASH = os.environ.get("AGENT_BASH") or (
    r"C:\Program Files\Git\bin\bash.exe" if os.name == "nt" else "/bin/bash"
)
# Only what local commands need. Everything else (API keys!) stays out.
# SYSTEMROOT is required on Windows or Python/bash fail to start.
BASH_ENV_KEYS = ("PATH", "HOME", "LANG", "TEMP", "TMP", "SYSTEMROOT")


# Two exception types used as labels: deep inside a tool, code just raises
# Denied(...) or ToolError(...), and execute() turns that into the right status
# in one place. No tool has to build result dicts itself.
class Denied(Exception):
    """Policy refused the action."""


class ToolError(Exception):
    """Action was allowed but failed."""


# Following redirects would let an approved URL send us anywhere, so we refuse
# them: returning None makes urllib raise HTTPError for the 3xx instead.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # urllib then raises HTTPError instead of following


class Runtime:
    """Validate and execute model-requested tools inside a workspace."""

    def __init__(self, root, mode="read-only", enabled=None, approve=None, offline=None):
        """`offline`: path to a fixture file that replaces live fetch_url responses."""
        if mode not in ("read-only", "edit"):
            raise ValueError(f"unknown mode: {mode}")
        self.root = Path(root).resolve()
        self.mode = mode
        # Safe default: without an approver, every bash command is denied.
        self.approve = approve or (lambda _command, _cwd: False)
        # A path (not True/False) because the injection exercise needs a
        # different fixture (web-injected.txt) than the normal run.
        self.offline = Path(offline) if offline else None

        # The registry: name -> (description, argument names, function).
        # Everything else is driven by this table: describe_tools builds the
        # prompt from it, dispatch checks arguments against it and calls the
        # function. Adding a tool = adding a line, no `if tool == ...` chains.
        self.registry = {
            "list_files": ("List up to 200 workspace files.", (), self.list_files),
            "read_file": ("Read a UTF-8 text file.", ("path",), self.read_file),
            "search_files": ("Find literal text in files.", ("query",), self.search_files),
            "write_file": (
                "Create a NEW file. Fails if it exists.", ("path", "content"), self.write_file
            ),
            "edit_file": (
                "Replace `old` with `new`; `old` must occur exactly once.",
                ("path", "old", "new"),
                self.edit_file,
            ),
            "fetch_url": ("GET an https://docs.python.org page.", ("url",), self.fetch_url),
            "bash": ("Run a shell command after human approval.", ("command",), self.bash),
        }
        # Unknown names fail immediately: a typo in --tools should crash at
        # startup, not silently disable a tool.
        self.enabled = set(self.registry) if enabled is None else set(enabled)
        unknown = self.enabled - set(self.registry)
        if unknown:
            raise ValueError(f"unknown tools: {sorted(unknown)}")

    # ---- policy ----

    # The whole permission table from the handout in one line. Used twice:
    # to build the prompt (the model only hears about usable tools) and again
    # at dispatch (the model can request a tool it was never told about; the
    # handout explicitly requires this second check).
    def allowed(self, tool):
        return tool in self.enabled and (self.mode == "edit" or tool in READ_ONLY_TOOLS)

    def describe_tools(self):
        """Tool list for the system prompt: only what may actually run."""
        lines = [
            f"- {name}({', '.join(arg_names)}): {description}"
            for name, (description, arg_names, _) in self.registry.items()
            if self.allowed(name)
        ]
        return "\n".join(lines) or "(no tools available)"

    # Turns the exceptions from dispatch/tools into result dicts. OSError (disk,
    # permissions) and UnicodeError (not UTF-8) become errors too: a broken
    # file should not crash the agent.
    def execute(self, action):
        """Validate one action, enforce policy, and return a result object."""
        try:
            output = self.dispatch(action)
        except Denied as exc:
            return {"status": "denied", "output": str(exc)}
        except ToolError as exc:
            return {"status": "error", "output": str(exc)}
        except (OSError, UnicodeError) as exc:
            return {"status": "error", "output": f"{type(exc).__name__}: {exc}"}
        return {"status": "ok", "output": output}

    # Steps 1-5 of the pipeline. Permission (3) comes BEFORE argument checks
    # (4), so e.g. bash in read-only mode is refused before its arguments are
    # even looked at, and the approval prompt is never reached.
    def dispatch(self, action):
        is_dict = isinstance(action, dict)
        if not (is_dict and "tool" in action and set(action) <= {"tool", "args"}):
            raise ToolError('action must look like {"tool": ..., "args": {...}}')
        tool, args = action["tool"], action.get("args", {})
        if tool not in self.registry:
            raise ToolError(f"unknown tool: {tool!r}")
        if not self.allowed(tool):
            raise Denied(f"{tool} is not allowed (mode={self.mode})")

        _, arg_names, function = self.registry[tool]
        if not isinstance(args, dict) or set(args) != set(arg_names):
            raise ToolError(f"{tool} takes exactly these arguments: {list(arg_names)}")
        for name, value in args.items():
            if not isinstance(value, str):
                raise ToolError(f"argument {name} must be a string")
            if len(value) > MAX_TEXT:
                raise ToolError(f"argument {name} is longer than {MAX_TEXT} characters")
        # function(**args) spreads the dict into keyword arguments:
        # {"path": "x"} -> read_file(path="x"). Safe only because the keys were
        # just checked to be exactly the expected names.
        return function(**args)

    # THE file boundary. A prompt saying "stay in the folder" is not a path
    # check; this is. Four checks, in order:
    # 1. absolute paths: anchor is non-empty for "/etc", "C:\..", "\\server".
    #    (On Windows, is_absolute() alone would miss "/etc/passwd".)
    # 2. any part starting with "." -> covers ".." AND hidden (.git, .venv).
    # 3. resolve() follows symlinks to the real location; if that is outside
    #    the root, deny. This catches a link pointing outside the workspace.
    # 4. hidden parts again on the resolved path (a harmless-looking link could
    #    point at .git/...).
    def resolve(self, path):
        """Workspace-relative path -> absolute path, or Denied."""
        requested = Path(path)
        if not path or requested.anchor:  # anchor = "/", "C:", "\\" ... i.e. absolute
            raise Denied("path must be relative to the workspace")
        if any(part.startswith(".") for part in requested.parts):  # catches ".." and ".git"
            raise Denied("'..' and hidden paths are not allowed")
        full = (self.root / requested).resolve()  # follows symlinks
        if not full.is_relative_to(self.root):
            raise Denied("path leaves the workspace")
        if any(part.startswith(".") for part in full.relative_to(self.root).parts):
            raise Denied("path resolves to a hidden file")
        return full

    # Protected-file check on the RESOLVED path, so a symlink to validation.py
    # is caught too. casefold() ignores case: on Windows "Orders/Validation.py"
    # is the same file.
    def resolve_writable(self, path):
        full = self.resolve(path)
        relative = full.relative_to(self.root).as_posix()
        if relative.casefold() in {p.casefold() for p in PROTECTED_FILES}:
            raise Denied(f"{relative} is a protected file")
        return full

    # ---- file tools ----

    # Walks the tree without following symlinked folders, skipping hidden
    # folders and __pycache__. `dirs[:] = ...` modifies the list os.walk will
    # descend into (in-place assignment is how you prune it).
    def walk_files(self):
        """Yield workspace-relative paths, skipping hidden dirs and not following links."""
        for folder, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
            for name in sorted(files):
                if not name.startswith("."):
                    yield (Path(folder) / name).relative_to(self.root).as_posix()

    def list_files(self):
        files = []
        for path in self.walk_files():
            if len(files) == MAX_FILES:
                files.append(f"... (stopped at {MAX_FILES} files)")
                break
            files.append(path)
        return files

    # Reads at most MAX_TEXT + 1 characters: the extra one tells us the file
    # was longer. The "truncated" flag keeps the model from believing it saw
    # everything.
    def read_file(self, path):
        full = self.resolve(path)
        if not full.is_file():
            raise ToolError(f"not a file: {path}")
        with open(full, encoding="utf-8") as file:
            content = file.read(MAX_TEXT + 1)  # +1 tells us whether there was more
        truncated = len(content) > MAX_TEXT
        return {"path": path, "content": content[:MAX_TEXT], "truncated": truncated}

    # Literal (not regex) search, line by line. Caps: 200 files, 50 matches.
    # Files that fail UTF-8 decoding are treated as binary and skipped.
    def search_files(self, query):
        if not query:
            raise ToolError("query must not be empty")
        matches = []
        for count, path in enumerate(self.walk_files()):
            if count == MAX_FILES or len(matches) == MAX_MATCHES:
                break
            full = self.root / path
            if full.is_symlink() or full.stat().st_size > 1_000_000:
                continue
            try:
                text = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue  # binary file
            for number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append({"path": path, "line": number, "excerpt": line.strip()[:200]})
                    if len(matches) == MAX_MATCHES:
                        break
        return matches

    # Mode "x" = create, fail if the file exists. The OS does that check
    # atomically; an `if exists(): ... else: write()` could race.
    # newline="" writes exactly the "\n"s the model sent (no Windows \r\n).
    def write_file(self, path, content):
        full = self.resolve_writable(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        try:
            # "x" = create only; fails atomically if the file exists
            with open(full, "x", encoding="utf-8", newline="") as file:
                file.write(content)
        except FileExistsError:
            raise ToolError(f"{path} already exists; use edit_file") from None
        return f"created {path}"

    # `old` must occur exactly once: forces the model to quote a unique piece
    # of code, so it can't edit the wrong spot by accident. The error tells it
    # to re-read the file, which is the usual fix. Size is checked before AND
    # after the edit.
    def edit_file(self, path, old, new):
        full = self.resolve_writable(path)
        if not full.is_file():
            raise ToolError(f"not a file: {path}")
        if full.stat().st_size > MAX_TEXT:
            raise ToolError(f"{path} is larger than {MAX_TEXT} bytes")
        if not old:
            raise ToolError("old must not be empty")
        text = full.read_text(encoding="utf-8")
        count = text.count(old)
        if count != 1:
            raise ToolError(
                f"old text occurs {count} times; it must occur exactly once. Re-read the file."
            )
        updated = text.replace(old, new, 1)
        if len(updated.encode("utf-8")) > MAX_TEXT:
            raise ToolError(f"edited file would exceed {MAX_TEXT} bytes")
        full.write_text(updated, encoding="utf-8", newline="")
        return f"edited {path}"

    # ---- internet ----

    # URL rules are checked first, in BOTH modes. Offline returns the fixture,
    # clearly labelled; it never pretends to be a live response.
    # Live: no redirects, only text/html or text/plain, 10 s timeout, and at
    # most MAX_TEXT + 1 bytes read. The Decimal page is mostly navigation
    # HTML, so "truncated": true is expected there.
    def fetch_url(self, url):
        check_docs_url(url)  # same rules online and offline
        if self.offline:
            content = self.offline.read_text(encoding="utf-8")
            return {"url": url, "source": f"offline fixture ({self.offline.name})",
                    "content": content[:MAX_TEXT], "truncated": len(content) > MAX_TEXT}

        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(url, timeout=FETCH_TIMEOUT) as response:
                kind = response.headers.get_content_type()
                if kind not in ("text/html", "text/plain"):
                    raise ToolError(f"refusing content type {kind}")
                body = response.read(MAX_TEXT + 1)
        except urllib.error.HTTPError as exc:  # includes refused redirects
            raise ToolError(f"HTTP {exc.code} for {url}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ToolError(f"network error: {exc}") from None
        return {"url": url, "source": "live docs.python.org",
                "content": body[:MAX_TEXT].decode("utf-8", errors="replace"),
                "truncated": len(body) > MAX_TEXT}

    # ---- bash ----

    # `is not True`: only a real True approves; a buggy approver returning
    # "no" or None denies. The prompt itself lives in the CLI (it passes in
    # `approve`), which keeps this testable and means the model can never
    # answer it.
    # NOTE: approved bash is NOT a sandbox. It can read/write anything the user
    # can (e.g. `cat ../../x`), bypassing resolve() entirely. The human
    # approval is the only guard there.
    def bash(self, command):
        cwd = str(self.root)
        if self.approve(command, cwd) is not True:  # only an explicit True approves
            raise Denied("the user did not approve this command")
        return run_command(command, cwd)


# Whitelists each URL part. Comparing the PARSED hostname defeats tricks like
# "docs.python.org.evil.invalid" or "docs.python.org@evil.com".
def check_docs_url(url):
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port  # raises ValueError on garbage like ":abc"
    except ValueError:
        raise Denied("malformed URL") from None
    if parts.scheme != "https" or parts.hostname != DOCS_HOST:
        raise Denied(f"only https://{DOCS_HOST} is allowed")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise Denied("no credentials, query or fragment allowed")
    if port not in (None, 443):
        raise Denied("only the default HTTPS port is allowed")


# The handout's bash rules:
#   no startup files      -> bash --noprofile --norc -c command
#   target as cwd         -> cwd=root
#   stdin closed          -> DEVNULL (a command waiting for input can't hang)
#   stdout+stderr merged  -> stderr=STDOUT
#   minimal environment   -> only BASH_ENV_KEYS, so API keys don't leak
#   20 s timeout, 12,000-byte cap DURING the run, kill the process group
#
# Why a reader thread: capture_output=True would buffer ALL output in memory
# before we could cut it off (`yes` would fill RAM). The thread collects output
# in 4 KB chunks while the main thread waits on the timeout; whichever limit
# hits first triggers the kill.
def run_command(command, cwd):
    """Run bash with a timeout and an output cap; kill the whole process tree on either."""
    env = {key: os.environ[key] for key in BASH_ENV_KEYS if key in os.environ}
    if os.name == "nt":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}  # own process group -> killpg works
    process = subprocess.Popen(
        [BASH, "--noprofile", "--norc", "-c", command],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **group,
    )

    output = bytearray()

    def read_output():  # runs in a thread so we can enforce the timeout meanwhile
        while chunk := process.stdout.read1(4096):
            output.extend(chunk)
            if len(output) > MAX_TEXT:
                kill_tree(process)
                return

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=BASH_TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(process)
    except KeyboardInterrupt:  # Ctrl+C: kill, then let the loop report "cancelled"
        kill_tree(process)
        raise
    reader.join(timeout=5)
    process.wait(timeout=5)

    # A non-zero exit code is still status "ok": the command ran, and e.g.
    # failing tests are useful information for the model.
    text = output[:MAX_TEXT].decode("utf-8", errors="replace")
    if timed_out:
        raise ToolError(f"command timed out after {BASH_TIMEOUT}s. Output so far:\n{text}")
    return {"exit_code": process.returncode, "output": text, "truncated": len(output) > MAX_TEXT}


# `bash -c "python -m unittest"` starts bash which starts python; killing only
# bash would leave python running. So kill the whole tree:
# - Linux/macOS: the process has its own group (start_new_session) -> killpg.
# - Windows has no killpg; `taskkill /T` kills the process and its children.
def kill_tree(process):
    try:
        if os.name == "nt":
            taskkill = ["taskkill", "/T", "/F", "/PID", str(process.pid)]
            subprocess.run(taskkill, capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass  # already gone
