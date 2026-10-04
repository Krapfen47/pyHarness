"""Allow `python3 -m student_agent` to run the CLI."""

from .cli import main

# SystemExit passes main()'s return value to the shell as the exit code
# (0 = final answer, 1 = no final answer, 130 = Ctrl+C).
raise SystemExit(main())
