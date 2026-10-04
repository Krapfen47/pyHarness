// Step through a past run event by event. The screen is always
// replay(events, k): the run exactly as it looked after event k.

import { useEffect } from "react";
import type { HarnessEvent, UnknownEvent } from "../events";
import { clock } from "../format";

export function ReplayBar({ events, index, onIndex, playing, onPlaying }: {
  events: (HarnessEvent | UnknownEvent)[];
  index: number;
  onIndex: (index: number) => void;
  playing: boolean;
  onPlaying: (playing: boolean) => void;
}) {
  useEffect(() => {
    if (!playing) return;
    if (index >= events.length) { onPlaying(false); return; }
    const timer = setTimeout(() => onIndex(index + 1), 180);
    return () => clearTimeout(timer);
  }, [playing, index, events.length, onIndex, onPlaying]);

  const current = events[index - 1];
  return (
    <div className="replay small">
      <span className="label">replay</span>
      <button className="btn small" onClick={() => onIndex(Math.max(1, index - 1))} title="Previous event">◀</button>
      <button className="btn small" onClick={() => {
        if (!playing && index >= events.length) onIndex(1);
        onPlaying(!playing);
      }}>{playing ? "❚❚ pause" : "▶ play"}</button>
      <button className="btn small" onClick={() => onIndex(Math.min(events.length, index + 1))} title="Next event">▶</button>
      <input type="range" min={1} max={events.length} value={index}
        onChange={(e) => { onPlaying(false); onIndex(Number(e.target.value)); }} />
      <span className="mono faint" style={{ minWidth: 230 }}>
        {index}/{events.length} · {current?.type} {current && `· ${clock(current.time)}`}
      </span>
    </div>
  );
}
