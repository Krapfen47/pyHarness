"""The web GUI: a local web server (this package) plus a React app (semProject/gui/).

    uv run semProject/main.py gui        then open http://127.0.0.1:8765

How the pieces fit together:

    browser (React)  --- REST: start / stop a run, list tasks and history --->  server.py
                     <-- SSE: every event of the live run, as it happens ----   (FastAPI)
                                                                                    |
                                                    manager.py runs HarnessRun in a background
                                                    thread and fans its events out to every
                                                    open browser tab (and to the JSONL log)

The GUI adds NO new way to touch the repository: it starts the same
HarnessRun as the CLI and only displays its events.
"""
