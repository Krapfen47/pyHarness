"""Model clients: the real one (Ollama) and a scripted one for tests."""

from harness.model.base import Message, ModelClient
from harness.model.ollama import OllamaModel
from harness.model.scripted import ScriptedModel, ScriptExhausted

__all__ = ["Message", "ModelClient", "OllamaModel", "ScriptedModel", "ScriptExhausted"]
