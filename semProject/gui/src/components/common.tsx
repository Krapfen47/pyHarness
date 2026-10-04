// Small building blocks shared by several components.

import { useState, type ReactNode } from "react";
import { STATUS_TONE } from "../format";

export function Pill({ tone = "", children, title }: {
  tone?: string; children: ReactNode; title?: string;
}) {
  return <span className={`pill ${tone}`} title={title}>{children}</span>;
}

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return <Pill tone={STATUS_TONE[status] ?? ""}>{label ?? status.replace("_", " ")}</Pill>;
}

/** The dashed "S2" / "S3" tag on greyed-out future features. */
export function StageTag({ stage }: { stage: 2 | 3 }) {
  return <span className="stage-tag" title={STAGE_HINT[stage]}>S{stage}</span>;
}

export const STAGE_HINT = {
  2: "Planned for Stage 2: navigation, context and sessions",
  3: "Planned for Stage 3: security, autonomy and advanced features",
};

/** A <pre> block with a copy button that collapses when the text is long. */
export function CodeBlock({ text, className = "", clampLines = 14, cursor = false }: {
  text: string; className?: string; clampLines?: number; cursor?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const long = text.split("\n").length > clampLines || text.length > 1600;
  const clamped = long && !expanded;
  return (
    <div>
      <div className={`code ${clamped ? "clamped" : ""}`}>
        <button className="btn small ghost copy" title="Copy"
          onClick={(e) => { e.stopPropagation(); void navigator.clipboard.writeText(text); }}>
          copy
        </button>
        <pre className={`${className} ${cursor ? "cursor" : ""}`}>{text}</pre>
      </div>
      {long && (
        <button className="code-more" onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>
          {expanded ? "show less" : `show all (${text.split("\n").length} lines)`}
        </button>
      )}
    </div>
  );
}

export function Section({ title, extra, children }: {
  title: string; extra?: ReactNode; children: ReactNode;
}) {
  return (
    <div className="section">
      <div className="row"><span className="label grow">{title}</span>{extra}</div>
      {children}
    </div>
  );
}

export function Gauge({ label, value, max, warnAt = 0.6, suffix = "" }: {
  label: string; value: number; max: number; warnAt?: number; suffix?: string;
}) {
  const ratio = max > 0 ? Math.min(1, value / max) : 0;
  const tone = ratio >= 1 ? "bad" : ratio >= warnAt ? "warn" : "";
  return (
    <div className="gauge" title={`${value} of ${max}`}>
      <div className="gauge-label"><span>{label}</span><span>{value} / {max}{suffix}</span></div>
      <div className="gauge-track">
        <div className={`gauge-fill ${tone}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
