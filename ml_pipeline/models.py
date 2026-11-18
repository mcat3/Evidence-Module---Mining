"""Stage 3: Random Forest land-cover classification, change detection and risk pattern extraction."""
from __future__ import annotations

from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pyproj import Transformer
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

from .ingestion import BANDS, Scene

NODATA = 255
CLASS_NAMES = {
    0: "Undisturbed Vegetation",
    1: "Active Mine Pit / Excavation",
    2: "Overburden / Mineral Stockpile",
    3: "Water / Tailings Pond",
    4: "Haul Roads / Built Infrastructure",
}
CLASS_COLORS = {0: (46, 139, 87), 1: (35, 35, 35), 2: (210, 160, 90), 3: (30, 120, 220), 4: (220, 40, 60)}
FEATURE_NAMES = BANDS + ("ndvi", "ndwi", "iron_swir_nir", "iron_red_blue", "brightness",
                          "ndvi_context_150m", "brightness_context_150m", "distance_to_coal_m")

# Rules used only to bootstrap training labels. Thresholds were set from sampled Sentinel-2 reflectance
# over Gevra: coal is dark and spectrally flat, overburden bright and neutral, haul roads dark with high
# SWIR/NIR. Spectra alone cannot separate coal benches from coal-dusted roads, or overburden dumps from
# dry bare fields, so strip width, bare-patch size and distance to exposed coal decide those cases.
# Dry-season fallow/agricultural land is non-mining land and is folded into class 0.
PSEUDO_LABEL_RULES = {
    "water": "(ndwi > 0.10 & swir1 < 0.06) | (swir1 < 0.035 & nir < 0.05)",
    "pit": "dark non-vegetated (ndvi < 0.18, brightness < 0.10) region wider than 50 m",
    "haul_roads": "dark non-vegetated (ndvi < 0.18, brightness < 0.13) strip narrower than 50 m & swir1/nir >= 1.4",
    "overburden": "bare (ndvi < 0.12 & brightness >= 0.15) & swir1/nir < 1.8 & "
                  "(distance_to_coal <= 300 m | (bare patch >= 20 ha & distance_to_coal <= 1500 m))",
    "vegetation": "ndvi > 0.45 | (0.18 <= ndvi <= 0.45 & nir >= 0.13 & brightness < 0.20 & distance_to_coal > 300 m)"
                  " | (bare & (distance_to_coal > 1500 m | (bare patch < 5 ha & distance_to_coal > 500 m)))",
}
CONTEXT_WINDOW_PX = 15
NO_COAL_DISTANCE_M = 100_000.0


def _masked_mean(x: np.ndarray, size: int) -> np.ndarray:
    finite = np.isfinite(x)
    total = ndimage.uniform_filter(np.where(finite, x, 0.0), size=size, mode="nearest")
    count = ndimage.uniform_filter(finite.astype(np.float64), size=size, mode="nearest")
    return np.where(count > 0, total / np.maximum(count, 1e-9), np.nan)


def distance_to_coal(bands: dict[str, np.ndarray], ndvi: np.ndarray, resolution: float) -> np.ndarray:
    brightness = np.mean([bands[b] for b in BANDS], axis=0)
    coal_like = (brightness < 0.10) & (ndvi < 0.15) & (bands["swir1"] >= 0.035)
    coal_body = ndimage.binary_opening(coal_like, structure=np.ones((5, 5)))
    if not coal_body.any():
        return np.full(ndvi.shape, NO_COAL_DISTANCE_M, dtype=np.float32)
    return (ndimage.distance_transform_edt(~coal_body) * resolution).astype(np.float32)


def feature_stack(bands: dict[str, np.ndarray], indices: dict[str, np.ndarray], resolution: float = 10.0) -> np.ndarray:
    brightness = np.mean([bands[b] for b in BANDS], axis=0)
    ndvi = indices["ndvi"]
    layers = [bands[b] for b in BANDS] + [indices[k] for k in ("ndvi", "ndwi", "iron_swir_nir", "iron_red_blue")]
    layers += [brightness, _masked_mean(ndvi, CONTEXT_WINDOW_PX), _masked_mean(brightness, CONTEXT_WINDOW_PX),
               distance_to_coal(bands, ndvi, resolution)]
    return np.stack(layers, axis=-1).astype(np.float32)


def _component_area_ha(mask: np.ndarray, pixel_ha: float) -> np.ndarray:
    comps, _ = ndimage.label(mask, structure=np.ones((3, 3)))
    sizes = np.bincount(comps.ravel()) * pixel_ha
    sizes[0] = 0
    return sizes[comps]


def pseudo_labels(stack: np.ndarray, valid: np.ndarray, pixel_ha: float = 0.01) -> np.ndarray:
    f = {name: stack[..., i] for i, name in enumerate(FEATURE_NAMES)}
    ndvi, ndwi, nir, swir1 = f["ndvi"], f["ndwi"], f["nir"], f["swir1"]
    bright, sn, dist = f["brightness"], f["iron_swir_nir"], f["distance_to_coal_m"]

    water = ((ndwi > 0.10) & (swir1 < 0.06)) | ((swir1 < 0.035) & (nir < 0.05))
    dark = (ndvi < 0.18) & (bright < 0.13) & (swir1 >= 0.035) & valid & ~water
    wide = ndimage.binary_opening(dark, structure=np.ones((5, 5)))
    bare = (ndvi < 0.12) & (bright >= 0.15) & valid
    bare_ha = _component_area_ha(bare, pixel_ha)
    rules = [
        (3, water),
        (1, wide & (bright < 0.10)),
        (4, dark & ~wide & (sn >= 1.4)),
        (2, bare & (sn < 1.8) & ((dist <= 300) | ((bare_ha >= 20) & (dist <= 1500)))),
        (0, (ndvi > 0.45) | ((ndvi >= 0.18) & (ndvi <= 0.45) & (nir >= 0.13) & (bright < 0.20) & (dist > 300))
            | (bare & ((dist > 1500) | ((bare_ha < 5) & (dist > 500))))),
    ]
    labels = np.full(valid.shape, -1, dtype=np.int8)
    for cls, rule in rules:
        labels[(labels == -1) & rule & valid] = cls
    return labels


def train_classifier(stacks: list[np.ndarray], valids: list[np.ndarray], *, pixel_ha: float = 0.01,
                     per_class: int = 5000, seed: int = 42) -> tuple[RandomForestClassifier, dict]:
    rng = np.random.default_rng(seed)
    X_parts, y_parts = [], []
    for stack, valid in zip(stacks, valids):
        labels = pseudo_labels(stack, valid, pixel_ha)
        X_parts.append(stack[labels >= 0])
        y_parts.append(labels[labels >= 0])
    X_all, y_all = np.concatenate(X_parts), np.concatenate(y_parts)

    keep, counts = [], {}
    for cls in CLASS_NAMES:
        idx = np.flatnonzero(y_all == cls)
        counts[CLASS_NAMES[cls]] = int(idx.size)
        if idx.size:
            keep.append(rng.choice(idx, size=min(per_class, idx.size), replace=False))
    keep = np.concatenate(keep)
    X, y = X_all[keep], y_all[keep]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)
    clf = RandomForestClassifier(n_estimators=200, max_depth=18, min_samples_leaf=2, class_weight="balanced",
                                 n_jobs=-1, random_state=seed)
    clf.fit(X_train, y_train)
    info = {
        "model": "RandomForestClassifier",
        "training_strategy": "bootstrapped from spectral rule-based pseudo-labels (both dates pooled)",
        "pseudo_label_rules": PSEUDO_LABEL_RULES,
        "features": list(FEATURE_NAMES),
        "pseudo_labelled_pixels_per_class": counts,
        "training_samples": int(len(y_train)),
        "holdout_samples": int(len(y_test)),
        "pseudo_label_holdout_agreement": round(float(clf.score(X_test, y_test)), 4),
        "feature_importance": {n: round(float(v), 4) for n, v in zip(FEATURE_NAMES, clf.feature_importances_)},
        "params": {"n_estimators": 200, "max_depth": 18, "min_samples_leaf": 2, "random_state": seed},
    }
    return clf, info


def classify(clf: RandomForestClassifier, stack: np.ndarray, valid: np.ndarray, chunk: int = 250_000):
    X = stack[valid]
    proba = np.zeros((X.shape[0], len(CLASS_NAMES)), dtype=np.float32)
    for start in range(0, X.shape[0], chunk):
        proba[start:start + chunk][:, clf.classes_] = clf.predict_proba(X[start:start + chunk])
    class_map = np.full(valid.shape, NODATA, dtype=np.uint8)
    confidence = np.full(valid.shape, np.nan, dtype=np.float32)
    class_map[valid] = proba.argmax(axis=1)
    confidence[valid] = proba.max(axis=1)
    return class_map, confidence


def class_area_stats(class_map: np.ndarray, mask: np.ndarray, pixel_ha: float) -> dict:
    return {CLASS_NAMES[c]: round(float(((class_map == c) & mask).sum() * pixel_ha), 2) for c in CLASS_NAMES}


def change_detection(base: np.ndarray, target: np.ndarray, both_valid: np.ndarray, pixel_ha: float) -> dict:
    per_class = {}
    for c, name in CLASS_NAMES.items():
        b = float(((base == c) & both_valid).sum() * pixel_ha)
        t = float(((target == c) & both_valid).sum() * pixel_ha)
        per_class[name] = {"class_id": c, "baseline_ha": round(b, 2), "target_ha": round(t, 2),
                           "change_ha": round(t - b, 2), "change_pct": round(100 * (t - b) / b, 2) if b > 0 else None}
    idx = base[both_valid].astype(np.int64) * len(CLASS_NAMES) + target[both_valid]
    matrix = np.bincount(idx, minlength=len(CLASS_NAMES) ** 2).reshape(len(CLASS_NAMES), -1) * pixel_ha
    return {
        "comparable_area_ha": round(float(both_valid.sum() * pixel_ha), 2),
        "per_class": per_class,
        "transition_matrix_ha": {"rows_baseline_cols_target": [CLASS_NAMES[c] for c in CLASS_NAMES],
                                 "values": np.round(matrix, 2).tolist()},
        "vegetation_lost_to_mining_ha": round(float(((base == 0) & np.isin(target, (1, 2)) & both_valid).sum() * pixel_ha), 2),
    }


def detect_risks(base: np.ndarray, target: np.ndarray, both_valid: np.ndarray, pixel_ha: float, resolution: float, *,
                 pit_expansion_pct: float = 10.0, water_buffer_m: float = 100.0, min_stockpile_ha: float = 1.0,
                 max_baseline_overlap: float = 0.2):
    flags = []
    change = change_detection(base, target, both_valid, pixel_ha)["per_class"]

    pit = change[CLASS_NAMES[1]]
    if pit["change_pct"] is not None and pit["change_pct"] > pit_expansion_pct:
        flags.append({"code": "PIT_EXPANSION", "severity": "HIGH" if pit["change_pct"] > 25 else "MEDIUM",
                      "value": pit["change_pct"], "unit": "%",
                      "message": f"Active pit area expanded by {pit['change_pct']:.1f}% (+{pit['change_ha']:.1f} ha), "
                                 f"above the {pit_expansion_pct:.0f}% threshold."})

    water_t = (target == 3) & both_valid
    near_water = ndimage.distance_transform_edt(~water_t) * resolution <= water_buffer_m
    veg_loss = (base == 0) & (target != 0) & both_valid
    veg_loss_near_water_ha = float((veg_loss & near_water).sum() * pixel_ha)
    if veg_loss_near_water_ha >= 1.0:
        flags.append({"code": "VEGETATION_LOSS_NEAR_WATER",
                      "severity": "HIGH" if veg_loss_near_water_ha >= 5 else "MEDIUM",
                      "value": round(veg_loss_near_water_ha, 2), "unit": "ha",
                      "message": f"{veg_loss_near_water_ha:.1f} ha of vegetation lost within {water_buffer_m:.0f} m "
                                 "of water / tailings ponds (runoff and contamination risk)."})

    components, n = ndimage.label((target == 2) & both_valid, structure=np.ones((3, 3)))
    sizes = np.bincount(components.ravel(), minlength=n + 1)
    overlap = np.bincount(components.ravel(), weights=(base == 2).ravel().astype(float), minlength=n + 1)
    new_ids = [i for i in range(1, n + 1)
               if sizes[i] * pixel_ha >= min_stockpile_ha and overlap[i] / sizes[i] < max_baseline_overlap]
    new_stockpiles = np.where(np.isin(components, new_ids), components, 0).astype(np.int32)
    if new_ids:
        total = float(sum(sizes[i] for i in new_ids) * pixel_ha)
        flags.append({"code": "NEW_STOCKPILE_FORMATION", "severity": "MEDIUM", "value": len(new_ids), "unit": "count",
                      "message": f"{len(new_ids)} new overburden/stockpile bodies (>= {min_stockpile_ha} ha each, "
                                 f"{total:.1f} ha total) absent in the baseline."})

    lost = change[CLASS_NAMES[0]]["change_ha"]
    if lost <= -5:
        flags.append({"code": "VEGETATION_LOSS", "severity": "HIGH" if lost <= -25 else "MEDIUM", "value": lost, "unit": "ha",
                      "message": f"Net undisturbed vegetation decreased by {abs(lost):.1f} ha."})

    metrics = {"veg_loss_near_water_ha": round(veg_loss_near_water_ha, 2), "new_stockpile_count": len(new_ids),
               "new_stockpile_ha": round(float(sum(sizes[i] for i in new_ids) * pixel_ha), 2)}
    return flags, new_stockpiles, metrics


def polygonize(labels: np.ndarray, transform, crs: str, *, mask: np.ndarray | None = None, min_area_ha: float = 0.5,
               simplify_m: float = 10.0, properties=None) -> dict:
    """Vectorize a label raster to a WGS84 GeoJSON FeatureCollection; `properties(value)` adds attributes."""
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True).transform
    data = labels.astype(np.int32)
    features = []
    for geom, value in shapes(data, mask=mask if mask is not None else data != NODATA, transform=transform,
                              connectivity=8):
        poly = shape(geom)
        area_ha = poly.area / 10_000
        if area_ha < min_area_ha:
            continue
        poly = poly.simplify(simplify_m, preserve_topology=True)
        props = {"area_ha": round(area_ha, 2)}
        props.update(properties(int(value)) if properties else {})
        features.append({"type": "Feature", "geometry": mapping(shp_transform(to_wgs, poly)), "properties": props})
    return {"type": "FeatureCollection", "features": features}


def class_polygons(class_map: np.ndarray, transform, crs: str, min_area_ha: float = 0.5) -> dict:
    return polygonize(class_map, transform, crs, min_area_ha=min_area_ha,
                      properties=lambda v: {"class_id": v, "class_name": CLASS_NAMES[v]})


def colorize(class_map: np.ndarray) -> np.ndarray:
    rgba = np.zeros(class_map.shape + (4,), dtype=np.uint8)
    for c, rgb in CLASS_COLORS.items():
        rgba[class_map == c] = (*rgb, 255)
    return rgba


def save_class_png(path: Path, class_map: np.ndarray) -> str:
    plt.imsave(path, colorize(class_map))
    return str(path)


def cog_colormap() -> dict:
    cmap = {c: (*rgb, 255) for c, rgb in CLASS_COLORS.items()}
    cmap[NODATA] = (0, 0, 0, 0)
    return cmap


def save_model(clf: RandomForestClassifier, path: Path) -> str:
    joblib.dump(clf, path, compress=3)
    return str(path)


def run_classification(scenes: dict[str, Scene], indices: dict[str, dict], *, seed: int = 42):
    stacks = {label: feature_stack(s.bands, indices[label], s.resolution) for label, s in scenes.items()}
    any_scene = next(iter(scenes.values()))
    clf, info = train_classifier([stacks[k] for k in scenes], [scenes[k].valid for k in scenes],
                                 pixel_ha=any_scene.pixel_area_ha, seed=seed)
    results = {}
    for label, scene in scenes.items():
        class_map, confidence = classify(clf, stacks[label], scene.valid)
        results[label] = {"class_map": class_map, "confidence": confidence,
                          "area_ha": class_area_stats(class_map, scene.valid, scene.pixel_area_ha)}
    return clf, info, results
