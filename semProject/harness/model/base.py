"""What the controller needs from "a model": one method, nothing more.

`Protocol` is Python's version of an interface (Java/C# `interface`, a TS
`interface`), with one twist: a class does not have to say "implements
ModelClient". If it has a matching `request_action` method, it fits. That is
called structural typing (or "duck typing": if it quacks like a duck...).

Why such a tiny interface? Because it is the seam that makes the whole loop
testable. The real Ollama client and the ScriptedModel used in tests both fit
it, so the controller cannot tell them apart. The handout requires exactly
this: "Core tests must run without a live account or API key."
"""

from typing import Protocol

# One chat message, as every chat API uses it: {"role": "user", "content": "..."}.
Message = dict[str, str]


class ModelClient(Protocol):
    def request_action(self, messages: list[Message]) -> str:
        """Send the whole conversation, get back the model's next reply as text.

        The reply is UNTRUSTED text. It is supposed to be one JSON action, but
        the controller must check that itself (see controller.validate_action).
        """
        ...
