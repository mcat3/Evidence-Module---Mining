"use client";

import { useState } from "react";

import { api, artifactUrl, type Job, type VerifyReport } from "@/lib/api";
import { bytes, shortHash } from "@/lib/format";

const CHECK_LABELS: Record<string, string> = {
  input_metadata_sha256: "Input satellite metadata",
  output_metrics_sha256: "Output spatial metrics",
  artifact_manifest_sha256: "Artifact manifest",
  package_sha256: "Whole evidence package",
};

type State =
  | { kind: "idle" }
  | { kind: "running" }
  | { kind: "done"; report: VerifyReport; at: Date }
  | { kind: "error"; message: string };

function CopyHash({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button type="button" className="hash" title={`${hash}\n(click to copy)`}
      onClick={() => navigator.clipboard?.writeText(hash).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      })}>
      <span className="mono">{shortHash(hash, 16)}</span>
      <span className="hash-copy">{copied ? "copied" : "copy"}</span>
    </button>
  );
}

export default function IntegrityPanel({ job }: { job: Job }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const result = job.result!;
  const pdfName = result.layers.report_pdf ?? "evidence_report.pdf";
  const jsonName = result.layers.evidence_json ?? "evidence_package.json";
  const pdf = result.artifacts[pdfName];
  const json = result.artifacts[jsonName];

  const verify = async () => {
    setState({ kind: "running" });
    try {
      setState({ kind: "done", report: await api.verify(job.id), at: new Date() });
    } catch (e) {
      setState({ kind: "error", message: (e as Error).message });
    }
  };

  const report = state.kind === "done" ? state.report : null;
  const checked = report?.artifacts_checked ?? 0;
  const failed = report?.artifacts_failed?.length ?? 0;

  return (
    <div className="integrity">
      <div className="hash-row">
        <span className="hash-label">Evidence package SHA-256</span>
        <CopyHash hash={result.evidence.package_sha256} />
      </div>

      <button type="button" className="btn btn-verify" onClick={verify} disabled={state.kind === "running"}>
        {state.kind === "running" ? (
          <><span className="spinner" aria-hidden /> Re-hashing files from object storage…</>
        ) : (
          <>
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden>
              <path d="M8 1.5 2.5 3.5v4c0 3.4 2.3 5.9 5.5 7 3.2-1.1 5.5-3.6 5.5-7v-4L8 1.5Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
              <path d="m5.5 8 1.8 1.8L10.8 6" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Verify Cryptographic Integrity
          </>
        )}
      </button>

      <div aria-live="polite">
        {report && report.valid && (
          <div className="verify-badge ok">
            <span className="status-icon good" aria-hidden>✓</span>
            <div>
              <strong>SHA-256 Verified ({checked - failed}/{checked} Files Intact)</strong>
              <span>Package hash matches the job record · checked {state.kind === "done" && state.at.toLocaleTimeString()}</span>
            </div>
          </div>
        )}
        {report && !report.valid && (
          <div className="verify-badge bad">
            <span className="status-icon critical" aria-hidden>✕</span>
            <div>
              <strong>Integrity check FAILED ({checked - failed}/{checked} files intact)</strong>
              <span>
                {failed ? `Altered: ${report.artifacts_failed!.join(", ")}. ` : ""}
                {Object.entries(report.checks).filter(([, ok]) => !ok).map(([k]) => CHECK_LABELS[k] ?? k).join(", ")}
                {!report.matches_job_record && " · package hash differs from the job record"}
              </span>
            </div>
          </div>
        )}
        {state.kind === "error" && (
          <div className="verify-badge bad">
            <span className="status-icon critical" aria-hidden>✕</span>
            <div><strong>Verification could not run</strong><span>{state.message}</span></div>
          </div>
        )}
        {report && (
          <ul className="check-list">
            {Object.entries(CHECK_LABELS).map(([key, label]) => (
              <li key={key} className={report.checks[key] ? "ok" : "bad"}>
                <span aria-hidden>{report.checks[key] ? "✓" : "✕"}</span> {label}
              </li>
            ))}
            <li className={failed ? "bad" : "ok"}>
              <span aria-hidden>{failed ? "✕" : "✓"}</span> {checked} artifact files re-hashed from MinIO
            </li>
          </ul>
        )}
      </div>

      <div className="downloads">
        {pdf && (
          <a className="download" href={artifactUrl(job.id, pdfName, true)} download>
            <span className="dl-icon pdf" aria-hidden>PDF</span>
            <span className="dl-text">
              <strong>{result.report_pages ? `${result.report_pages}-Page ` : ""}PDF Audit Dossier</strong>
              <small>{bytes(pdf.bytes)} · SHA-256 {pdf.sha256.slice(0, 10)}…</small>
            </span>
            <span className="dl-arrow" aria-hidden>↓</span>
          </a>
        )}
        {json && (
          <a className="download" href={artifactUrl(job.id, jsonName, true)} download>
            <span className="dl-icon json" aria-hidden>{"{ }"}</span>
            <span className="dl-text">
              <strong>Evidence JSON</strong>
              <small>{bytes(json.bytes)} · SHA-256 {json.sha256.slice(0, 10)}…</small>
            </span>
            <span className="dl-arrow" aria-hidden>↓</span>
          </a>
        )}
      </div>
    </div>
  );
}
