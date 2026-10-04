"""Smoke test for the setup: uv run lab/hello.py"""

import sys


def main() -> None:
    print(f"Hello from Python {sys.version.split()[0]} at {sys.executable}")


if __name__ == "__main__":
    main()
