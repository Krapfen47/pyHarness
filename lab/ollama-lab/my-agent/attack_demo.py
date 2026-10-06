"""Feed fixtures/attack-actions.jsonl straight into the runtime. No model involved.

This is the handout's "test the controls without relying on the model" step:
pretend a model asked for the four worst things in the fixture and show what
the runtime answers. Run from the my-agent folder:

    python attack_demo.py edit        # protected edit + path escape denied, bash asks a human
    python attack_demo.py read-only   # bash denied before any approval prompt appears

Nothing in target-service changes; check with `git status --short` afterwards.
"""

import json
import sys
from pathlib import Path

from student_agent import Runtime
from student_agent.cli import make_approver

LAB_DIR = Path(__file__).resolve().parents[1]
mode = sys.argv[1] if len(sys.argv) > 1 else "edit"

# The same yes/no approval prompt the real CLI uses. Its log events are thrown
# away here (lambda event: None), because the result line already shows them.
runtime = Runtime(LAB_DIR / "target-service", mode=mode, approve=make_approver(lambda event: None))
print(f"mode={mode}")

attacks = (LAB_DIR / "fixtures" / "attack-actions.jsonl").read_text(encoding="utf-8")
for line in attacks.splitlines():
    print(f"\n-> {line}")
    result = runtime.execute(json.loads(line))
    print(f"<- {result['status']}: {result['output']}")
