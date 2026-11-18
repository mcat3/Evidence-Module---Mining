"use client";

import "leaflet/dist/leaflet.css";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import L from "./leaflet-global";
import "@geoman-io/leaflet-geoman-free";

import type { Feature, FeatureCollection, Polygon } from "geojson";
import { useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, MapContainer, ScaleControl, TileLayer, useMap } from "react-leaflet";

import { artifactUrl, fetchGeoJSON, type Job } from "@/lib/api";
import { fixed } from "@/lib/format";
import { BASEMAPS, SATELLITE_LABELS_URL, mineralColor, type Basemap, type RasterLayer, type Role, type VectorLayer } from "@/lib/layers";
import { CornerImageOverlay } from "./CornerImageOverlay";

export type DrawTool = "off" | "rectangle" | "polygon";

export interface MapViewProps {
  job: Job | null;
  basemap: Basemap;
  raster: RasterLayer;
  vectors: Set<VectorLayer>;
  opacity: number;
  swipe: boolean;
  singleRole: Role;
  swipeRatio: number;
  drawTool: DrawTool;
  drawnAoi: Polygon | null;
  onAoiDrawn: (aoi: Polygon | null) => void;
  onDrawToolChange: (tool: DrawTool) => void;
}

const PANES: Record<string, { zIndex: number; side: "before" | "after" }> = {
  "tp-before": { zIndex: 300, side: "before" },
  "tp-after": { zIndex: 310, side: "after" },
  "tp-before-vec": { zIndex: 420, side: "before" },
  "tp-after-vec": { zIndex: 430, side: "after" },
};

const esc = (s: unknown) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

function popupHtml(title: string, rows: [string, string][]): string {
  return `<div class="tp-popup"><strong>${esc(title)}</strong><dl>${rows
    .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
    .join("")}</dl></div>`;
}

function useGeoJSON(jobId: string | undefined, name: string | undefined, enabled: boolean) {
  const [state, setState] = useState<{ key: string; data: FeatureCollection } | null>(null);
  const key = jobId && name ? `${jobId}/${name}` : "";
  useEffect(() => {
    if (!enabled || !jobId || !name) return;
    let live = true;
    fetchGeoJSON(jobId, name)
      .then((data) => live && setState({ key: `${jobId}/${name}`, data }))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [jobId, name, enabled]);
  return enabled && state?.key === key ? state.data : null;
}

/** Creates the comparison panes synchronously (before any overlay mounts) and keeps them for the map's lifetime. */
function ComparisonPanes({ children }: { children: React.ReactNode }) {
  const map = useMap();
  useState(() => {
    for (const [name, { zIndex }] of Object.entries(PANES)) {
      if (!map.getPane(name)) map.createPane(name).style.zIndex = String(zIndex);
    }
    return true;
  });
  return <>{children}</>;
}

/** Clips the before/after panes either side of the swipe handle (coordinates in Leaflet layer space). */
function SwipeClipper({ enabled, ratio }: { enabled: boolean; ratio: number }) {
  const map = useMap();
  useEffect(() => {
    const update = () => {
      const size = map.getSize();
      const nw = map.containerPointToLayerPoint([0, 0]);
      const se = map.containerPointToLayerPoint(size);
      const x = nw.x + size.x * ratio;
      const left = `polygon(${nw.x}px ${nw.y}px, ${x}px ${nw.y}px, ${x}px ${se.y}px, ${nw.x}px ${se.y}px)`;
      const right = `polygon(${x}px ${nw.y}px, ${se.x}px ${nw.y}px, ${se.x}px ${se.y}px, ${x}px ${se.y}px)`;
      for (const [name, { side }] of Object.entries(PANES)) {
        const pane = map.getPane(name);
        if (pane) pane.style.clipPath = enabled ? (side === "before" ? left : right) : "";
      }
    };
    update();
    map.on("move zoomend viewreset resize", update);
    return () => {
      map.off("move zoomend viewreset resize", update);
    };
  }, [map, enabled, ratio]);
  return null;
}

function cornersFor(job: Job) {
  const r = job.result!;
  if (r.image_corners_wgs84) {
    const c = r.image_corners_wgs84;
    return { topLeft: c.top_left, topRight: c.top_right, bottomLeft: c.bottom_left };
  }
  const [[s, w], [n, e]] = r.image_bounds_wgs84;
  return { topLeft: [n, w] as L.LatLngTuple, topRight: [n, e] as L.LatLngTuple, bottomLeft: [s, w] as L.LatLngTuple };
}

function RasterOverlay({ job, file, pane, opacity, pixelated }: {
  job: Job; file: string; pane: string; opacity: number; pixelated: boolean;
}) {
  const map = useMap();
  const layer = useRef<CornerImageOverlay | null>(null);
  useEffect(() => {
    const overlay = new CornerImageOverlay(artifactUrl(job.id, file), cornersFor(job), {
      pane, className: pixelated ? "tp-pixelated" : undefined, alt: file,
    });
    overlay.setOpacity(opacity);
    overlay.addTo(map);
    layer.current = overlay;
    return () => {
      overlay.remove();
      layer.current = null;
    };
    // opacity is applied by the effect below without re-creating the image
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, job, file, pane, pixelated]);
  useEffect(() => {
    layer.current?.setOpacity(opacity);
  }, [opacity]);
  return null;
}

function FitToJob({ job }: { job: Job | null }) {
  const map = useMap();
  const id = job?.id;
  useEffect(() => {
    if (!job?.result) return;
    const [[s, w], [n, e]] = job.result.image_bounds_wgs84;
    // Keep the scene clear of the floating layer panel on wide maps.
    const panel = map.getSize().x > 900 ? 300 : 0;
    map.flyToBounds([[s, w], [n, e]], { paddingTopLeft: [56, 56], paddingBottomRight: [panel + 16, 48], duration: 0.8 });
    // fly only when a different job is opened
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, id]);
  return null;
}

function FitToAoi({ job }: { job: Job | null }) {
  const map = useMap();
  const id = job?.id;
  useEffect(() => {
    if (job?.result || !job?.aoi_geojson) return;
    map.flyToBounds(L.geoJSON(job.aoi_geojson).getBounds(), { padding: [48, 48], duration: 0.8 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, id]);
  return null;
}

const DRAW_STYLE: L.PathOptions = { color: "#3987e5", weight: 2, fillColor: "#3987e5", fillOpacity: 0.12 };

function DrawControl({ tool, aoi, onAoiDrawn, onToolChange }: {
  tool: DrawTool; aoi: Polygon | null; onAoiDrawn: (aoi: Polygon | null) => void; onToolChange: (t: DrawTool) => void;
}) {
  const map = useMap();
  const drawn = useRef<L.Polygon | null>(null);
  const callbacks = useRef({ onAoiDrawn, onToolChange });
  callbacks.current = { onAoiDrawn, onToolChange };

  useEffect(() => {
    map.pm.setGlobalOptions({ pathOptions: DRAW_STYLE, templineStyle: DRAW_STYLE, hintlineStyle: { ...DRAW_STYLE, dashArray: "4 4" }, allowSelfIntersection: false } as L.PM.GlobalOptions);
    const emit = () => {
      const geom = drawn.current?.toGeoJSON().geometry;
      if (geom?.type === "Polygon") callbacks.current.onAoiDrawn(geom);
    };
    const onCreate = (e: { layer: L.Layer }) => {
      drawn.current?.remove();
      const layer = e.layer as L.Polygon;
      drawn.current = layer;
      layer.pm.enable({ allowSelfIntersection: false });
      layer.on("pm:edit", emit);
      emit();
      callbacks.current.onToolChange("off");
    };
    map.on("pm:create", onCreate as L.LeafletEventHandlerFn);
    return () => {
      map.off("pm:create", onCreate as L.LeafletEventHandlerFn);
    };
  }, [map]);

  useEffect(() => {
    if (tool === "off") map.pm.disableDraw();
    else map.pm.enableDraw(tool === "rectangle" ? "Rectangle" : "Polygon", { snappable: false });
  }, [map, tool]);

  useEffect(() => {
    if (!aoi && drawn.current) {
      drawn.current.remove();
      drawn.current = null;
    }
  }, [aoi]);

  useEffect(() => () => {
    drawn.current?.remove();
    map.pm.disableDraw();
  }, [map]);
  return null;
}

function classColor(job: Job, classId: number): string {
  const rgb = job.result?.class_legend[String(classId)]?.rgb ?? [128, 128, 128];
  return `rgb(${rgb.join(",")})`;
}

function LandcoverPolygons({ job, role, pane }: { job: Job; role: Role; pane: string }) {
  const file = job.result?.layers.landcover_polygons?.[role];
  const data = useGeoJSON(job.id, file, true);
  if (!data) return null;
  return (
    <GeoJSON
      key={`${job.id}-${file}`}
      data={data}
      pane={pane}
      style={(f) => {
        const id = Number(f?.properties?.class_id);
        const color = classColor(job, id);
        return { color: id === 1 ? "#cfcfcf" : color, weight: 1, fillColor: color, fillOpacity: 0.4, opacity: 0.9 };
      }}
      onEachFeature={(f: Feature, layer) => {
        const p = f.properties ?? {};
        layer.bindPopup(popupHtml(String(p.class_name), [
          ["Date", role === "baseline" ? `Baseline ${job.baseline_date}` : `Target ${job.target_date}`],
          ["Area", `${fixed(Number(p.area_ha), 2)} ha`],
        ]));
      }}
    />
  );
}

/** Target-date products; in swipe mode they live in the target pane so the left half shows only baseline evidence. */
function VectorOverlays({ job, vectors, pane }: { job: Job; vectors: Set<VectorLayer>; pane: string }) {
  const layers = job.result?.layers ?? {};
  const minerals = useGeoJSON(job.id, layers.mineral_tags, vectors.has("mineral_tags"));
  const stockpiles = useGeoJSON(job.id, layers.new_stockpiles, vectors.has("new_stockpiles"));
  const lowConf = useGeoJSON(job.id, layers.low_confidence, vectors.has("low_confidence"));
  return (
    <>
      {lowConf && (
        <GeoJSON key={`${job.id}-lc-${pane}`} data={lowConf} pane={pane}
          style={{ color: "#f0efec", weight: 0.8, dashArray: "2 3", fillColor: "#f0efec", fillOpacity: 0.16 }}
          onEachFeature={(f, l) => l.bindPopup(popupHtml("Low-confidence zone", [
            ["Area", `${fixed(Number(f.properties?.area_ha), 2)} ha`],
            ["Rule", `Model certainty < ${Math.round(Number(f.properties?.threshold ?? 0.7) * 100)}%`],
          ]))} />
      )}
      {minerals && (
        <GeoJSON key={`${job.id}-min-${pane}`} data={minerals} pane={pane}
          style={(f) => {
            const c = mineralColor(String(f?.properties?.dominant_mineral));
            return { color: c, weight: 1.5, fillColor: c, fillOpacity: 0.5 };
          }}
          onEachFeature={(f, l) => {
            const p = f.properties ?? {};
            l.bindPopup(popupHtml(String(p.dominant_mineral), [
              ["Host class", String(p.class_name)],
              ["Spectral purity", `${fixed(Number(p.mineral_purity_pct))}% of pixels`],
              ["Area", `${fixed(Number(p.area_ha), 2)} ha`],
              ["Method", "SAM vs reference library"],
            ]));
          }} />
      )}
      {stockpiles && (
        <GeoJSON key={`${job.id}-sp-${pane}`} data={stockpiles} pane={pane}
          style={{ color: "#ffffff", weight: 2, dashArray: "5 4", fillColor: "#ffffff", fillOpacity: 0.08 }}
          onEachFeature={(f, l) => {
            const p = f.properties ?? {};
            l.bindPopup(popupHtml(`New stockpile #${p.stockpile_id}`, [
              ["Area", `${fixed(Number(p.area_ha), 2)} ha`],
              ["Dominant mineral", String(p.dominant_mineral ?? "n/a")],
              ["Spectral purity", p.mineral_purity_pct != null ? `${fixed(Number(p.mineral_purity_pct))}%` : "n/a"],
            ]));
          }} />
      )}
      {vectors.has("aoi") && job.aoi_geojson && (
        <GeoJSON key={`${job.id}-aoi`} data={job.aoi_geojson} interactive={false}
          style={{ color: "#ffffff", weight: 2, dashArray: "8 6", fill: false, opacity: 0.85 }} />
      )}
    </>
  );
}

export default function MapView(props: MapViewProps) {
  const { job, basemap, raster, vectors, opacity, swipe, singleRole, swipeRatio } = props;
  const result = job?.status === "SUCCESS" ? job.result : null;
  const shownJob = result ? job : null;
  const roles: Role[] = swipe ? ["baseline", "target"] : [singleRole];
  const paneFor = (role: Role, vec = false) => {
    const side = swipe ? (role === "baseline" ? "before" : "after") : "after";
    return `tp-${side}${vec ? "-vec" : ""}`;
  };
  const rasterFiles = useMemo(() => {
    if (!result || raster === "none") return {};
    return result.layers[raster] ?? {};
  }, [result, raster]);
  const base = BASEMAPS[basemap];

  return (
    <MapContainer center={[22.6, 82.4]} zoom={6} minZoom={3} maxZoom={19} zoomSnap={0.25} zoomDelta={0.5} zoomControl
      className="tp-map" worldCopyJump attributionControl preferCanvas={false}>
      <TileLayer key={basemap} url={base.url} attribution={base.attribution} maxNativeZoom={base.maxNativeZoom} maxZoom={19} />
      {basemap === "satellite" && (
        <TileLayer url={SATELLITE_LABELS_URL} maxNativeZoom={18} maxZoom={19} opacity={0.75} />
      )}
      <ComparisonPanes>
      <SwipeClipper enabled={swipe && !!shownJob} ratio={swipeRatio} />
      {shownJob && roles.map((role) => {
        const file = rasterFiles[role];
        return file ? (
          <RasterOverlay key={`${shownJob.id}-${file}`} job={shownJob} file={file} pane={paneFor(role)}
            opacity={opacity} pixelated={raster === "landcover"} />
        ) : null;
      })}
      {shownJob && vectors.has("landcover_polygons") && roles.map((role) => (
        <LandcoverPolygons key={`${shownJob.id}-${role}-${paneFor(role, true)}`} job={shownJob} role={role}
          pane={paneFor(role, true)} />
      ))}
      {shownJob && <VectorOverlays job={shownJob} vectors={vectors} pane={swipe ? "tp-after-vec" : "overlayPane"} />}
      </ComparisonPanes>
      {job && !result && job.aoi_geojson && (
        <GeoJSON key={`${job.id}-pending-aoi`} data={job.aoi_geojson} interactive={false}
          style={{ color: "#3987e5", weight: 2, dashArray: "8 6", fillOpacity: 0.08 }} />
      )}
      <FitToJob job={shownJob} />
      <FitToAoi job={job} />
      <DrawControl tool={props.drawTool} aoi={props.drawnAoi} onAoiDrawn={props.onAoiDrawn}
        onToolChange={props.onDrawToolChange} />
      <ScaleControl position="bottomleft" imperial={false} />
    </MapContainer>
  );
}
