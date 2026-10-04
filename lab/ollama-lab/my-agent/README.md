# Week 1: Coding agent with Ollama

A small coding agent written in plain Python (standard library only). It talks to a
local Ollama model, uses tools to read and edit the order service in
`target-service`, and asks a human before it runs any bash command.

**Authors:** TODO name(s). If you worked in a pair, write who did what.

**AI assistance:** I used an AI coding assistant (Claude Code) to help write the
agent code. I read, tested and ran all of it myself, and the comments in the code
explain every part. TODO: adjust this to describe what you actually did.

## Setup

You need:

- Python 3.10 or newer. No `pip install` is needed.
- Ollama running locally on `http://127.0.0.1:11434`.
- Git and bash. On Windows the agent uses Git Bash
  (`C:\Program Files\Git\bin\bash.exe`). Set `AGENT_BASH` to use a different bash.

Download a model once:

```bash
ollama pull qwen2.5-coder:7b
```

## Choosing the model

The default is `qwen2.5-coder:7b`. To use a different model, pass `--model` or set
the `OLLAMA_MODEL` environment variable:

```bash
python -m student_agent --model qwen2.5-coder:3b ...
```

Use `3b` on a computer with little memory. Use `14b` if you have enough memory and
don't mind slower answers.

## How to run

Run the commands from the `my-agent` folder. The target is `../target-service`.

**Read-only run** (the agent can look at files but can't change anything):

```bash
python -m student_agent --root ../target-service --offline --task "Inspect the order service and docs/business-rules.md. Read orders/pricing.py and the acceptance tests. Find the cause of the incorrect totals. Use the Decimal documentation to check rounding behavior. Explain the needed repair without changing any files."
```

**Edit run** (the agent can edit files, and asks before each bash command):

```bash
python -m student_agent --root ../target-service --mode edit --offline --task "Repair orders/pricing.py according to docs/business-rules.md. Keep validation and acceptance tests unchanged. Read the files before editing. Add one useful regression test in tests/test_student.py. Request approval to run python -m unittest discover -s tests -v. Summarize what changed and what you verified."
```

All options:

| Option | Meaning |
|---|---|
| `--root` | The folder the agent works in (required) |
| `--task` | What the agent should do (required) |
| `--mode` | `read-only` (default) or `edit` |
| `--tools` | Comma-separated list of tools to turn on, e.g. `read_file,list_files`. Default: all |
| `--model` | Ollama model name (default: `OLLAMA_MODEL`, or `qwen2.5-coder:7b`) |
| `--offline [FILE]` | `fetch_url` returns a local file instead of the internet. Default file: `fixtures/decimal-offline.txt`. The result is labelled "offline fixture" |
| `--max-turns` | Maximum number of turns (default 15) |
| `--log` | Where to write the log. Default: `my-agent/runs/<time>.jsonl` (outside the target) |

The program prints every tool call and result while it runs. It also writes every
event to a JSONL log file, one JSON object per line.

## Permissions

The model only **suggests** actions. The runtime (`runtime.py`) decides whether an
action is allowed, and it checks this again on every call.

| Tool | Read-only | Edit |
|---|---|---|
| `list_files`, `read_file`, `search_files` | allowed | allowed |
| `fetch_url` (only `https://docs.python.org`) | allowed | allowed |
| `write_file` (only new files), `edit_file` | denied | allowed |
| `bash` | denied | allowed after a human types `yes` |

Other rules:

- **File boundary:** paths must stay inside the target folder. Absolute paths, `..`,
  hidden files (`.git`, `.venv`) and symlinks that point outside are denied.
- **Protected files** can be read but never changed: `orders/validation.py`,
  `tests/test_acceptance.py`, `docs/business-rules.md`.
- **Bash:** the program prints the command and its working folder and asks
  `Approve this command only? Type yes:`. Only the exact answer `yes` runs it.
  Commands run with a 20-second time limit and a 12,000-byte output limit, and
  without API keys in their environment.
- **Bash isn't a sandbox.** An approved command can do anything your user account
  can do, including changing protected files. Read every command before you approve it.
- **Internet:** only HTTPS pages on `docs.python.org`. No query string, no
  redirects, text or HTML only, 10-second time limit.

## How it works

| File | Job |
|---|---|
| `agent.py` | The loop. It asks the model for one JSON action, lets the runtime run it, and sends the result back as untrusted data. It stops on a final answer, after 15 turns, on a model error, or on Ctrl+C. |
| `runtime.py` | The tool registry and all security checks: which tools are allowed, file paths, protected files, bash approval, URL rules. |
| `model.py` | Sends the conversation to Ollama (`/api/chat`, JSON format, temperature 0) and returns the reply text. |
| `cli.py` | Reads the command-line options, asks for bash approval, prints progress and writes the log. |

## Tests

From `my-agent`:

```bash
python -m unittest discover -s tests -v
```

From the lab package folder (`ollama-lab`):

```bash
python checks/check_agent.py --implementation my-agent --module student_agent
```

14 of the 15 public checks pass on Windows. `test_symlink_escape` can't run on
Windows unless Developer Mode is on, because the test itself isn't allowed to
create a symlink. The code handles symlinks with `Path.resolve()`.

## Results

- **Read-only run** (`qwen2.5-coder:7b`): the agent listed the files and read the
  pricing code, the tests, the business rules and the Decimal documentation. After
  that it kept re-reading the same files and never gave a final answer. It stopped
  at the 15-turn limit. `git status` showed no changes in the target.
- **Edit run:** TODO
- **Prompt injection test:** TODO

## Known limitations

- The 7B model often repeats the same tool calls and runs out of turns. A
  smaller task (one rule at a time) works better.
- A final answer from the model is only a claim. Always check `git diff` and run
  the tests yourself.
- Prompt injection isn't solved. The system prompt asks the model to treat
  tool results as data, and the runtime blocks forbidden actions, but a human can
  still approve a harmful bash command.
- On Windows, timed-out commands are stopped with `taskkill /T` instead of
  process groups (`os.killpg` only exists on Linux and macOS).
