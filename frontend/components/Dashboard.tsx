"use client";

import type { Polygon } from "geojson";
import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import { api, type Health, type Job, type JobSummary } from "@/lib/api";
import type { Basemap, RasterLayer, Role, VectorLayer } from "@/lib/layers";
import CustomAoiPanel, { RunProgress } from "./CustomAoiPanel";
import LayerPanel from "./LayerPanel";
import type { DrawTool } from "./map/MapView";
import SwipeHandle from "./map/SwipeHandle";
import JobReport from "./report/JobReport";

const MapView = dynamic(() => import("./map/MapView"), {
  ssr: false,
  loading: () => <div className="tp-map map-loading">Loading map…</div>,
});

const DEFAULT_VECTORS: VectorLayer[] = ["aoi", "new_stockpiles"];
const RASTER_NAMES: Record<RasterLayer, string> = {
  rgb: "True-color RGB", false_color: "False-color SWIR", ndvi: "NDVI", landcover: "ML classification", none: "",
};

function JobPicker({ jobs, currentId, onPick, onDraw }: {
  jobs: JobSummary[]; currentId?: string; onPick: (id: string) => void; onDraw: () => void;
}) {
  const demo = jobs.filter((j) => j.is_demo);
  const done = jobs.filter((j) => !j.is_demo && j.status === "SUCCESS");
  const other = jobs.filter((j) => !j.is_demo && j.status !== "SUCCESS");
  const label = (j: JobSummary) => `${j.site_name} · ${j.baseline_date?.slice(0, 4) ?? "—"} → ${j.target_date.slice(0, 4)}`;
  return (
    <label className="picker">
      <span className="sr-only">Switch case study</span>
      <select value={currentId ?? ""} onChange={(e) => (e.target.value === "__draw" ? onDraw() : e.target.value && onPick(e.target.value))}>
        <option value="" disabled>Switch case study…</option>
        {demo.length > 0 && (
          <optgroup label="Pre-computed demo">
            {demo.map((j) => <option key={j.id} value={j.id}>{label(j)}</option>)}
          </optgroup>
        )}
        {done.length > 0 && (
          <optgroup label="Completed live analyses">
            {done.map((j) => <option key={j.id} value={j.id}>{label(j)}</option>)}
          </optgroup>
        )}
        {other.length > 0 && (
          <optgroup label="In progress / failed">
            {other.map((j) => <option key={j.id} value={j.id}>{`${label(j)} (${j.status.toLowerCase()})`}</option>)}
          </optgroup>
        )}
        <optgroup label="New">
          <option value="__draw">✎ Draw a new custom AOI polygon…</option>
        </optgroup>
      </select>
    </label>
  );
}

function setUrlJob(id: string | null) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set("job", id);
  else url.searchParams.delete("job");
  url.searchParams.delete("demo");
  window.history.replaceState(null, "", url);
}

export default function Dashboard() {
  const [job, setJob] = useState<Job | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [drawOpen, setDrawOpen] = useState(false);
  const [drawTool, setDrawTool] = useState<DrawTool>("off");
  const [drawnAoi, setDrawnAoi] = useState<Polygon | null>(null);
  const [run, setRun] = useState<Job | null>(null);

  const [basemap, setBasemap] = useState<Basemap>("satellite");
  const [raster, setRaster] = useState<RasterLayer>("rgb");
  const [vectors, setVectors] = useState<Set<VectorLayer>>(new Set(DEFAULT_VECTORS));
  const [opacity, setOpacity] = useState(1);
  const [swipe, setSwipe] = useState(true);
  const [singleRole, setSingleRole] = useState<Role>("target");
  const [ratio, setRatio] = useState(0.5);

  const refreshJobs = useCallback(() => api.jobs().then(setJobs).catch(() => undefined), []);

  const show = useCallback((next: Job) => {
    setJob(next);
    setError(null);
    setDrawOpen(false);
    setDrawTool("off");
    setUrlJob(next.id);
    if (next.status !== "SUCCESS") setRun(next);
  }, []);

  const loadDemo = useCallback(async () => {
    setLoading("Loading Gevra case study…");
    try {
      const demo = await api.demo();
      setRaster("rgb");
      setVectors(new Set(DEFAULT_VECTORS));
      setSwipe(true);
      setRatio(0.5);
      setOpacity(1);
      show(demo);
      void refreshJobs();
    } catch (e) {
      setError(`Demo could not be loaded: ${(e as Error).message}`);
    } finally {
      setLoading(null);
    }
  }, [show, refreshJobs]);

  const openJob = useCallback(async (id: string) => {
    setLoading("Loading analysis…");
    try {
      show(await api.job(id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(null);
    }
  }, [show]);

  // Initial load: health, job list, and an optional ?job= / ?demo deep link.
  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    api.health().then(setHealth).catch(() => setHealth({ status: "degraded", services: { api: "unreachable" }, demo_available: false }));
    void refreshJobs();
    const params = new URLSearchParams(window.location.search);
    const id = params.get("job");
    if (id) void openJob(id);
    else if (params.has("demo")) void loadDemo();
  }, [refreshJobs, openJob, loadDemo]);

  useEffect(() => {
    const t = setInterval(() => {
      api.health().then(setHealth).catch(() => setHealth({ status: "degraded", services: { api: "unreachable" }, demo_available: false }));
    }, 30000);
    return () => clearInterval(t);
  }, []);

  // Poll a live run until it settles; the finished job then replaces the pending view.
  const runId = run?.id;
  const runActive = run && (run.status === "PENDING" || run.status === "RUNNING");
  useEffect(() => {
    if (!runId || !runActive) return;
    const t = setInterval(async () => {
      try {
        const next = await api.job(runId);
        setRun(next);
        if (next.status === "SUCCESS" || next.status === "FAILED") {
          void refreshJobs();
          setJob((cur) => (cur?.id === next.id ? next : cur));
        }
      } catch {
        /* transient: keep polling */
      }
    }, 3000);
    return () => clearInterval(t);
  }, [runId, runActive, refreshJobs]);

  const toggleVector = (v: VectorLayer) =>
    setVectors((cur) => {
      const next = new Set(cur);
      if (next.has(v)) next.delete(v);
      else next.add(v);
      return next;
    });

  const startDraw = () => {
    setDrawOpen(true);
    setDrawTool(drawnAoi ? "off" : "rectangle");
  };

  const result = job?.status === "SUCCESS" ? job.result : null;
  const scenes = result?.scenes;
  const apiOk = health?.status === "ok";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
            <path d="M16 2.5 4.5 7v8.2c0 7 4.8 12.4 11.5 14.3 6.7-1.9 11.5-7.3 11.5-14.3V7L16 2.5Z" fill="#1c5cab" />
            <path d="M8.5 19.5 13 13l3.5 4.5 2.5-3 4.5 5" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          </svg>
          <div>
            <div className="brand-name">TerraProof</div>
            <div className="brand-sub">Mining intelligence · auditable evidence</div>
          </div>
        </div>

        <button type="button" className="btn-demo" onClick={loadDemo} disabled={!!loading}>
          {loading?.startsWith("Loading Gevra") ? <span className="spinner" aria-hidden /> : (
            <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden><path d="M5 3.5v11l9-5.5-9-5.5Z" fill="currentColor" /></svg>
          )}
          Load Pre-Computed Demo (Gevra Mine 2021 vs 2024)
        </button>

        <JobPicker jobs={jobs} currentId={job?.id} onPick={openJob} onDraw={startDraw} />

        <button type="button" className={`btn btn-draw ${drawOpen ? "btn-on" : ""}`} onClick={() => (drawOpen ? setDrawOpen(false) : startDraw())}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden><path d="M3 5.5 8 2l5.5 4-2 7.5h-7L3 5.5Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
          Custom AOI
        </button>

        <div className={`health ${health ? (apiOk ? "ok" : "bad") : ""}`}
          title={health ? Object.entries(health.services).map(([k, v]) => `${k}: ${v}`).join("\n") : "checking…"}>
          <span className="dot" aria-hidden />
          {health ? (apiOk ? "Services online" : "Services degraded") : "Checking…"}
        </div>
      </header>

      <main className="workspace">
        <div className="map-area">
          <MapView job={job} basemap={basemap} raster={raster} vectors={vectors} opacity={opacity}
            swipe={swipe} singleRole={singleRole} swipeRatio={ratio}
            drawTool={drawTool} drawnAoi={drawnAoi} onAoiDrawn={setDrawnAoi} onDrawToolChange={setDrawTool} />

          {result && swipe && (raster !== "none" || vectors.has("landcover_polygons")) && (
            <SwipeHandle ratio={ratio} onChange={setRatio}
              leftLabel={`Baseline · ${scenes?.baseline?.acquired.slice(0, 10) ?? job?.baseline_date}`}
              rightLabel={`Target · ${scenes?.target.acquired.slice(0, 10) ?? job?.target_date}`} />
          )}

          <LayerPanel result={result} basemap={basemap} onBasemap={setBasemap} raster={raster} onRaster={setRaster}
            vectors={vectors} onToggleVector={toggleVector} opacity={opacity} onOpacity={setOpacity}
            swipe={swipe} onSwipe={setSwipe} singleRole={singleRole} onSingleRole={setSingleRole} />

          {result && (
            <div className="map-caption">
              {raster !== "none" ? RASTER_NAMES[raster] : "Basemap only"}
              {swipe ? " · drag the divider to compare dates" : ` · ${singleRole === "baseline" ? "baseline" : "target"} date`}
            </div>
          )}
          {loading && <div className="map-toast"><span className="spinner" aria-hidden /> {loading}</div>}
        </div>

        <aside className="sidebar">
          {error && (
            <div className="alert-error" role="alert">
              {error}
              <button type="button" className="link" onClick={() => setError(null)}>Dismiss</button>
            </div>
          )}

          {run && (drawOpen || run.id !== job?.id || run.status !== "SUCCESS") && (
            <RunProgress run={run} onOpen={() => show(run)} onDismiss={() => setRun(null)} />
          )}

          {drawOpen && (
            <CustomAoiPanel aoi={drawnAoi} tool={drawTool} onTool={setDrawTool}
              onClear={() => { setDrawnAoi(null); setDrawTool("rectangle"); }}
              onSubmitted={(submitted) => {
                setRun(submitted);
                setJob(submitted);
                setDrawnAoi(null);
                setDrawOpen(false);
                setUrlJob(submitted.id);
                void refreshJobs();
              }}
              onClose={() => { setDrawOpen(false); setDrawTool("off"); }} />
          )}

          {!drawOpen && result && job && <JobReport job={job} />}

          {!drawOpen && !job && !run && (
            <div className="empty">
              <h1>Mining activity, measured and sealed.</h1>
              <p>
                TerraProof compares two Sentinel-2 acquisitions of a mine, classifies every 10 m pixel with a Random Forest,
                tags stockpile mineralogy with a spectral angle mapper, and seals the result in a SHA-256 evidence package.
              </p>
              <button type="button" className="btn btn-primary btn-wide" onClick={loadDemo} disabled={!!loading}>
                Load the Gevra demo (2021 vs 2024)
              </button>
              <button type="button" className="btn btn-wide" onClick={startDraw}>Draw a custom AOI for a live run</button>
              <ul className="empty-steps">
                <li><strong>1</strong> Swipe the divider to compare baseline and target imagery.</li>
                <li><strong>2</strong> Toggle RGB, SWIR, NDVI, ML polygons and mineral tags in Layers.</li>
                <li><strong>3</strong> Verify the evidence hashes and download the PDF dossier.</li>
              </ul>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}
