# pyHarness

Course work for building agentic harnesses in Python.

## Deliverables

- **Semester project, Stage 1 (coding harness with CLI and web GUI):**
  [semProject/README.md](semProject/README.md). How to run it, architecture
  diagrams, tests, and real-model results.
- **Week 1 lab (coding agent with Ollama):**
  [lab/ollama-lab/my-agent/README.md](lab/ollama-lab/my-agent/README.md). The
  agent, the repair and prompt-injection runs, limitations. The repaired
  `target-service` has its own git repository, so it isn't in this one; it was
  submitted as a ZIP.

No secrets are needed for either: the models run locally in Ollama.

## Layout

```
lab/            one-off lab exercises (plain scripts)
semProject/     the semester project
  main.py       entry point
  harness/      the actual package (import as `harness`)
  tests/        pytest tests
pyproject.toml  deps + tool config (like package.json)
uv.lock         exact resolved versions (like package-lock.json), commit it
.venv/          the virtual environment (like node_modules), never commit it
```

## Commands

Everything goes through [uv](https://docs.astral.sh/uv/). `uv run` automatically uses `.venv`, so you never need to "activate" anything.

| Task | Command | npm equivalent |
|---|---|---|
| Install everything from lockfile | `uv sync` | `npm ci` |
| Add a dependency | `uv add httpx` | `npm i httpx` |
| Add a dev dependency | `uv add --dev mypy` | `npm i -D mypy` |
| Remove a dependency | `uv remove httpx` | `npm rm httpx` |
| Run a script | `uv run lab/hello.py` | `node lab/hello.js` |
| Run the project | `uv run semProject/main.py run --task semProject/tasks/cosmic-batchref --model qwen2.5-coder:14b` | |
| Start the GUI | `uv run semProject/main.py gui` | |
| Run tests | `uv run pytest` | `npm test` |
| Lint / autofix | `uv run ruff check . --fix` | `eslint --fix` |
| Format | `uv run ruff format .` | `prettier -w` |
| REPL | `uv run python` | `node` |

Settings (optional): copy `.env.example` to `.env`. `semProject/main.py` loads it with `python-dotenv`.

Editor: point VS Code / PyCharm at `.venv\Scripts\python.exe` as the interpreter.

See [CHEATSHEET.md](CHEATSHEET.md) for syntax.
