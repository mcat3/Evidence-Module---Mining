"use client";

import { useRef } from "react";

interface Props {
  ratio: number;
  onChange: (ratio: number) => void;
  leftLabel: string;
  rightLabel: string;
}

/** Draggable divider over the map; the map itself stays fully interactive on both sides. */
export default function SwipeHandle({ ratio, onChange, leftLabel, rightLabel }: Props) {
  const root = useRef<HTMLDivElement>(null);

  const setFromClientX = (clientX: number) => {
    const box = root.current?.getBoundingClientRect();
    if (!box) return;
    onChange(Math.min(0.98, Math.max(0.02, (clientX - box.left) / box.width)));
  };

  return (
    <div className="swipe" ref={root} aria-hidden={false}>
      <div className="swipe-label swipe-label-left" style={{ right: `calc(${(1 - ratio) * 100}% + 18px)` }}>
        <span className="swipe-arrow">◀</span> {leftLabel}
      </div>
      <div className="swipe-label swipe-label-right" style={{ left: `calc(${ratio * 100}% + 18px)` }}>
        {rightLabel} <span className="swipe-arrow">▶</span>
      </div>
      <div
        className="swipe-bar"
        style={{ left: `${ratio * 100}%` }}
        role="slider"
        tabIndex={0}
        aria-label="Before/after comparison divider"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(ratio * 100)}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          setFromClientX(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.currentTarget.hasPointerCapture(e.pointerId)) setFromClientX(e.clientX);
        }}
        onKeyDown={(e) => {
          const step = e.shiftKey ? 0.1 : 0.02;
          if (e.key === "ArrowLeft") onChange(Math.max(0.02, ratio - step));
          if (e.key === "ArrowRight") onChange(Math.min(0.98, ratio + step));
        }}
      >
        <div className="swipe-grip">
          <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden>
            <path d="M7 4 2 9l5 5M11 4l5 5-5 5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>
    </div>
  );
}
