import type { FeatureCollection, Polygon } from "geojson";

export type JobState = "PENDING" | "RUNNING" | "SUCCESS" | "FAILED";
export type LatLng = [number, number];

export interface Kpis {
  pit_expansion_ha: number;
  pit_expansion_pct: number | null;
  overburden_change_ha: number;
  vegetation_change_ha: number;
  vegetation_lost_to_mining_ha: number;
  new_stockpiles_detected: number;
  mean_confidence_pct: number;
  evidence_reliability_grade: "HIGH" | "MEDIUM" | "LOW";
  risk_flag_count: number;
}

export interface RiskFlag {
  code: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  message: string;
  value: number;
  unit: string;
}

export interface Scene {
  scene_id: string;
  acquired: string;
  platform: string;
  catalog: string;
  aoi_cloud_pct: number;
  requested_date: string;
  mgrs_tile: string;
}

export interface ClassChange {
  class_id: number;
  baseline_ha: number;
  target_ha: number;
  change_ha: number;
  change_pct: number | null;
}

export interface Artifact {
  sha256: string;
  bytes: number;
  content_type: string;
}

export type RoleLayer = { baseline?: string; target?: string };

export interface JobResult {
  site_name: string;
  kpis: Kpis;
  risk_flags: RiskFlag[];
  risk_metrics: Record<string, number>;
  change_detection: {
    per_class: Record<string, ClassChange>;
    comparable_area_ha: number;
    vegetation_lost_to_mining_ha: number;
  };
  land_cover_area_ha: Record<"baseline" | "target", Record<string, number>>;
  scenes: { baseline?: Scene; target: Scene };
  image_bounds_wgs84: [LatLng, LatLng];
  image_corners_wgs84?: { top_left: LatLng; top_right: LatLng; bottom_left: LatLng; bottom_right: LatLng } | null;
  class_legend: Record<string, { name: string; rgb: [number, number, number] }>;
  validation: {
    grade: string;
    reasons: string[];
    per_date: Record<string, { mean_confidence: number; low_confidence_pct: number; cloud_free_aoi_pct: number }>;
    qa_checks: { coregistration: { shift_m: number; shift_px: number; pass: boolean }; comparable_area_pct: number };
  };
  hyperspectral: {
    data_source: string;
    composition: Record<string, { area_ha: number; pct_of_tagged: number }>;
    tagged_pct: number;
    pixels_analysed: number;
  };
  model: { model: string; training_strategy: string; pseudo_label_holdout_agreement: number };
  pipeline_runtime_s: number;
  evidence: { package_sha256: string; package_file_sha256: string; report_sha256: string };
  report_pages?: number | null;
  layers: {
    rgb?: RoleLayer;
    false_color?: RoleLayer;
    ndvi?: RoleLayer;
    landcover?: RoleLayer;
    landcover_polygons?: RoleLayer;
    mineral_tags?: string;
    new_stockpiles?: string;
    low_confidence?: string;
    report_pdf?: string;
    evidence_json?: string;
  };
  artifacts: Record<string, Artifact>;
}

export interface Job {
  id: string;
  status: JobState;
  stage: string | null;
  error: string | null;
  is_demo: boolean;
  site_name: string;
  target_date: string;
  baseline_date: string | null;
  evidence_sha256: string | null;
  aoi_geojson: Polygon | null;
  aoi_area_ha: number | null;
  result: JobResult | null;
}

export interface JobSummary {
  id: string;
  status: JobState;
  stage: string | null;
  is_demo: boolean;
  site_name: string;
  target_date: string;
  baseline_date: string | null;
  created_at: string;
}

export interface VerifyReport {
  valid: boolean;
  checks: Record<string, boolean>;
  package_sha256: string;
  artifacts_checked?: number;
  artifacts_failed?: string[];
  matches_job_record: boolean;
}

export interface Health {
  status: "ok" | "degraded";
  services: Record<string, string>;
  demo_available: boolean;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detailMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { msg?: string; loc?: unknown[] }) => (d.msg ?? "").replace(/^Value error, /, ""))
      .filter(Boolean)
      .join("; ");
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store", ...init });
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, detailMessage(body, `${res.status} ${res.statusText}`));
  return body as T;
}

export const api = {
  health: () => request<Health>("/health"),
  demo: () => request<Job>("/demo"),
  jobs: () => request<JobSummary[]>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  verify: (id: string) => request<VerifyReport>(`/jobs/${id}/verify`),
  createJob: (payload: { aoi_geojson: Polygon; target_date: string; baseline_date: string | null; site_name: string }) =>
    request<Job>("/jobs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }),
};

export const artifactUrl = (jobId: string, name: string, download = false) =>
  `/api/jobs/${jobId}/artifacts/${encodeURIComponent(name)}${download ? "?download=true" : ""}`;

const geojsonCache = new Map<string, Promise<FeatureCollection>>();

export function fetchGeoJSON(jobId: string, name: string): Promise<FeatureCollection> {
  const key = `${jobId}/${name}`;
  let hit = geojsonCache.get(key);
  if (!hit) {
    hit = fetch(artifactUrl(jobId, name)).then((r) => {
      if (!r.ok) throw new ApiError(r.status, `could not load ${name}`);
      return r.json() as Promise<FeatureCollection>;
    });
    hit.catch(() => geojsonCache.delete(key));
    geojsonCache.set(key, hit);
  }
  return hit;
}
