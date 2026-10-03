"""Stage 1 coding harness.

How the parts fit together (arrows = "uses"):

    cli.ConsoleUI -> controller.AgentController -> model (OllamaModel / ScriptedModel)
                                |
                                +-> tools.Toolbox -> tools.RepositoryTools -> tools.PathGuard
                                          |
                                          +-> execution.DockerSandbox   (run_check)

    cli -> verification.Verification -> execution.DockerSandbox + workspace.Workspace (diff)
"""

# Leftover placeholder from the project skeleton (kept so tests/test_core.py
# still passes). Delete core.py, tests/test_core.py and this line together.
from harness.core import echo

__all__ = ["echo"]
