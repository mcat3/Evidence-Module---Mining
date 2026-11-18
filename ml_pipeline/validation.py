"""Stage 4: confidence audit, QA checks, reliability grading and ground-truth scoring."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

from .models import CLASS_NAMES, NODATA

LOW_CONFIDENCE_THRESHOLD = 0.70


def confidence_audit(confidence: np.ndarray, valid: np.ndarray, threshold: float = LOW_CONFIDENCE_THRESHOLD) -> dict:
    c = confidence[valid]
    return {
        "mean_confidence": round(float(c.mean()), 4),
        "median_confidence": round(float(np.median(c)), 4),
        "p10_confidence": round(float(np.percentile(c, 10)), 4),
        "low_confidence_threshold": threshold,
        "low_confidence_pct": round(float(100 * (c < threshold).mean()), 2),
    }


def coregistration_offset(a: np.ndarray, b: np.ndarray, valid: np.ndarray) -> tuple[float, float]:
    """Sub-pixel (row, col) shift of b relative to a via FFT phase correlation."""
    def prep(x):
        x = np.where(valid, x, np.nanmean(x[valid]))
        x = x - x.mean()
        return x * np.outer(np.hanning(x.shape[0]), np.hanning(x.shape[1]))

    fa, fb = np.fft.fft2(prep(a)), np.fft.fft2(prep(b))
    cross = fa * np.conj(fb)
    corr = np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-12)).real
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    shift = []
    for axis, p in enumerate(peak):
        n = corr.shape[axis]
        prev_idx, next_idx = list(peak), list(peak)
        prev_idx[axis], next_idx[axis] = (p - 1) % n, (p + 1) % n
        y0, y1, y2 = corr[tuple(prev_idx)], corr[peak], corr[tuple(next_idx)]
        denom = y0 - 2 * y1 + y2
        sub = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
        s = p + sub
        shift.append(s - n if s > n / 2 else s)
    return float(shift[0]), float(shift[1])


def reliability_grade(cloud_free_pcts: list[float], mean_confidence: float, low_conf_pct: float,
                      shift_px: float | None) -> tuple[str, list[str]]:
    reasons, score = [], 0
    worst_clear = min(cloud_free_pcts)
    if worst_clear >= 90:
        score += 2
    elif worst_clear >= 70:
        score += 1
    else:
        reasons.append(f"cloud-free AOI only {worst_clear:.1f}%")
    if mean_confidence >= 0.85 and low_conf_pct <= 15:
        score += 2
    elif mean_confidence >= 0.70:
        score += 1
        reasons.append(f"mean classifier confidence {mean_confidence:.2f}, {low_conf_pct:.1f}% pixels low-confidence")
    else:
        reasons.append(f"mean classifier confidence only {mean_confidence:.2f}")
    if shift_px is None or shift_px <= 0.5:
        score += 2
    elif shift_px <= 1.0:
        score += 1
        reasons.append(f"co-registration offset {shift_px:.2f} px")
    else:
        reasons.append(f"co-registration offset {shift_px:.2f} px exceeds 1 px")
    grade = "HIGH" if score >= 6 else "MEDIUM" if score >= 4 else "LOW"
    return grade, reasons


def run_validation(scenes: dict, classification: dict) -> tuple[dict, dict[str, np.ndarray]]:
    target = scenes["target"]
    audit = {"per_date": {}, "qa_checks": {}}
    low_conf_masks = {}
    for label, scene in scenes.items():
        conf = classification[label]["confidence"]
        audit["per_date"][label] = {
            "cloud_free_aoi_pct": round(float(100 * scene.valid.sum() / scene.aoi_mask.sum()), 2),
            **confidence_audit(conf, scene.valid),
        }
        low_conf_masks[label] = scene.valid & (conf < LOW_CONFIDENCE_THRESHOLD)

    shift_px = None
    if "baseline" in scenes:
        both = target.valid & scenes["baseline"].valid
        dy, dx = coregistration_offset(scenes["baseline"].bands["nir"], target.bands["nir"], both)
        shift_px = float(np.hypot(dy, dx))
        audit["qa_checks"]["coregistration"] = {
            "method": "FFT phase correlation on NIR (B08)", "shift_rows_px": round(dy, 3), "shift_cols_px": round(dx, 3),
            "shift_px": round(shift_px, 3), "shift_m": round(shift_px * target.resolution, 2),
            "pass": shift_px <= 1.0,
        }
        audit["qa_checks"]["comparable_area_pct"] = round(float(100 * both.sum() / target.aoi_mask.sum()), 2)

    t = audit["per_date"]["target"]
    grade, reasons = reliability_grade([d["cloud_free_aoi_pct"] for d in audit["per_date"].values()],
                                       t["mean_confidence"], t["low_confidence_pct"], shift_px)
    audit["evidence_reliability_grade"] = grade
    audit["grade_reasons"] = reasons or ["all QA checks passed"]
    return audit, low_conf_masks


def score_against_ground_truth(class_map: np.ndarray, transform, crs: str, ground_truth: dict | str | Path, *,
                               class_property: str = "class_id") -> dict:
    """Confusion matrix, per-class IoU/precision/recall and kappa against ground-truth GeoJSON polygons (WGS84).

    Each feature needs `class_property` set to a class id (0-4) or a class name from CLASS_NAMES.
    """
    if not isinstance(ground_truth, dict):
        ground_truth = json.loads(Path(ground_truth).read_text())
    name_to_id = {v.lower(): k for k, v in CLASS_NAMES.items()}
    to_raster = Transformer.from_crs(4326, crs, always_xy=True).transform

    geoms = []
    for feat in ground_truth.get("features", []):
        raw = feat.get("properties", {}).get(class_property)
        cls = int(raw) if str(raw).strip().lstrip("-").isdigit() else name_to_id.get(str(raw).strip().lower())
        if cls not in CLASS_NAMES:
            raise ValueError(f"Ground-truth feature has unknown class {raw!r} in property '{class_property}'")
        geoms.append((mapping(shp_transform(to_raster, shape(feat["geometry"]))), cls))
    if not geoms:
        raise ValueError("Ground-truth GeoJSON contains no features")

    truth = rasterize(geoms, out_shape=class_map.shape, transform=transform, fill=NODATA, dtype="uint8")
    sel = (truth != NODATA) & (class_map != NODATA)
    if not sel.any():
        raise ValueError("Ground-truth polygons do not overlap the classified area")
    k = len(CLASS_NAMES)
    cm = np.bincount(truth[sel].astype(np.int64) * k + class_map[sel], minlength=k * k).reshape(k, k)

    per_class = {}
    for c, name in CLASS_NAMES.items():
        tp, fn, fp = cm[c, c], cm[c].sum() - cm[c, c], cm[:, c].sum() - cm[c, c]
        if cm[c].sum() == 0 and cm[:, c].sum() == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[name] = {
            "iou": round(float(tp / (tp + fp + fn)), 4) if tp + fp + fn else 0.0,
            "precision": round(float(precision), 4), "recall": round(float(recall), 4),
            "f1": round(float(2 * precision * recall / (precision + recall)), 4) if precision + recall else 0.0,
            "truth_pixels": int(cm[c].sum()),
        }
    total = cm.sum()
    oa = np.trace(cm) / total
    pe = (cm.sum(axis=0) * cm.sum(axis=1)).sum() / total ** 2
    present = [CLASS_NAMES[c] for c in CLASS_NAMES if cm[c].sum() > 0]
    return {
        "evaluated_pixels": int(total),
        "overall_accuracy": round(float(oa), 4),
        "cohens_kappa": round(float((oa - pe) / (1 - pe)), 4) if pe < 1 else 1.0,
        "mean_iou": round(float(np.mean([per_class[n]["iou"] for n in present])), 4),
        "per_class": per_class,
        "confusion_matrix": {"rows_truth_cols_predicted": [CLASS_NAMES[c] for c in CLASS_NAMES], "values": cm.tolist()},
    }
