"""Talk to a local Ollama server (carried over from the lab's model.py).

Only standard-library HTTP (urllib) is used, as in the lab: one POST request
per turn doesn't need an extra dependency.
"""

import json
import os
import urllib.error
import urllib.request

from harness.model.base import Message

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

    def request_action(self, messages: list[Message]) -> str:
        # - stream False: one complete answer instead of token-by-token chunks.
        # - format "json": Ollama forces the output to be valid JSON. It does
        #   NOT guarantee our shape ({"tool":..} / {"final":..}); the
        #   controller still checks that.
        # - temperature 0: always pick the most likely token, so runs are
        #   (nearly) repeatable. Great for debugging and the demo video.
        # - num_predict: max tokens per reply (an output limit on the model).
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 2048, "num_ctx": self.context_window},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Any exception here ends the run as "model_error" in the controller,
        # so the only job is to make the message useful.
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama returned HTTP {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"cannot reach Ollama at {self.endpoint} ({exc.reason}). Is it running?"
            ) from None

        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ollama response exceeded the size limit")
        # Response: {"message": {"role": "assistant", "content": "<text>"}, ...}
        return json.loads(body)["message"]["content"]
