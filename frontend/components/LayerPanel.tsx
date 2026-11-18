"use client";

import { useEffect, useState } from "react";

import type { JobResult } from "@/lib/api";
import { MINERAL_COLORS, RASTER_LAYERS, VECTOR_LAYERS, type Basemap, type RasterLayer, type Role, type VectorLayer } from "@/lib/layers";

interface Props {
  result: JobResult | null;
  basemap: Basemap;
  onBasemap: (b: Basemap) => void;
  raster: RasterLayer;
  onRaster: (r: RasterLayer) => void;
  vectors: Set<VectorLayer>;
  onToggleVector: (v: VectorLayer) => void;
  opacity: number;
  onOpacity: (o: number) => void;
  swipe: boolean;
  onSwipe: (s: boolean) => void;
  singleRole: Role;
  onSingleRole: (r: Role) => void;
}

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { id: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" role="radio" aria-checked={value === o.id}
          className={value === o.id ? "on" : ""} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Legend({ result, raster, vectors }: { result: JobResult; raster: RasterLayer; vectors: Set<VectorLayer> }) {
  const showClasses = raster === "landcover" || vectors.has("landcover_polygons");
  const showMinerals = vectors.has("mineral_tags");
  return (
    <>
      {raster === "ndvi" && (
        <div className="legend">
          <div className="legend-title">NDVI</div>
          <div className="ndvi-ramp" />
          <div className="ramp-labels"><span>−0.2 bare / water</span><span>0.8 dense veg.</span></div>
        </div>
      )}
      {showClasses && (
        <div className="legend">
          <div className="legend-title">Land classification</div>
          {Object.entries(result.class_legend).map(([id, c]) => (
            <div key={id} className="legend-row">
              <span className="swatch" style={{ background: `rgb(${c.rgb.join(",")})` }} />
              {c.name}
            </div>
          ))}
        </div>
      )}
      {showMinerals && (
        <div className="legend">
          <div className="legend-title">Dominant mineral (SAM)</div>
          {Object.entries(MINERAL_COLORS).map(([name, color]) => (
            <div key={name} className="legend-row">
              <span className="swatch" style={{ background: color }} />
              {name}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default function LayerPanel(p: Props) {
  const [open, setOpen] = useState(true);
  // Start collapsed on phones, where the open panel would cover most of the map.
  useEffect(() => {
    if (window.innerWidth <= 860) setOpen(false);
  }, []);
  const has = (r: RasterLayer) => r === "none" || !!p.result?.layers[r as Exclude<RasterLayer, "none">];

  return (
    <div className={`layer-panel ${open ? "" : "collapsed"}`}>
      <button type="button" className="layer-panel-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
          <path d="M8 1.5 1.5 5 8 8.5 14.5 5 8 1.5ZM1.5 8 8 11.5 14.5 8M1.5 11 8 14.5 14.5 11" fill="none"
            stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
        Layers
        <span className="chev">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="layer-panel-body">
          <div className="lp-section">
            <div className="lp-title">Basemap</div>
            <Segmented label="Basemap" value={p.basemap} onChange={p.onBasemap}
              options={[{ id: "satellite", label: "Satellite (Esri)" }, { id: "streets", label: "Streets (OSM)" }]} />
          </div>

          <div className="lp-section">
            <div className="lp-title">Comparison</div>
            <Segmented label="Comparison mode" value={p.swipe ? "swipe" : "single"}
              onChange={(v) => p.onSwipe(v === "swipe")}
              options={[{ id: "swipe", label: "Split-screen swipe" }, { id: "single", label: "Single date" }]} />
            {!p.swipe && (
              <Segmented label="Date shown" value={p.singleRole} onChange={p.onSingleRole}
                options={[{ id: "baseline", label: "Baseline" }, { id: "target", label: "Target" }]} />
            )}
          </div>

          <div className="lp-section">
            <div className="lp-title">Imagery <span className="lp-note">one at a time</span></div>
            {RASTER_LAYERS.map((l) => (
              <label key={l.id} className={`toggle-row ${has(l.id) ? "" : "disabled"}`}>
                <input type="checkbox" checked={p.raster === l.id} disabled={!has(l.id)}
                  onChange={() => p.onRaster(p.raster === l.id ? "none" : l.id)} />
                <span className="toggle" aria-hidden />
                <span className="toggle-text">
                  <span>{l.label}</span>
                  <small>{l.hint}</small>
                </span>
              </label>
            ))}
            <label className="opacity-row">
              <span>Opacity</span>
              <input type="range" min={0} max={1} step={0.05} value={p.opacity}
                onChange={(e) => p.onOpacity(Number(e.target.value))} disabled={p.raster === "none"} />
              <span className="mono">{Math.round(p.opacity * 100)}%</span>
            </label>
          </div>

          <div className="lp-section">
            <div className="lp-title">Vector overlays</div>
            {VECTOR_LAYERS.map((l) => (
              <label key={l.id} className="toggle-row">
                <input type="checkbox" checked={p.vectors.has(l.id)} onChange={() => p.onToggleVector(l.id)} />
                <span className="toggle" aria-hidden />
                <span className="toggle-text">
                  <span>{l.label}</span>
                  {l.hint && <small>{l.hint}</small>}
                </span>
              </label>
            ))}
          </div>

          {p.result && <Legend result={p.result} raster={p.raster} vectors={p.vectors} />}
        </div>
      )}
    </div>
  );
}
