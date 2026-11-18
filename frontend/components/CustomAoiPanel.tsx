"use client";

import type { Polygon } from "geojson";
import { useState } from "react";

import { api, type Job } from "@/lib/api";
import { fixed, isoDate, polygonAreaKm2, shiftYears } from "@/lib/format";
import type { DrawTool } from "./map/MapView";

const MAX_KM2 = 150;
const S2_START = "2017-03-28";

const STAGES = [
  { match: "Queued", label: "Queued for worker" },
  { match: "Stage 1", label: "STAC search & ingestion" },
  { match: "Stage 2", label: "Spectral indices & composites" },
  { match: "Stage 3: Random Forest", label: "Random Forest classification" },
  { match: "Stage 3: change", label: "Change detection & risk patterns" },
  { match: "Stage 3: SAM", label: "SAM hyperspectral tagging" },
  { match: "Stage 4", label: "Validation & uncertainty audit" },
  { match: "Stage 5", label: "Evidence packaging (SHA-256 + PDF)" },
  { match: "Uploading", label: "Publishing to object storage" },
];

export function stageIndex(job: Job): number {
  if (job.status === "SUCCESS") return STAGES.length;
  if (!job.stage || job.status === "PENDING") return 0;
  const i = STAGES.findIndex((s) => job.stage!.startsWith(s.match));
  return i < 0 ? 0 : i;
}

export function RunProgress({ run, onOpen, onDismiss }: { run: Job; onOpen: () => void; onDismiss: () => void }) {
  const idx = stageIndex(run);
  const failed = run.status === "FAILED";
  return (
    <section className="panel run">
      <header className="panel-head">
        <h2>{run.site_name}</h2>
        <span className={`run-state ${run.status.toLowerCase()}`}>{run.status}</span>
      </header>
      <ol className="stages">
        {STAGES.map((s, i) => {
          const state = failed && i === idx ? "failed" : i < idx ? "done" : i === idx && !failed ? "active" : "todo";
          return (
            <li key={s.label} className={state}>
              <span className="stage-dot" aria-hidden>{state === "done" ? "✓" : state === "failed" ? "✕" : ""}</span>
              {s.label}
            </li>
          );
        })}
      </ol>
      {failed && <p className="error-text">{run.error}</p>}
      <div className="run-actions">
        {run.status === "SUCCESS" && <button type="button" className="btn btn-primary" onClick={onOpen}>Open results</button>}
        {(failed || run.status === "SUCCESS") && <button type="button" className="btn" onClick={onDismiss}>Dismiss</button>}
      </div>
    </section>
  );
}

interface Props {
  aoi: Polygon | null;
  tool: DrawTool;
  onTool: (t: DrawTool) => void;
  onClear: () => void;
  onSubmitted: (job: Job) => void;
  onClose: () => void;
}

export default function CustomAoiPanel({ aoi, tool, onTool, onClear, onSubmitted, onClose }: Props) {
  const today = isoDate(new Date());
  const [name, setName] = useState("Custom AOI");
  const [target, setTarget] = useState(shiftYears(today, 0));
  const [baseline, setBaseline] = useState(shiftYears(today, -2));
  const [useBaseline, setUseBaseline] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const km2 = aoi ? polygonAreaKm2(aoi) : 0;
  const problems: string[] = [];
  if (aoi && km2 > MAX_KM2) problems.push(`AOI is ${fixed(km2)} km²; the limit is ${MAX_KM2} km²`);
  if (target > today) problems.push("Target date cannot be in the future");
  if (target < S2_START) problems.push(`Sentinel-2 L2A starts ${S2_START}`);
  if (useBaseline && baseline >= target) problems.push("Baseline must be before the target date");
  if (useBaseline && baseline < S2_START) problems.push(`Baseline predates Sentinel-2 L2A (${S2_START})`);

  const submit = async () => {
    if (!aoi) return;
    setBusy(true);
    setError(null);
    try {
      const job = await api.createJob({ aoi_geojson: aoi, target_date: target, baseline_date: useBaseline ? baseline : null, site_name: name.trim() || "Custom AOI" });
      onSubmitted(job);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel custom">
      <header className="panel-head">
        <h2>Live custom AOI analysis</h2>
        <button type="button" className="link" onClick={onClose}>Close</button>
      </header>
      <p className="muted">
        Draw an area on the map. The worker searches Sentinel-2 L2A (&lt; 20% cloud, ±15 days of each date), runs the full
        5-stage pipeline and seals the evidence package. A typical 60 km² run takes about 2 minutes.
      </p>

      <div className="draw-tools">
        <button type="button" className={`btn ${tool === "rectangle" ? "btn-on" : ""}`} onClick={() => onTool(tool === "rectangle" ? "off" : "rectangle")}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><rect x="2.5" y="3.5" width="11" height="9" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>
          Rectangle
        </button>
        <button type="button" className={`btn ${tool === "polygon" ? "btn-on" : ""}`} onClick={() => onTool(tool === "polygon" ? "off" : "polygon")}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><path d="M3 5.5 8 2l5.5 4-2 7.5h-7L3 5.5Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
          Polygon
        </button>
        {aoi && <button type="button" className="btn btn-ghost" onClick={onClear}>Clear</button>}
      </div>
      {tool !== "off" && (
        <p className="hint">
          {tool === "rectangle" ? "Click one corner on the map, then click the opposite corner." : "Click to add vertices; click the first vertex to close."}
        </p>
      )}

      {aoi ? (
        <div className={`aoi-area ${km2 > MAX_KM2 ? "bad" : ""}`}>
          AOI area <strong className="mono">{fixed(km2)} km²</strong> <span className="muted">/ {MAX_KM2} km² limit · drag vertices to edit</span>
        </div>
      ) : (
        <div className="aoi-area muted">No AOI drawn yet.</div>
      )}

      <form className="form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <label>
          <span>Site name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </label>
        <div className="form-row">
          <label>
            <span>
              <input type="checkbox" checked={useBaseline} onChange={(e) => setUseBaseline(e.target.checked)} /> Baseline date
            </span>
            <input type="date" value={baseline} min={S2_START} max={today} disabled={!useBaseline} onChange={(e) => setBaseline(e.target.value)} />
          </label>
          <label>
            <span>Target date</span>
            <input type="date" value={target} min={S2_START} max={today} onChange={(e) => setTarget(e.target.value)} />
          </label>
        </div>
        {problems.map((p) => <p key={p} className="error-text">{p}</p>)}
        {error && <p className="error-text">{error}</p>}
        <button type="submit" className="btn btn-primary btn-wide" disabled={!aoi || busy || problems.length > 0}>
          {busy ? <><span className="spinner" aria-hidden /> Submitting…</> : "Run live analysis"}
        </button>
      </form>
    </section>
  );
}
