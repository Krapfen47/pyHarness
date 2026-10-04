// The handout's Figure 1 ("CLI or UI -> controller <-> LLM -> tools / execution /
// context -> verification"), drawn live: the box the latest event belongs to
// lights up, and the arrow between the last two boxes moves.
// Dashed boxes are reserved for Stage 2 and Stage 3.

import { modelLabel } from "../format";
import type { FlowNode, RunView } from "../state";

const W = 160;
const H = 46;

interface NodeSpec {
  id: string;
  x: number;
  y: number;
  title: string;
  sub: string;
  stage?: 2 | 3;
}

function nodes(view: RunView): NodeSpec[] {
  const model = modelLabel(view.start?.model ?? view.launch?.model ?? "model");
  const sandbox = view.start?.sandbox;
  return [
    { id: "context_mgr", x: 20, y: 20, title: "Context manager", sub: "compaction · S2", stage: 2 },
    { id: "context", x: 200, y: 20, title: "Basic context", sub: "rules + task + files" },
    { id: "llm", x: 420, y: 20, title: "LLM (Ollama)", sub: model.length > 24 ? `${model.slice(0, 23)}…` : model },
    { id: "policy", x: 640, y: 20, title: "Policy + approvals", sub: "autonomy · S3", stage: 3 },
    { id: "ui", x: 20, y: 95, title: "You (GUI / CLI)", sub: "submit · review" },
    { id: "controller", x: 200, y: 95, title: "Agent controller", sub: "validate · count · limit" },
    { id: "tools", x: 420, y: 95, title: "Repository tools", sub: "PathGuard boundary" },
    { id: "verification", x: 640, y: 95, title: "Verification", sub: "acceptance · regression · scope" },
    { id: "sessions", x: 20, y: 170, title: "Sessions", sub: "resume · history · S2", stage: 2 },
    { id: "sandbox", x: 420, y: 170, title: "Docker sandbox",
      sub: sandbox?.problem ? "unavailable" : "--network none · read-only" },
  ];
}

// Each edge: the two nodes, and the SVG path between them.
const EDGES: { a: string; b: string; d: string; both?: boolean; stage?: 2 | 3 }[] = [
  { a: "ui", b: "controller", d: "M180 118 H200" },
  { a: "context", b: "controller", d: "M280 66 V95" },
  { a: "controller", b: "llm", d: "M360 110 H390 V43 H420", both: true },
  { a: "controller", b: "tools", d: "M360 118 H420", both: true },
  { a: "controller", b: "sandbox", d: "M360 126 H390 V193 H420", both: true },
  { a: "controller", b: "verification", d: "M320 95 V81 H720 V95" },
  { a: "verification", b: "sandbox", d: "M720 141 V193 H580", both: true },
  { a: "verification", b: "ui", d: "M780 141 V228 H190 V132 H180" },
  { a: "context_mgr", b: "context", d: "M180 43 H200", stage: 2 },
  { a: "sessions", b: "controller", d: "M180 193 H240 V141", stage: 2 },
  { a: "policy", b: "tools", d: "M640 50 H610 V110 H580", stage: 3 },
];

function edgeActive(edge: { a: string; b: string }, active: [FlowNode, FlowNode] | null): boolean {
  if (!active) return false;
  const [from, to] = active;
  return (edge.a === from && edge.b === to) || (edge.a === to && edge.b === from);
}

export function FlowDiagram({ view }: { view: RunView }) {
  return (
    <div className="flow">
      <svg viewBox="0 0 820 240" role="img"
        aria-label="Architecture of the harness; the active component is highlighted">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
            orient="auto-start-reverse">
            <path d="M0 0 L10 5 L0 10 z" fill="currentColor" />
          </marker>
        </defs>
        {EDGES.map((edge) => {
          const active = edgeActive(edge, view.activeEdge);
          return (
            <path key={`${edge.a}-${edge.b}`} d={edge.d}
              className={`edge ${active ? "active" : ""} ${edge.stage ? "reserved" : ""}`}
              style={{ color: active ? "var(--accent)" : "var(--border-strong)" }}
              markerEnd="url(#arrow)" markerStart={edge.both ? "url(#arrow)" : undefined} />
          );
        })}
        {nodes(view).map((node) => (
          <g key={node.id}
            className={`node ${view.activeNode === node.id ? "active" : ""} ${node.stage ? "reserved" : ""}`}>
            <title>{node.stage ? `Planned for Stage ${node.stage}` : node.title}</title>
            <rect x={node.x} y={node.y} width={W} height={H} rx={7} />
            <text x={node.x + 10} y={node.y + 19}>{node.title}</text>
            <text className="sub" x={node.x + 10} y={node.y + 35}>{node.sub}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}
