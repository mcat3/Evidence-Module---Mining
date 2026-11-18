"""Stage 5: tamper-evident evidence packaging (SHA-256 over canonical JSON + artifact manifest)."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "terraproof.evidence/1.0"
CANONICALIZATION = "JSON, UTF-8, keys sorted, separators (',', ':'), NaN/Inf -> null"

PUBLISHED_ARTIFACTS = (
    "baseline_rgb.png", "target_rgb.png", "baseline_false_color.png", "target_false_color.png",
    "baseline_ndvi.png", "target_ndvi.png", "baseline_landcover.png", "target_landcover.png",
    "baseline_landcover.geojson", "target_landcover.geojson", "new_stockpiles.geojson",
    "target_mineral_tags.geojson", "target_low_confidence.geojson",
    "baseline_rgb.tif", "target_rgb.tif", "baseline_false_color.tif", "target_false_color.tif",
    "baseline_landcover.tif", "target_landcover.tif", "baseline_confidence.tif", "target_confidence.tif",
    "target_mineral_tags.tif", "baseline_indices.tif", "target_indices.tif",
    "hyperspectral_signatures.png", "mineral_reference_library.json", "ingestion_metadata.json",
    "pipeline_summary.json",
)
EMBEDDED_LAYERS = {"new_stockpiles": "new_stockpiles.geojson", "mineral_tags": "target_mineral_tags.geojson"}
PACKAGE_NAME = "evidence_package.json"
REPORT_NAME = "evidence_report.pdf"


def _sanitize(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def canonical_bytes(obj) -> bytes:
    return json.dumps(_sanitize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_json(obj) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def artifact_manifest(out_dir: Path, names=PUBLISHED_ARTIFACTS) -> dict:
    return {name: {"sha256": sha256_file(out_dir / name), "bytes": (out_dir / name).stat().st_size}
            for name in names if (out_dir / name).exists()}


def _input_block(summary: dict, ingestion: dict) -> dict:
    return {
        "aoi_geojson": summary["inputs"]["aoi_geojson"],
        "aoi_area_ha": summary["aoi_area_ha"],
        "target_date": summary["inputs"]["target_date"],
        "baseline_date": summary["inputs"]["baseline_date"],
        "satellite_scenes": summary["scenes"],
        "search_parameters": ingestion.get("search_parameters"),
        "processing_grid": {"crs": summary["crs"], "resolution_m": summary["resolution_m"],
                            "shape": ingestion.get("grid_shape"), "transform": ingestion.get("grid_transform")},
    }


def _output_block(summary: dict, out_dir: Path) -> dict:
    hyperspectral = {k: v for k, v in summary["hyperspectral"].items() if k != "files"}
    return {
        "kpis": summary["kpis"],
        "land_cover_area_ha": summary["land_cover_area_ha"],
        "change_detection": summary["change_detection"],
        "risk_flags": summary["risk_flags"],
        "risk_metrics": summary["risk_metrics"],
        "hyperspectral_mineral_tags": hyperspectral,
        "validation_audit": summary["validation"],
        "model": summary["model"],
        "class_legend": summary["class_legend"],
        "spectral_index_stats": summary["spectral_index_stats"],
        "geojson_layers": {k: json.loads((out_dir / f).read_text()) for k, f in EMBEDDED_LAYERS.items()
                           if (out_dir / f).exists()},
    }


def build_evidence_package(summary: dict, out_dir: str | Path, *, job_id: str | None = None,
                           artifact_names=PUBLISHED_ARTIFACTS) -> dict:
    out_dir = Path(out_dir)
    ingestion = json.loads((out_dir / "ingestion_metadata.json").read_text())
    inputs = _input_block(summary, ingestion)
    outputs = _output_block(summary, out_dir)
    manifest = artifact_manifest(out_dir, artifact_names)
    body = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "site_name": summary["site_name"],
        "pipeline_generated_at": summary["generated_at"],
        "packaged_at": datetime.now(timezone.utc).isoformat(),
        "image_bounds_wgs84": summary.get("image_bounds_wgs84"),
        "inputs": inputs,
        "outputs": outputs,
        "artifact_manifest": manifest,
    }
    body = _sanitize(body)
    package = {
        **body,
        "integrity": {
            "algorithm": "SHA-256",
            "canonicalization": CANONICALIZATION,
            "input_metadata_sha256": sha256_json(inputs),
            "output_metrics_sha256": sha256_json(outputs),
            "artifact_manifest_sha256": sha256_json(manifest),
            "package_sha256": sha256_json(body),
            "package_sha256_scope": "entire document except the 'integrity' object",
        },
    }
    (out_dir / PACKAGE_NAME).write_text(json.dumps(package, indent=2, ensure_ascii=False))
    return package


def verify_package(package: dict, artifact_dir: str | Path | None = None) -> dict:
    """Recompute every hash; optionally re-hash artifact files on disk against the manifest."""
    pkg = copy.deepcopy(package)
    integrity = pkg.pop("integrity", None) or {}
    checks = {
        "package_sha256": sha256_json(pkg) == integrity.get("package_sha256"),
        "input_metadata_sha256": sha256_json(pkg.get("inputs")) == integrity.get("input_metadata_sha256"),
        "output_metrics_sha256": sha256_json(pkg.get("outputs")) == integrity.get("output_metrics_sha256"),
        "artifact_manifest_sha256": sha256_json(pkg.get("artifact_manifest")) == integrity.get("artifact_manifest_sha256"),
    }
    artifacts = {}
    if artifact_dir is not None:
        for name, entry in (pkg.get("artifact_manifest") or {}).items():
            path = Path(artifact_dir) / name
            artifacts[name] = path.exists() and sha256_file(path) == entry["sha256"]
    return {
        "valid": all(checks.values()) and all(artifacts.values()),
        "package_sha256": integrity.get("package_sha256"),
        "recomputed_package_sha256": sha256_json(pkg),
        "checks": checks,
        "artifacts_checked": len(artifacts),
        "artifacts_failed": [n for n, ok in artifacts.items() if not ok],
    }
