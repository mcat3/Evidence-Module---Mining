import type { Job } from "@/lib/api";
import { fixed } from "@/lib/format";
import IntegrityPanel from "./IntegrityPanel";
import KpiGrid from "./KpiGrid";
import LandCoverChange from "./LandCoverChange";
import MineralChart from "./MineralChart";
import RiskAlerts from "./RiskAlerts";

function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h2>{title}</h2>
        {aside && <span className="panel-aside">{aside}</span>}
      </header>
      {children}
    </section>
  );
}

const acquired = (iso?: string) => (iso ? iso.slice(0, 10) : "n/a");

export default function JobReport({ job }: { job: Job }) {
  const r = job.result!;
  const { baseline, target } = r.scenes;
  const coreg = r.validation.qa_checks.coregistration;
  return (
    <div className="report">
      <div className="report-head">
        <div className="report-tags">
          <span className={`tag ${job.is_demo ? "tag-demo" : "tag-live"}`}>{job.is_demo ? "Pre-computed demo" : "Live analysis"}</span>
          <span className="tag">Sentinel-2 L2A · 10 m</span>
        </div>
        <h1>{job.site_name}</h1>
        <div className="scene-pair">
          <div>
            <span className="scene-role">Baseline</span>
            <span className="scene-date mono">{acquired(baseline?.acquired)}</span>
            <span className="scene-id mono" title={baseline?.scene_id}>{baseline?.scene_id ?? "none"}</span>
          </div>
          <span className="scene-arrow" aria-hidden>→</span>
          <div>
            <span className="scene-role">Target</span>
            <span className="scene-date mono">{acquired(target?.acquired)}</span>
            <span className="scene-id mono" title={target?.scene_id}>{target?.scene_id}</span>
          </div>
        </div>
        <div className="report-meta">
          AOI {fixed((job.aoi_area_ha ?? 0) / 100, 1)} km² · cloud {fixed(baseline?.aoi_cloud_pct ?? 0)}% / {fixed(target?.aoi_cloud_pct ?? 0)}%
          · runtime {fixed(r.pipeline_runtime_s, 0)} s
        </div>
      </div>

      <Section title="Key metrics" aside={`${r.kpis.evidence_reliability_grade} reliability`}>
        <KpiGrid result={r} />
      </Section>

      <Section title="Risk alerts" aside={`${r.risk_flags.length} flagged`}>
        <RiskAlerts flags={r.risk_flags} />
      </Section>

      <Section title="Evidence & integrity" aside="SHA-256">
        <IntegrityPanel key={job.id} job={job} />
      </Section>

      <Section title="Mineral breakdown" aside="SAM · 4 references">
        <MineralChart hs={r.hyperspectral} />
      </Section>

      <Section title="Land-cover change" aside={`${fixed(r.change_detection.comparable_area_ha, 0)} ha compared`}>
        <LandCoverChange result={r} />
      </Section>

      <Section title="Validation audit">
        <dl className="qa-list">
          <dt>Co-registration (FFT phase corr.)</dt>
          <dd className={coreg.pass ? "ok" : "bad"}>{coreg.pass ? "✓" : "✕"} {fixed(coreg.shift_px, 3)} px ({fixed(coreg.shift_m, 2)} m)</dd>
          <dt>Cloud-free AOI</dt>
          <dd>{Object.entries(r.validation.per_date).map(([k, v]) => `${k} ${fixed(v.cloud_free_aoi_pct)}%`).join(" · ")}</dd>
          <dt>Low-confidence pixels (&lt; 70%)</dt>
          <dd>{Object.entries(r.validation.per_date).map(([k, v]) => `${k} ${fixed(v.low_confidence_pct)}%`).join(" · ")}</dd>
          <dt>Classifier</dt>
          <dd>{r.model.model}, pseudo-label hold-out agreement {fixed(r.model.pseudo_label_holdout_agreement * 100)}%</dd>
        </dl>
        <p className="fineprint">
          Hold-out agreement measures consistency with the rule-based training labels, not accuracy against ground truth.
          Score against surveyed polygons with <code>scripts/score_ground_truth.py</code>.
        </p>
      </Section>
    </div>
  );
}
