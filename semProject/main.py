"""Entry point for the semester project, so it runs from the repository root:

    uv run semProject/main.py run --task semProject/tasks/cosmic-batchref

Python puts the folder of the started script (semProject/) on its import
path, which is why `import harness` works here without installing anything.
"""

import sys

from harness.cli import main

if __name__ == "__main__":
    sys.exit(main())
