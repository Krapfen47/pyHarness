"""Talk to a local Ollama server (carried over from the lab's model.py).

Only standard-library HTTP (http.client) is used: one POST request per turn
doesn't need an extra dependency.

The reply is STREAMED: Ollama sends it as many small JSON lines while the
model is still writing ("NDJSON", newline-delimited JSON), e.g.

    {"message": {"role": "assistant", "content": "{\\"to"}, "done": false}
    {"message": {"role": "assistant", "content": "ol\\": "}, "done": false}
    ...
    {"message": {...}, "done": true, "eval_count": 41, "eval_duration": 812345678, ...}

We glue the pieces back together, so the controller still gets one string.
Streaming changes nothing about WHAT the model answers; it only lets a UI
show the answer while it is being written, and lets the Stop button cut a
reply off halfway (see cancel()).
"""

import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from harness.model.base import Message, OnToken

# Safety cap on how much of Ollama's HTTP response we read. A normal reply is a
# few KB; anything near 1 MB means something is wrong, so we stop instead of
# filling memory.
MAX_RESPONSE_BYTES = 1_000_000

DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_URL = "http://127.0.0.1:11434/api/chat"


class OllamaModel:
    """Real model client. Fits the ModelClient protocol (see base.py)."""

    # context_window: how many tokens (prompt + history + reply) Ollama keeps.
    # Ollama's default is small (a few thousand tokens). Past it, Ollama
    # SILENTLY drops the oldest messages, including the system prompt with the
    # rules. qwen2.5-coder supports 32k; 16k balances memory use and headroom.
    #
    # timeout: seconds to wait for ONE reply. A model too big for the graphics
    # card partly runs on the CPU and can need minutes per reply, so this is
    # configurable (OLLAMA_TIMEOUT in .env) instead of fixed.
    def __init__(
        self,
        model_name: str | None = None,
        endpoint: str | None = None,
        timeout: float | None = None,
        context_window: int = 16_384,
    ):
        # Settings come from arguments, then environment (.env), then defaults.
        # Nothing about the model is hard-coded inside the loop.
        self.model_name = model_name or os.environ.get("OLLAMA_MODEL") or DEFAULT_MODEL
        self.endpoint = endpoint or os.environ.get("OLLAMA_URL") or DEFAULT_URL
        self.timeout = timeout or float(os.environ.get("OLLAMA_TIMEOUT") or 300)
        self.context_window = context_window
        # OLLAMA_THINK=true asks a "thinking" model (qwen3, deepseek-r1, ...)
        # to reason in a separate channel before answering. Unset = we don't
        # send the option at all, so models without thinking are unaffected.
        think = os.environ.get("OLLAMA_THINK", "").strip().lower()
        self.think = None if not think else think in ("1", "true", "yes")
        # Numbers about the last reply (token counts, timings), for the UI.
        self.last_stats: dict | None = None
        # The network socket while a reply is streaming; cancel() needs it.
        self._socket: socket.socket | None = None

    def settings(self) -> dict:
        """What the run log records about this model's configuration."""
        return {"model": self.model_name, "endpoint": self.endpoint, "timeout": self.timeout,
                "context_window": self.context_window, "temperature": 0, "max_reply_tokens": 2048,
                "think": self.think}

    def request_action(self, messages: list[Message], on_token: OnToken | None = None) -> str:
        # - stream True: the reply arrives in pieces (see the module docstring).
        # - format "json": Ollama forces the output to be valid JSON. It does
        #   NOT guarantee our shape ({"tool":..} / {"final":..}); the
        #   controller still checks that.
        # - temperature 0: always pick the most likely token, so runs are
        #   (nearly) repeatable. Great for debugging and the demo video.
        # - num_predict: max tokens per reply (an output limit on the model).
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 2048, "num_ctx": self.context_window},
        }
        if self.think is not None:
            payload["think"] = self.think
        self.last_stats = None

        url = urllib.parse.urlsplit(self.endpoint)
        kind = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        # `timeout` here is per network read: if Ollama sends NOTHING for that
        # long, the read fails. The `deadline` below also limits the TOTAL time,
        # because a slow but steady stream would never trip a per-read timeout.
        connection = kind(url.hostname, url.port, timeout=self.timeout)
        # Any exception here ends the run as "model_error" in the controller
        # (or "cancelled", if the user pressed Stop), so the only job is to
        # make the message useful.
        try:
            connection.connect()
        except OSError as exc:
            raise RuntimeError(
                f"cannot reach Ollama at {self.endpoint} ({exc}). Is it running?"
            ) from None
        # Our own reference to the network socket, for cancel(). (http.client
        # may hand the socket over to the response object and forget it.)
        self._socket = connection.sock
        deadline = time.monotonic() + self.timeout
        parts: list[str] = []
        received = 0
        try:
            connection.request("POST", url.path or "/api/chat", body=json.dumps(payload),
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                detail = response.read(2000).decode("utf-8", errors="replace")
                raise RuntimeError(f"Ollama returned HTTP {response.status}: {detail}")
            while True:
                line = response.readline(MAX_RESPONSE_BYTES)
                if not line:
                    raise RuntimeError("Ollama closed the connection before the reply was done")
                received += len(line)
                if received > MAX_RESPONSE_BYTES:
                    raise RuntimeError("Ollama response exceeded the size limit")
                if time.monotonic() > deadline:
                    raise RuntimeError(f"the reply took longer than {self.timeout:.0f} s")
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise RuntimeError(f"Ollama error: {chunk['error']}")
                message = chunk.get("message") or {}
                if message.get("thinking") and on_token:
                    on_token("thinking", message["thinking"])
                if message.get("content"):
                    parts.append(message["content"])
                    if on_token:
                        on_token("content", message["content"])
                if chunk.get("done"):
                    self.last_stats = reply_stats(chunk)
                    break
        except TimeoutError:
            raise RuntimeError(f"no answer from Ollama for {self.timeout:.0f} s") from None
        except (OSError, http.client.HTTPException) as exc:
            raise RuntimeError(f"the connection to Ollama broke off ({exc})") from None
        finally:
            self._socket = None
            connection.close()
        return "".join(parts)

    def cancel(self) -> None:
        """Abort the reply that is streaming right now, from ANOTHER thread.

        The GUI runs the agent loop in a background thread. When the user
        presses Stop, that thread may be stuck waiting for Ollama (a big model
        on the CPU can think for a minute before the first word). Closing the
        socket underneath it wakes the waiting read up at once with an error,
        and Ollama notices the closed connection and stops generating.

        Two steps, because operating systems differ: shutdown() wakes a
        waiting read on Linux/macOS, but not on Windows. There, only really
        closing the OS handle does. A plain sock.close() would NOT do that,
        because the response object still holds a reference to the socket;
        detach() takes the raw handle away from Python so we can close it.
        (Both found by test_ollama_streaming.py on this Windows machine.)
        """
        sock = self._socket
        if sock is None:
            return  # no reply streaming: nothing to cancel
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed
        try:
            socket.close(sock.detach())
        except OSError:
            pass


def reply_stats(chunk: dict) -> dict:
    """The numbers from Ollama's last ("done") line, in friendlier units.

    Ollama measures time in nanoseconds (1 s = 1_000_000_000 ns).
    """
    def seconds(key: str) -> float:
        return round(chunk.get(key, 0) / 1e9, 2)

    output_s = seconds("eval_duration")
    output_tokens = chunk.get("eval_count", 0)
    return {
        "prompt_tokens": chunk.get("prompt_eval_count", 0),  # tokens the model had to read
        "output_tokens": output_tokens,  # tokens it wrote
        "load_s": seconds("load_duration"),  # loading the model into memory
        "prompt_s": seconds("prompt_eval_duration"),  # reading the prompt
        "output_s": output_s,  # writing the reply
        "total_s": seconds("total_duration"),
        "tokens_per_s": round(output_tokens / output_s, 1) if output_s else None,
        "done_reason": chunk.get("done_reason"),  # "stop" = finished, "length" = hit num_predict
    }


def list_models(endpoint: str | None = None, timeout: float = 3) -> list[str]:
    """Names of the models Ollama has pulled (GET /api/tags). Raises if Ollama is down."""
    endpoint = endpoint or os.environ.get("OLLAMA_URL") or DEFAULT_URL
    url = urllib.parse.urlsplit(endpoint)
    tags = urllib.parse.urlunsplit((url.scheme, url.netloc, "/api/tags", "", ""))
    try:
        with urllib.request.urlopen(tags, timeout=timeout) as response:
            data = json.loads(response.read(MAX_RESPONSE_BYTES))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise RuntimeError(f"cannot reach Ollama at {tags} ({exc})") from None
    return sorted(model["name"] for model in data.get("models", []))
