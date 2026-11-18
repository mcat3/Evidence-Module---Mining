"""End-to-end orchestration of Stages 1-4 for one AOI and date pair."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy import ndimage

from . import hyperspectral, models, spectral, validation
from .ingestion import ingest

log = logging.getLogger(__name__)


def _write_geojson(path: Path, fc: dict) -> str:
    path.write_text(json.dumps(fc))
    return str(path)


def _relative_names(obj):
    """Artifact references as bare file names so summaries are portable and leak no local paths."""
    if isinstance(obj, dict):
        return {k: _relative_names(v) for k, v in obj.items()}
    return Path(obj).name if isinstance(obj, str) else obj


def _mining_components(class_map: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, dict[int, int]]:
    """Connected components of pit (1) and stockpile (2) pixels, with ids unique across both classes."""
    combined = np.zeros(class_map.shape, dtype=np.int32)
    id_to_class, offset = {}, 0
    for cls in (2, 1):
        comps, n = ndimage.label((class_map == cls) & valid, structure=np.ones((3, 3)))
        combined[comps > 0] = comps[comps > 0] + offset
        id_to_class.update({i + offset: cls for i in range(1, n + 1)})
        offset += n
    return combined, id_to_class


def _image_bounds_wgs84(transform, shape: tuple[int, int], crs: str) -> list[list[float]]:
    """[[south, west], [north, east]] of the raster grid, for map image overlays."""
    h, w = shape
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True)
    corners = [to_wgs.transform(*(transform * (c, r))) for c, r in ((0, 0), (w, 0), (0, h), (w, h))]
    lons, lats = zip(*corners)
    return [[round(min(lats), 7), round(min(lons), 7)], [round(max(lats), 7), round(max(lons), 7)]]


def run_pipeline(aoi_geojson: dict, target_date: str, baseline_date: str | None, out_dir: str | Path, *,
                 site_name: str = "Custom AOI", seed: int = 42, progress=None) -> dict:
    t0 = time.time()

    def stage(name: str) -> None:
        log.info(name)
        if progress:
            progress(name)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: dict = {}

    stage("Stage 1: ingestion")
    scenes, ingestion_meta = ingest(aoi_geojson, target_date, baseline_date, out)
    files["ingestion"] = {**ingestion_meta["outputs"], "metadata": str(out / "ingestion_metadata.json")}
    target = scenes["target"]
    pixel_ha, transform, crs = target.pixel_area_ha, target.transform, target.crs

    stage("Stage 2: spectral indices and composites")
    indices, files["spectral"] = spectral.process_spectral(scenes, out)
    index_stats = {label: spectral.index_summary(indices[label], s.valid) for label, s in scenes.items()}

    stage("Stage 3: Random Forest classification")
    clf, model_info, classification = models.run_classification(scenes, indices, seed=seed)
    files["model"] = models.save_model(clf, out / "landcover_rf.joblib")
    files["classification"] = {}
    for label, res in classification.items():
        files["classification"][label] = {
            "class_cog": spectral.write_cog(out / f"{label}_landcover.tif", res["class_map"], transform, crs,
                                            nodata=models.NODATA, colormap=models.cog_colormap(), categorical=True,
                                            descriptions=["Land cover class (0-4)"]),
            "confidence_cog": spectral.write_cog(out / f"{label}_confidence.tif", res["confidence"], transform, crs,
                                                 nodata=np.nan, descriptions=["RF max class probability"]),
            "class_png": models.save_class_png(out / f"{label}_landcover.png", res["class_map"]),
            "polygons_geojson": _write_geojson(out / f"{label}_landcover.geojson",
                                               models.class_polygons(res["class_map"], transform, crs)),
        }

    change, risk_flags, risk_metrics = None, [], {}
    new_stockpiles = np.zeros(target.valid.shape, dtype=np.int32)
    if "baseline" in scenes:
        stage("Stage 3: change detection and risk patterns")
        both = target.valid & scenes["baseline"].valid
        base_map, tgt_map = classification["baseline"]["class_map"], classification["target"]["class_map"]
        change = models.change_detection(base_map, tgt_map, both, pixel_ha)
        risk_flags, new_stockpiles, risk_metrics = models.detect_risks(base_map, tgt_map, both, pixel_ha, target.resolution)

    stage("Stage 3: SAM hyperspectral mineral tagging")
    tgt_map = classification["target"]["class_map"]
    mineral_map, mineral_summary = hyperspectral.tag_minerals(target, tgt_map, out, seed=seed)
    files["hyperspectral"] = {
        **mineral_summary["files"],
        "mineral_cog": spectral.write_cog(out / "target_mineral_tags.tif", mineral_map, transform, crs,
                                          nodata=hyperspectral.NODATA, categorical=True,
                                          descriptions=["SAM mineral tag: 0 unclassified, 1 coal, 2 hematite, "
                                                        "3 kaolinite, 4 sandstone/shale"]),
    }

    components, id_to_class = _mining_components(tgt_map, target.valid)
    tags = hyperspectral.stockpile_mineral_tags(components, mineral_map, pixel_ha, min_area_ha=1.0)
    files["hyperspectral"]["mineral_tags_geojson"] = _write_geojson(
        out / "target_mineral_tags.geojson",
        models.polygonize(components, transform, crs, mask=np.isin(components, list(tags)), min_area_ha=1.0,
                          properties=lambda v: {"component_id": v, "class_id": id_to_class[v],
                                                "class_name": models.CLASS_NAMES[id_to_class[v]], **tags[v]}))
    if "baseline" in scenes:
        stock_tags = hyperspectral.stockpile_mineral_tags(new_stockpiles, mineral_map, pixel_ha, min_area_ha=0.0)
        files["new_stockpiles_geojson"] = _write_geojson(
            out / "new_stockpiles.geojson",
            models.polygonize(new_stockpiles, transform, crs, mask=new_stockpiles > 0, min_area_ha=0.1,
                              properties=lambda v: {"stockpile_id": v, **stock_tags.get(v, {})}))

    stage("Stage 4: validation and uncertainty audit")
    audit, low_conf = validation.run_validation(scenes, classification)
    files["low_confidence_geojson"] = _write_geojson(
        out / "target_low_confidence.geojson",
        models.polygonize(low_conf["target"].astype(np.uint8), transform, crs, mask=low_conf["target"], min_area_ha=0.25,
                          properties=lambda v: {"flag": "Low Confidence", "threshold": validation.LOW_CONFIDENCE_THRESHOLD}))

    kpis = {"evidence_reliability_grade": audit["evidence_reliability_grade"],
            "mean_confidence_pct": round(100 * audit["per_date"]["target"]["mean_confidence"], 1)}
    if change:
        pc = change["per_class"]
        kpis.update({
            "pit_expansion_ha": pc[models.CLASS_NAMES[1]]["change_ha"],
            "pit_expansion_pct": pc[models.CLASS_NAMES[1]]["change_pct"],
            "overburden_change_ha": pc[models.CLASS_NAMES[2]]["change_ha"],
            "vegetation_change_ha": pc[models.CLASS_NAMES[0]]["change_ha"],
            "vegetation_lost_to_mining_ha": change["vegetation_lost_to_mining_ha"],
            "new_stockpiles_detected": risk_metrics["new_stockpile_count"],
            "risk_flag_count": len(risk_flags),
        })

    summary = {
        "site_name": site_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_s": round(time.time() - t0, 1),
        "inputs": {"aoi_geojson": ingestion_meta["aoi_geojson"], "target_date": target_date, "baseline_date": baseline_date},
        "aoi_area_ha": ingestion_meta["aoi_area_ha"],
        "crs": crs,
        "resolution_m": target.resolution,
        "image_bounds_wgs84": _image_bounds_wgs84(transform, target.valid.shape, crs),
        "scenes": ingestion_meta["scenes"],
        "kpis": kpis,
        "spectral_index_stats": index_stats,
        "model": model_info,
        "land_cover_area_ha": {label: res["area_ha"] for label, res in classification.items()},
        "change_detection": change,
        "risk_flags": risk_flags,
        "risk_metrics": risk_metrics,
        "hyperspectral": mineral_summary,
        "validation": audit,
        "class_legend": {str(k): {"name": v, "rgb": models.CLASS_COLORS[k]} for k, v in models.CLASS_NAMES.items()},
        "files": files,
    }
    summary["files"] = _relative_names(files)
    summary["hyperspectral"]["files"] = _relative_names(mineral_summary["files"])
    (out / "pipeline_summary.json").write_text(json.dumps(summary, indent=2))
    log.info("Pipeline finished in %.1fs", summary["runtime_s"])
    return summary
