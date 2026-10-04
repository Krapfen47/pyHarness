"""Local Ollama chat adapter.

The agent loop only needs "a function that takes messages and returns a string".
This class is the real version of that function; the tests use fakes instead.
That is why the loop can be tested without Ollama running.
"""

import json
import urllib.error
import urllib.request

# Safety cap on how much of Ollama's HTTP response we read. A normal reply is a
# few KB; anything near 1 MB means something is wrong, so we stop instead of
# filling memory ("bounded response" in the handout).
MAX_RESPONSE_BYTES = 1_000_000


class OllamaModel:
    """Callable adapter for Ollama's local chat endpoint.

    `__call__` makes an instance callable like a function:
        model = OllamaModel("qwen2.5-coder:7b")
        reply = model(messages)      # runs __call__
    So run_agent can treat this object and a test's fake function the same way.
    """

    # context_window: how many tokens (prompt + history + reply) Ollama keeps.
    # Ollama's default is small (a few thousand tokens). When the conversation
    # grows past it, Ollama SILENTLY drops the oldest messages, which includes the
    # system prompt with our rules and the protocol. One read_file result can be
    # ~3000 tokens, so the default fills up after a few turns. qwen2.5-coder
    # supports 32k; 16k is a compromise between memory use and headroom.
    def __init__(
        self,
        model_name,
        endpoint="http://127.0.0.1:11434/api/chat",
        timeout=90,
        context_window=16_384,
    ):
        self.model_name = model_name
        self.endpoint = endpoint
        self.timeout = timeout
        self.context_window = context_window

    def __call__(self, messages):
        """Return the model's message content as a JSON string."""

        # The request body, as the handout specifies:
        # - stream False: one complete answer instead of token-by-token chunks.
        # - format "json": Ollama constrains generation to valid JSON. It does not
        #   guarantee OUR shape ({"tool":..} / {"final":..}); parse_action checks that.
        # - temperature 0: always pick the most likely token -> repeatable runs,
        #   which makes debugging and the video demo much easier.
        # - num_predict: max tokens in the reply (the handout's output limit).
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": 2048,
                "num_ctx": self.context_window,
            },
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Any exception raised here propagates to run_agent, which ends the run
        # with termination "model_error" and the message below as the reason.
        # So the job here is only to make that message useful.
        try:
            # `with` closes the connection even if reading fails.
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # Ollama answers errors with JSON like {"error": "model 'x' not found"}.
            detail = exc.read(2000).decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama returned HTTP {exc.code}: {detail}") from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"cannot reach Ollama at {self.endpoint} ({exc.reason}). Is it running?"
            ) from None

        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ollama response exceeded the size limit")

        # Ollama's response looks like:
        #   {"model": ..., "message": {"role": "assistant", "content": "<text>"}, ...}
        # We return only the text. Whether that text is a valid action is the
        # loop's problem (parse_action), not the adapter's.
        data = json.loads(body)
        return data["message"]["content"]
