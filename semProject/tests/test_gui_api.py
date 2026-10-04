"""The GUI's web server: REST endpoints, the local-only rule, and the live event bridge.

FastAPI's TestClient calls the app directly (no real network). Runs use the
scripted model and a fake sandbox, so no Docker or Ollama is needed.
"""

import asyncio
import threading
import time

import pytest
from conftest import FakeSandbox
from fastapi.testclient import TestClient

import harness.gui.server as server
from harness.gui.manager import RunManager, Subscriber
from harness.runner import HarnessRun

LOCAL = "http://127.0.0.1:8765"


@pytest.fixture
def manager(tmp_path) -> RunManager:
    def harness(request, emit):
        return HarnessRun(request, emit, sandbox_factory=lambda *args: FakeSandbox())
    return RunManager(tmp_path / "runs", harness_factory=harness)


@pytest.fixture
def client(manager, task_dir, tmp_path, monkeypatch) -> TestClient:
    # The task fixture lives in <tmp>/task; the server scans <tmp> for tasks.
    monkeypatch.setenv("HARNESS_WORKDIR", str(tmp_path / "work"))
    monkeypatch.setattr(server, "docker_status", lambda: {"ok": False, "detail": "test"})
    monkeypatch.setattr(server, "ollama_status", lambda: {"ok": True, "models": ["m"]})
    app = server.create_app(manager, 8765, tasks_dir=task_dir.parent, dist_dir=tmp_path / "x")
    return TestClient(app, base_url=LOCAL)


def wait_until_done(manager: RunManager) -> None:
    manager.current.thread.join(timeout=30)
    assert not manager.current.running


def test_health_and_tasks(client):
    health = client.get("/api/health").json()
    assert health["ollama"]["models"] == ["m"] and health["active_run"] is None
    tasks = client.get("/api/tasks").json()
    assert [t["id"] for t in tasks] == ["task"]
    assert tasks[0]["name"] == "calc-bug" and tasks[0]["has_script"] is True


def test_scripted_run_ends_up_in_history_with_all_events(client, manager):
    response = client.post("/api/runs", json={"task": "task", "scripted": True, "pace": 0})
    run_id = response.json()["run_id"]
    wait_until_done(manager)

    history = client.get("/api/runs").json()
    assert history[0]["run_id"] == run_id
    assert history[0]["status"] == "verified" and history[0]["task"] == "calc-bug"
    events = client.get(f"/api/runs/{run_id}").json()["events"]
    assert events[0]["type"] == "launch" and events[-1]["type"] == "finished"
    assert [e["seq"] for e in events] == sorted(e["seq"] for e in events)
    # Streamed pieces are live-only: not in the log.
    assert not any(e["type"] == "model_token" for e in events)


def test_only_one_run_at_a_time_and_stop_works(client, manager):
    slow = {"task": "task", "scripted": True, "pace": 0.2}
    run_id = client.post("/api/runs", json=slow).json()["run_id"]
    assert client.post("/api/runs", json=slow).status_code == 409  # busy
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 200
    wait_until_done(manager)
    assert manager.current.events[-1]["status"] == "cancelled"
    assert client.post(f"/api/runs/{run_id}/stop").status_code == 404  # not running anymore


def test_requests_cannot_name_paths(client):
    assert client.post("/api/runs", json={"task": "../task"}).status_code == 404
    assert client.get("/api/runs/..%2F..%2Fsecret").status_code == 404
    assert client.post("/api/runs", json={"task": "task", "model": "x; rm -rf /"}).status_code \
        == 422
    assert client.post("/api/runs", json={"task": "task", "max_actions": 10_000}).status_code \
        == 422


def test_other_sites_are_refused(client):
    # A page on another site, or a DNS-rebinding trick, can't use the API.
    assert client.get("/api/tasks", headers={"host": "evil.example"}).status_code == 403
    response = client.post("/api/runs", json={"task": "task"},
                           headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_live_events_reach_a_subscriber_on_another_thread(manager, task_dir, tmp_path,
                                                           monkeypatch):
    """The bridge from the run thread to the web server's asyncio loop."""
    from harness.runner import RunRequest

    monkeypatch.setenv("HARNESS_WORKDIR", str(tmp_path / "work"))

    async def collect() -> list[dict]:
        queue: asyncio.Queue = asyncio.Queue()
        manager.subscribe(Subscriber(asyncio.get_running_loop(), queue))
        request = RunRequest(task=str(task_dir), script=str(task_dir / "reference_script.json"))
        threading.Thread(target=manager.start, args=(request,)).start()
        received = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            event = await asyncio.wait_for(queue.get(), timeout=30)
            received.append(event)
            if event["type"] == "finished":
                break
        return received

    events = asyncio.run(collect())
    assert events[-1]["status"] == "verified"
    assert any(e["type"] == "model_token" for e in events)  # live view gets the pieces
    assert len({e["run_id"] for e in events}) == 1
