"""The GUI's web server (FastAPI): a small REST API, a live event stream, the React app.

    GET  /api/health              is Ollama reachable (+ which models)? is Docker running?
    GET  /api/tasks               the task folders in semProject/tasks/
    POST /api/runs                start a run          -> {"run_id": ...}
    POST /api/runs/{id}/stop      the Stop button
    GET  /api/runs                History: every past run, newest first
    GET  /api/runs/{id}           all events of one run (to replay it)
    GET  /api/live                Server-Sent Events: the live run's events as they happen
    GET  /                        the built React app (semProject/gui/dist)

SSE ("Server-Sent Events") is the simplest way for a server to PUSH data to
a browser: one long HTTP response that never ends, made of blocks like

    data: {"seq": 12, "type": "request", ...}

each followed by an empty line. The browser's built-in `EventSource` reads it
and even reconnects by itself if the connection drops.

Security: this server can start runs, so it must only be reachable from
this computer. It listens on 127.0.0.1 only, and it rejects requests whose
Host / Origin header names another site. That stops a web page on the
internet from talking to it through your browser ("DNS rebinding" and
"cross-site request" attacks). No endpoint accepts a file path or a command:
the browser sends a task NAME, and the server looks the folder up itself.
"""

import asyncio
import json
import re
import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from harness.execution.sandbox import DockerSandbox
from harness.gui.history import list_runs, load_run
from harness.gui.manager import OVERFLOW, RunBusy, RunManager, Subscriber
from harness.limits import Limits
from harness.model.ollama import DEFAULT_MODEL, list_models
from harness.runner import PROJECT_DIR, RUNS_DIR, TASKS_DIR, RunRequest
from harness.task import TaskError, load_task

DIST_DIR = PROJECT_DIR / "gui" / "dist"  # output of `npm run build`
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
VITE_DEV_PORT = 5173  # the React dev server (`npm run dev`) forwards /api here
MODEL_NAME = re.compile(r"^[\w.:/-]{1,100}$")  # e.g. "qwen2.5-coder:14b"


class StartRun(BaseModel):
    """The body of POST /api/runs. Pydantic checks types and ranges for us."""

    task: str  # a task folder NAME from GET /api/tasks, never a path
    mode: str = Field("run", pattern="^(run|baseline)$")
    model: str | None = None  # Ollama model; None = the default
    scripted: bool = False  # use the task's reference_script.json instead of a model
    pace: float = Field(0.15, ge=0, le=2)  # scripted: seconds between streamed pieces
    reference_patch: bool = False  # baseline: apply the task's reference_fix.patch first
    max_actions: int = Field(Limits.max_actions, ge=1, le=100)


def find_tasks(tasks_dir: Path) -> dict[str, Path]:
    """Task name (folder name) -> folder, for every folder with a task.toml."""
    return {path.parent.name: path.parent for path in sorted(tasks_dir.glob("*/task.toml"))}


def describe_task(name: str, folder: Path) -> dict:
    try:
        task = load_task(folder)
    except TaskError as exc:
        return {"id": name, "error": str(exc)}
    return {
        "id": name, "name": task.name, "repo_url": task.repo_url, "commit": task.commit,
        "request": task.request, "writable": list(task.writable),
        "agent_checks": task.agent_checks, "verification": task.verification,
        "has_script": (folder / "reference_script.json").is_file(),
        "has_patch": (folder / "reference_fix.patch").is_file(),
    }


def docker_status() -> dict:
    # A throw-away sandbox object, only to reuse its "is Docker usable?" check.
    problem = DockerSandbox(PROJECT_DIR, {}, "health-check", Limits()).problem()
    return {"ok": problem is None, "detail": problem}


def ollama_status() -> dict:
    try:
        return {"ok": True, "models": list_models(), "default": DEFAULT_MODEL}
    except RuntimeError as exc:
        return {"ok": False, "models": [], "default": DEFAULT_MODEL, "detail": str(exc)}


def create_app(manager: RunManager, port: int, tasks_dir: Path = TASKS_DIR,
               dist_dir: Path = DIST_DIR) -> FastAPI:
    allowed_origins = {f"http://{host}:{p}" for host in LOCAL_HOSTS for p in (port, VITE_DEV_PORT)}

    # "lifespan": code that runs when the server starts (before `yield`) and
    # when it stops (after). On Ctrl+C we stop a running run, so no Docker
    # container is left behind.
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await asyncio.to_thread(manager.shutdown)

    app = FastAPI(title="pyHarness GUI", lifespan=lifespan)

    # Runs before every request (a "middleware").
    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = urlsplit(f"//{request.headers.get('host', '')}").hostname
        if host not in LOCAL_HOSTS:
            return JSONResponse({"detail": "only local requests are allowed"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method != "GET" and origin is not None and origin not in allowed_origins:
            return JSONResponse({"detail": f"origin {origin} is not allowed"}, status_code=403)
        return await call_next(request)

    # Plain `def` (not `async def`) endpoints run in a thread pool, so slow
    # work like asking Docker or Ollama doesn't freeze the live stream.
    @app.get("/api/health")
    def health():
        return {"ollama": ollama_status(), "docker": docker_status(),
                "active_run": manager.active_run()}

    @app.get("/api/tasks")
    def tasks():
        return [describe_task(name, folder) for name, folder in find_tasks(tasks_dir).items()]

    @app.post("/api/runs")
    def start_run(body: StartRun):
        folder = find_tasks(tasks_dir).get(body.task)
        if folder is None:
            raise HTTPException(404, f"no task called {body.task!r}")
        if body.model is not None and not MODEL_NAME.match(body.model):
            raise HTTPException(422, "that doesn't look like a model name")
        script = folder / "reference_script.json"
        patch = folder / "reference_fix.patch"
        if body.mode == "run" and body.scripted and not script.is_file():
            raise HTTPException(422, "this task has no reference_script.json")
        if body.mode == "baseline" and body.reference_patch and not patch.is_file():
            raise HTTPException(422, "this task has no reference_fix.patch")
        request = RunRequest(
            task=str(folder), mode=body.mode, model=body.model,
            script=str(script) if body.mode == "run" and body.scripted else None,
            pace=body.pace,
            patch=str(patch) if body.mode == "baseline" and body.reference_patch else None,
            max_actions=body.max_actions,
        )
        try:
            return {"run_id": manager.start(request)}
        except RunBusy as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/runs/{run_id}/stop")
    def stop_run(run_id: str):
        if not manager.stop(run_id):
            raise HTTPException(404, "that run is not running")
        return {"stopping": run_id}

    @app.get("/api/runs")
    def runs():
        return list_runs(manager.runs_dir)

    @app.get("/api/runs/{run_id}")
    def run_events(run_id: str):
        events = load_run(manager.runs_dir, run_id)
        if events is None:
            raise HTTPException(404, f"no run called {run_id!r}")
        return {"run_id": run_id, "events": events}

    @app.get("/api/live")
    async def live(request: Request):
        queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        subscriber = Subscriber(asyncio.get_running_loop(), queue)
        backlog = manager.subscribe(subscriber)

        def sse(event: dict) -> str:
            return f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"

        async def stream():
            try:
                yield ": connected\n\n"  # lines starting with ":" are comments
                for event in backlog:  # catch up: the current run so far
                    yield sse(event)
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=10)
                    except TimeoutError:
                        yield ": ping\n\n"  # keeps the connection from looking dead
                        continue
                    if event is OVERFLOW:
                        break  # the browser reconnects and starts fresh
                    yield sse(event)
            finally:
                manager.unsubscribe(subscriber)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    # The React app. Mounted last, so the /api routes above take priority.
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=dist_dir, html=True), name="app")
    else:
        @app.get("/")
        def not_built():
            return HTMLResponse(
                "<h1>The GUI is not built yet</h1><p>Run once:</p>"
                "<pre>cd semProject/gui\nnpm install\nnpm run build</pre>"
                "<p>then reload this page. (The API is already running.)</p>")

    return app


def serve(port: int = 8765, open_browser: bool = True) -> int:
    """Start the server and block until Ctrl+C."""
    import uvicorn

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    app = create_app(RunManager(RUNS_DIR), port)
    url = f"http://127.0.0.1:{port}"
    print(f"harness GUI on {url}  (Ctrl+C to quit)", flush=True)
    if open_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    # 127.0.0.1, never 0.0.0.0: unreachable from other computers.
    # timeout_graceful_shutdown: open live streams never end by themselves,
    # so on Ctrl+C give them 3 seconds and then close them.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning",
                timeout_graceful_shutdown=3)
    return 0
