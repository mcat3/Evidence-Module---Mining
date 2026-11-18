"""Shape a finished pipeline run into the JSON stored on the job row and served to the dashboard."""
from __future__ import annotations

import re
from pathlib import Path

from backend.app import storage
from backend.services.evidence_builder import PACKAGE_NAME, REPORT_NAME, sha256_file

LAYER_FILES = {
    "rgb": "{role}_rgb.png",
    "false_color": "{role}_false_color.png",
    "ndvi": "{role}_ndvi.png",
    "landcover": "{role}_landcover.png",
    "landcover_polygons": "{role}_landcover.geojson",
    "rgb_cog": "{role}_rgb.tif",
    "landcover_cog": "{role}_landcover.tif",
}
SINGLE_LAYERS = {
    "mineral_tags": "target_mineral_tags.geojson",
    "new_stockpiles": "new_stockpiles.geojson",
    "low_confidence": "target_low_confidence.geojson",
    "confidence_cog": "target_confidence.tif",
    "mineral_cog": "target_mineral_tags.tif",
    "signature_plot": "hyperspectral_signatures.png",
    "report_pdf": REPORT_NAME,
    "evidence_json": PACKAGE_NAME,
}


def publish_artifacts(job_id, artifact_dir: Path, names) -> dict:
    manifest = {}
    for name in names:
        path = artifact_dir / name
        if path.exists():
            manifest[name] = {"key": storage.upload_file(job_id, path, name), "sha256": sha256_file(path),
                              "bytes": path.stat().st_size, "content_type": storage.content_type(name)}
    return manifest


def image_corners_wgs84(raster_path: Path) -> dict | None:
    """Exact WGS84 positions of the raster grid's corners.

    The PNG overlays are rendered on a UTM grid, which is rotated relative to lon/lat (meridian convergence), so the
    dashboard places them with an affine transform through these corners instead of stretching them over a bbox.
    """
    if not raster_path.exists():
        return None
    import rasterio
    from pyproj import Transformer

    with rasterio.open(raster_path) as src:
        to_wgs = Transformer.from_crs(src.crs, 4326, always_xy=True)
        corners = {"top_left": (0, 0), "top_right": (src.width, 0), "bottom_left": (0, src.height),
                   "bottom_right": (src.width, src.height)}
        out = {}
        for key, (col, row) in corners.items():
            lon, lat = to_wgs.transform(*(src.transform * (col, row)))
            out[key] = [round(lat, 7), round(lon, 7)]
    return out


def pdf_page_count(pdf_path: Path) -> int | None:
    """Page count of a ReportLab PDF (its page dictionaries are written uncompressed)."""
    if not pdf_path.exists():
        return None
    return len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", pdf_path.read_bytes())) or None


def build_job_result(summary: dict, evidence: dict, artifacts: dict, artifact_dir: Path | None = None) -> dict:
    layers = {}
    for layer, pattern in LAYER_FILES.items():
        per_role = {role: pattern.format(role=role) for role in ("baseline", "target")
                    if pattern.format(role=role) in artifacts}
        if per_role:
            layers[layer] = per_role
    layers.update({k: v for k, v in SINGLE_LAYERS.items() if v in artifacts})
    validation = summary["validation"]
    return {
        "site_name": summary["site_name"],
        "kpis": summary["kpis"],
        "risk_flags": summary["risk_flags"],
        "risk_metrics": summary["risk_metrics"],
        "change_detection": summary["change_detection"],
        "land_cover_area_ha": summary["land_cover_area_ha"],
        "scenes": summary["scenes"],
        "image_bounds_wgs84": summary["image_bounds_wgs84"],
        "image_corners_wgs84": image_corners_wgs84(artifact_dir / "target_rgb.tif") if artifact_dir else None,
        "class_legend": summary["class_legend"],
        "validation": {"grade": validation["evidence_reliability_grade"], "reasons": validation["grade_reasons"],
                       "per_date": validation["per_date"], "qa_checks": validation["qa_checks"]},
        "hyperspectral": {k: summary["hyperspectral"][k] for k in
                          ("data_source", "composition", "tagged_pct", "pixels_analysed", "angle_threshold_rad")},
        "model": {k: summary["model"][k] for k in ("model", "training_strategy", "pseudo_label_holdout_agreement")},
        "pipeline_runtime_s": summary["runtime_s"],
        "evidence": {k: evidence[k] for k in ("package_sha256", "package_file_sha256", "report_sha256")},
        "report_pages": pdf_page_count(artifact_dir / REPORT_NAME) if artifact_dir else None,
        "layers": layers,
        "artifacts": {name: {k: v for k, v in meta.items() if k != "key"} for name, meta in artifacts.items()},
    }
