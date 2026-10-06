"""Build the week 1 lab submission ZIP.

The handout asks for "your agent, the repaired service, your tests, and a short
README", without model downloads, virtual environments, credentials or
temporary files. This script packs exactly that, so nothing is forgotten and
nothing private slips in. Rerun it after every change (e.g. to the README):

    python lab/make_submission_zip.py

Paths inside the ZIP start with ollama-lab/, just like on disk, so every
command in my-agent/README.md works unchanged after unzipping.

What goes in:
  my-agent/        the agent, its tests, README, attack_demo.py
  target-service/  the repaired service INCLUDING its .git folder, so a grader
                   can run `git diff -- orders/pricing.py` and see the repair
                   against the "Record lab baseline" commit
  checks/          the course's public checks (the README runs them)
  fixtures/        offline docs and attack files (--offline and attack_demo.py
                   read them, so the agent can't run without them)

What stays out:
  my-agent/runs/   run logs (the handout says: don't submit logs)
  caches           __pycache__, .pyc files, test/lint caches
  questionnaire.md submitted as its own item, not inside the code ZIP
  course files     handout, PDF, sample-agent: not my work
"""

import zipfile
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent  # .../pyHarness/lab
PACKAGE = LAB_DIR / "ollama-lab"
OUTPUT = LAB_DIR / "week1-lab-submission.zip"

INCLUDE = ["my-agent", "target-service", "checks", "fixtures"]
# A file is skipped if ANY folder on its path has one of these names.
SKIP_DIRS = {"runs", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".claude"}


def wanted(path):
    """True for real files that belong in the submission."""
    parts = path.relative_to(PACKAGE).parts
    return path.is_file() and path.suffix != ".pyc" and not SKIP_DIRS.intersection(parts)


def main():
    count = 0
    # "w" overwrites an old ZIP, so a rebuild never keeps stale files.
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for top in INCLUDE:
            # rglob("*") walks the whole folder tree, hidden files (.git) included.
            for path in sorted((PACKAGE / top).rglob("*")):
                if wanted(path):
                    archive.write(path, Path("ollama-lab") / path.relative_to(PACKAGE))
                    count += 1
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"wrote {OUTPUT} ({count} files, {size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
