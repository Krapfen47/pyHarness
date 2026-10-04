"""The Ollama client's streaming, tested against a tiny fake Ollama server.

No real Ollama needed: a few lines of standard-library HTTP server play its
part and send the same kind of NDJSON stream (one JSON object per line).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness.model.ollama import OllamaModel


def chunk(content: str = "", done: bool = False, thinking: str = "", **extra) -> bytes:
    message = {"role": "assistant", "content": content}
    if thinking:
        message["thinking"] = thinking
    return (json.dumps({"message": message, "done": done, **extra}) + "\n").encode()


DONE = chunk(done=True, done_reason="stop", prompt_eval_count=120, eval_count=8,
             eval_duration=400_000_000, prompt_eval_duration=100_000_000,
             load_duration=0, total_duration=600_000_000)


class FakeOllama:
    """Runs a fake server in a background thread. `script` decides what it sends."""

    def __init__(self, script):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                outer.requests.append(json.loads(self.rfile.read(length)))
                script(self)

            def log_message(self, *args):  # keep the test output quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # port 0 = any free port
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/chat"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def stream(*lines: bytes, pause: float = 0.0):
    """A script that sends the given lines, one by one, then closes."""
    def script(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "application/x-ndjson")
        handler.end_headers()
        for line in lines:
            handler.wfile.write(line)
            handler.wfile.flush()
            time.sleep(pause)
    return script


@pytest.fixture
def fake():
    servers = []

    def start(script):
        server = FakeOllama(script)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def test_streamed_pieces_are_joined_and_reported(fake):
    server = fake(stream(chunk('{"final": '), chunk('"done"}'), DONE))
    pieces = []
    model = OllamaModel("test-model", endpoint=server.url, timeout=5)

    reply = model.request_action([{"role": "user", "content": "hi"}],
                                 on_token=lambda kind, text: pieces.append((kind, text)))

    assert reply == '{"final": "done"}'
    assert pieces == [("content", '{"final": '), ("content", '"done"}')]
    assert server.requests[0]["stream"] is True
    assert server.requests[0]["format"] == "json"
    stats = model.last_stats
    assert stats["prompt_tokens"] == 120 and stats["output_tokens"] == 8
    assert stats["tokens_per_s"] == 20.0  # 8 tokens in 0.4 s


def test_thinking_text_is_passed_on_separately(fake):
    server = fake(stream(chunk(thinking="Let me look at handlers.py"),
                         chunk('{"final": "x"}'), DONE))
    pieces = []
    reply = OllamaModel("m", endpoint=server.url, timeout=5).request_action(
        [], on_token=lambda kind, text: pieces.append(kind))
    assert reply == '{"final": "x"}'  # thinking is NOT part of the reply
    assert pieces == ["thinking", "content"]


def test_http_error_gives_a_clear_message(fake):
    def not_found(handler):
        handler.send_response(404)
        handler.end_headers()
        handler.wfile.write(b'{"error": "model \'nope\' not found"}')

    server = fake(not_found)
    with pytest.raises(RuntimeError, match="HTTP 404.*not found"):
        OllamaModel("nope", endpoint=server.url, timeout=5).request_action([])


def test_error_in_the_middle_of_the_stream_is_raised(fake):
    server = fake(stream(chunk('{"fi'), b'{"error": "out of memory"}\n'))
    with pytest.raises(RuntimeError, match="out of memory"):
        OllamaModel("m", endpoint=server.url, timeout=5).request_action([])


def test_unreachable_server_gives_a_clear_message():
    model = OllamaModel("m", endpoint="http://127.0.0.1:9/api/chat", timeout=2)  # port 9: nobody
    with pytest.raises(RuntimeError, match="cannot reach Ollama"):
        model.request_action([])


def test_cancel_from_another_thread_ends_a_hanging_reply_at_once(fake):
    # The server sends one piece and then goes silent for a long time, like a
    # big model thinking on the CPU. cancel() must not wait for it.
    server = fake(stream(chunk('{"tool"'), chunk(": 1}"), DONE, pause=30))
    model = OllamaModel("m", endpoint=server.url, timeout=60)
    first_piece = threading.Event()
    threading.Thread(target=lambda: (first_piece.wait(5), model.cancel()), daemon=True).start()

    started = time.monotonic()
    with pytest.raises(RuntimeError):
        model.request_action([], on_token=lambda kind, text: first_piece.set())
    assert time.monotonic() - started < 10  # far less than the 30 s pause
