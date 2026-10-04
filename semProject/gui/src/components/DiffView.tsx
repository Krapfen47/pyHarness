// Two ways to show a change:
//   UnifiedDiff  the final `git diff` text from verification
//   EditDiff     one edit_file request (old -> new), computed here with jsdiff

import { diffLines } from "diff";
import { useMemo } from "react";

interface Line {
  kind: "file" | "hunk" | "add" | "del" | "ctx" | "note";
  text: string;
  oldNo?: number;
  newNo?: number;
}

/** Turn unified-diff text into numbered lines. */
function parseUnified(diff: string): Line[] {
  const lines: Line[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const raw of diff.split("\n")) {
    if (raw.startsWith("diff --git")) {
      const match = / b\/(.+)$/.exec(raw);
      lines.push({ kind: "file", text: match ? match[1] : raw });
    } else if (raw.startsWith("index ") || raw.startsWith("--- ") || raw.startsWith("+++ ")
      || raw.startsWith("new file mode") || raw.startsWith("deleted file mode")) {
      continue; // header details; the file name is already shown
    } else if (raw.startsWith("@@")) {
      // "@@ -14,6 +14,10 @@ ..." = old lines start at 14, new lines start at 14
      const match = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(raw);
      if (match) { oldNo = Number(match[1]); newNo = Number(match[2]); }
      lines.push({ kind: "hunk", text: raw });
    } else if (raw.startsWith("+")) {
      lines.push({ kind: "add", text: raw, newNo: newNo++ });
    } else if (raw.startsWith("-")) {
      lines.push({ kind: "del", text: raw, oldNo: oldNo++ });
    } else if (raw.startsWith("\\")) {
      lines.push({ kind: "note", text: raw });
    } else if (raw !== "" || lines.length > 0) {
      lines.push({ kind: "ctx", text: raw, oldNo: oldNo++, newNo: newNo++ });
    }
  }
  return lines;
}

function Lines({ lines }: { lines: Line[] }) {
  return (
    <div className="diff">
      {lines.map((line, i) =>
        line.kind === "file" ? (
          <div key={i} className="diff-file">{line.text}</div>
        ) : (
          <div key={i} className={`diff-line ${line.kind}`}>
            <span className="no">{line.oldNo ?? ""}</span>
            <span className="no">{line.newNo ?? ""}</span>
            <span className="text">{line.text}</span>
          </div>
        ))}
    </div>
  );
}

export function UnifiedDiff({ diff }: { diff: string }) {
  if (!diff.trim()) return <div className="faint">(no changes)</div>;
  return <Lines lines={parseUnified(diff)} />;
}

export function EditDiff({ before, after }: { before: string; after: string }) {
  // useMemo: only recompute the diff when the texts change, not on every redraw.
  const lines = useMemo(() => {
    const result: Line[] = [];
    for (const part of diffLines(before, after)) {
      const kind = part.added ? "add" : part.removed ? "del" : "ctx";
      const sign = part.added ? "+" : part.removed ? "-" : " ";
      const text = part.value.endsWith("\n") ? part.value.slice(0, -1) : part.value;
      for (const line of text.split("\n")) result.push({ kind, text: sign + line });
    }
    return result;
  }, [before, after]);
  return <Lines lines={lines} />;
}
