"""Stage 1: Sentinel-2 L2A scene search, SCL cloud masking and AOI-aligned loading."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import odc.stac
import planetary_computer
import rasterio
from affine import Affine
from odc.geo.geobox import GeoBox
from pyproj import Transformer
from pystac_client import Client
from rasterio.features import geometry_mask
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

log = logging.getLogger(__name__)

BANDS = ("blue", "green", "red", "nir", "swir1", "swir2")
S2_BAND_IDS = {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08", "swir1": "B11", "swir2": "B12"}
# SCL: 0 no data, 1 saturated, 3 cloud shadow, 8/9 cloud medium/high probability, 10 thin cirrus
SCL_INVALID = (0, 1, 3, 8, 9, 10)

CATALOGS = {
    "earth-search": {
        "url": "https://earth-search.aws.element84.com/v1",
        "assets": {"blue": "blue", "green": "green", "red": "red", "nir": "nir",
                   "swir1": "swir16", "swir2": "swir22", "scl": "scl"},
    },
    "planetary-computer": {
        "url": "https://planetarycomputer.microsoft.com/api/stac/v1",
        "assets": {"blue": "B02", "green": "B03", "red": "B04", "nir": "B08",
                   "swir1": "B11", "swir2": "B12", "scl": "SCL"},
    },
}


@dataclass
class Scene:
    label: str
    bands: dict[str, np.ndarray]
    scl: np.ndarray
    valid: np.ndarray
    aoi_mask: np.ndarray
    transform: Affine
    crs: str
    metadata: dict = field(default_factory=dict)

    @property
    def resolution(self) -> float:
        return abs(self.transform.a)

    @property
    def pixel_area_ha(self) -> float:
        return abs(self.transform.a * self.transform.e) / 10_000


def utm_epsg(lon: float, lat: float) -> int:
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def aoi_from_point(lat: float, lon: float, half_size_km: float = 4.0) -> dict:
    """Square AOI polygon (GeoJSON, WGS84) centred on a point, sized in metres on the local UTM grid."""
    epsg = utm_epsg(lon, lat)
    to_utm = Transformer.from_crs(4326, epsg, always_xy=True)
    to_wgs = Transformer.from_crs(epsg, 4326, always_xy=True)
    x, y = to_utm.transform(lon, lat)
    d = half_size_km * 1000
    ring = [to_wgs.transform(x + dx, y + dy) for dx, dy in ((-d, -d), (d, -d), (d, d), (-d, d), (-d, -d))]
    return {"type": "Polygon", "coordinates": [[[round(px, 7), round(py, 7)] for px, py in ring]]}


def parse_aoi(aoi_geojson: dict):
    if aoi_geojson.get("type") == "FeatureCollection":
        aoi_geojson = aoi_geojson["features"][0]
    if aoi_geojson.get("type") == "Feature":
        aoi_geojson = aoi_geojson["geometry"]
    geom = shape(aoi_geojson)
    if geom.geom_type != "Polygon" or not geom.is_valid:
        raise ValueError("AOI must be a valid GeoJSON Polygon in WGS84")
    return geom


def build_grid(aoi, resolution: float = 10.0):
    """Snap the AOI to a pixel-aligned grid in its local UTM zone so every date shares one grid."""
    epsg = utm_epsg(aoi.centroid.x, aoi.centroid.y)
    aoi_utm = shp_transform(Transformer.from_crs(4326, epsg, always_xy=True).transform, aoi)
    minx, miny, maxx, maxy = aoi_utm.bounds
    minx, miny = np.floor(minx / resolution) * resolution, np.floor(miny / resolution) * resolution
    maxx, maxy = np.ceil(maxx / resolution) * resolution, np.ceil(maxy / resolution) * resolution
    width, height = int(round((maxx - minx) / resolution)), int(round((maxy - miny) / resolution))
    transform = Affine(resolution, 0, minx, 0, -resolution, maxy)
    geobox = GeoBox((height, width), transform, f"EPSG:{epsg}")
    aoi_mask = geometry_mask([mapping(aoi_utm)], out_shape=(height, width), transform=transform, invert=True)
    return geobox, aoi_utm, aoi_mask, epsg


def search_candidates(catalog: str, aoi, center: date, window_days: int, max_cloud: float) -> list:
    cfg = CATALOGS[catalog]
    modifier = planetary_computer.sign_inplace if catalog == "planetary-computer" else None
    client = Client.open(cfg["url"], modifier=modifier)
    start, end = center - timedelta(days=window_days), center + timedelta(days=window_days)
    search = client.search(
        collections=["sentinel-2-l2a"],
        intersects=mapping(aoi),
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        max_items=200,
    )
    items = [it for it in search.items() if shape(it.geometry).contains(aoi)]

    def rank(it):
        baseline = float(it.properties.get("s2:processing_baseline") or 0)
        return (round(it.properties.get("eo:cloud_cover", 100), 1),
                abs((it.datetime.date() - center).days), -baseline)

    return sorted(items, key=rank)


def _scale_offset(item) -> tuple[float, float]:
    # Baseline >= 04.00 products carry a +1000 DN radiometric offset. Earth Search re-encodes most
    # items with it already removed (flagged by earthsearch:boa_offset_applied) even though their
    # raster:bands metadata still lists offset -0.1, so the flag is the source of truth.
    baseline = float(item.properties.get("s2:processing_baseline") or 0)
    already_applied = bool(item.properties.get("earthsearch:boa_offset_applied", False))
    return 1e-4, (-0.1 if baseline >= 4.0 and not already_applied else 0.0)


def _scene_metadata(item, catalog: str, valid: np.ndarray, aoi_mask: np.ndarray) -> dict:
    p = item.properties
    tile = p.get("s2:mgrs_tile") or f"{p.get('mgrs:utm_zone', '')}{p.get('mgrs:latitude_band', '')}{p.get('mgrs:grid_square', '')}"
    sun_elev = p.get("view:sun_elevation")
    if sun_elev is None and p.get("s2:mean_solar_zenith") is not None:
        sun_elev = 90 - p["s2:mean_solar_zenith"]
    amap = CATALOGS[catalog]["assets"]
    scale, offset = _scale_offset(item)
    return {
        "scene_id": item.id,
        "reflectance_scale": scale,
        "reflectance_offset": offset,
        "catalog": catalog,
        "stac_api": CATALOGS[catalog]["url"],
        "acquired": item.datetime.isoformat(),
        "platform": p.get("platform"),
        "mgrs_tile": tile,
        "processing_baseline": p.get("s2:processing_baseline"),
        "scene_cloud_pct": round(float(p.get("eo:cloud_cover", float("nan"))), 4),
        "aoi_cloud_pct": round(float(100 * (1 - valid.sum() / max(aoi_mask.sum(), 1))), 2),
        "sun_elevation_deg": round(float(sun_elev), 3) if sun_elev is not None else None,
        "sun_azimuth_deg": p.get("view:sun_azimuth", p.get("s2:mean_solar_azimuth")),
        "assets": {S2_BAND_IDS.get(k, k.upper()): item.assets[v].href.split("?")[0] for k, v in amap.items()},
    }


def load_scene(item, catalog: str, geobox: GeoBox, aoi_mask: np.ndarray, label: str) -> Scene:
    amap = CATALOGS[catalog]["assets"]
    patch = planetary_computer.sign if catalog == "planetary-computer" else None
    ds = odc.stac.load(
        [item],
        bands=list(amap.values()),
        geobox=geobox,
        resampling={"*": "bilinear", amap["scl"]: "nearest"},
        groupby="solar_day",
        patch_url=patch,
        fail_on_error=True,
    ).isel(time=0)

    scl = ds[amap["scl"]].values.astype(np.uint8)
    bands = {}
    for name in BANDS:
        raw = ds[amap[name]].values
        scale, offset = _scale_offset(item)
        refl = raw.astype(np.float32) * scale + offset
        refl[raw == 0] = np.nan
        bands[name] = np.clip(refl, 0.0, 1.5)

    finite = np.all([np.isfinite(b) for b in bands.values()], axis=0)
    valid = aoi_mask & finite & ~np.isin(scl, SCL_INVALID)
    for name in BANDS:
        bands[name][~aoi_mask] = np.nan

    return Scene(label=label, bands=bands, scl=scl, valid=valid, aoi_mask=aoi_mask,
                 transform=geobox.affine, crs=str(geobox.crs),
                 metadata=_scene_metadata(item, catalog, valid, aoi_mask))


def acquire_scene(label: str, aoi, center: date, geobox: GeoBox, aoi_mask: np.ndarray, *,
                  window_days: int, max_cloud: float, max_aoi_cloud_pct: float, max_attempts: int = 4) -> Scene:
    """Try catalogs in order; within a catalog take the first scene whose AOI cloud cover is acceptable."""
    errors = []
    for catalog in CATALOGS:
        try:
            candidates = search_candidates(catalog, aoi, center, window_days, max_cloud)
        except Exception as exc:
            errors.append(f"{catalog}: search failed ({exc})")
            continue
        if not candidates:
            errors.append(f"{catalog}: no scenes < {max_cloud}% cloud within ±{window_days} days of {center}")
            continue
        best = None
        for item in candidates[:max_attempts]:
            try:
                scene = load_scene(item, catalog, geobox, aoi_mask, label)
            except Exception as exc:
                errors.append(f"{catalog}/{item.id}: load failed ({exc})")
                continue
            log.info("%s candidate %s: AOI cloud %.2f%%", label, item.id, scene.metadata["aoi_cloud_pct"])
            if best is None or scene.metadata["aoi_cloud_pct"] < best.metadata["aoi_cloud_pct"]:
                best = scene
            if scene.metadata["aoi_cloud_pct"] <= max_aoi_cloud_pct:
                break
        if best is not None:
            best.metadata["candidates_considered"] = len(candidates)
            best.metadata["meets_aoi_cloud_threshold"] = bool(best.metadata["aoi_cloud_pct"] <= max_aoi_cloud_pct)
            return best
    raise RuntimeError(f"No usable Sentinel-2 scene for {label} ({center}): " + "; ".join(errors))


def write_scene(scene: Scene, out_dir: Path) -> dict:
    h, w = scene.scl.shape
    bands_path = out_dir / f"{scene.label}_s2_bands.tif"
    profile = dict(driver="GTiff", height=h, width=w, count=len(BANDS), dtype="float32", crs=scene.crs,
                   transform=scene.transform, nodata=np.nan, compress="deflate", tiled=True)
    with rasterio.open(bands_path, "w", **profile) as dst:
        for i, name in enumerate(BANDS, start=1):
            data = np.where(scene.valid, scene.bands[name], np.nan).astype(np.float32)
            dst.write(data, i)
            dst.set_band_description(i, f"{S2_BAND_IDS[name]} {name} reflectance")
    scl_path = out_dir / f"{scene.label}_scl.tif"
    profile.update(count=1, dtype="uint8", nodata=0)
    with rasterio.open(scl_path, "w", **profile) as dst:
        dst.write(scene.scl, 1)
        dst.set_band_description(1, "Sentinel-2 Scene Classification Layer")
    return {"bands": bands_path.name, "scl": scl_path.name}


def ingest(aoi_geojson: dict, target_date: str, baseline_date: str | None, out_dir: str | Path, *,
           window_days: int = 15, max_cloud: float = 20.0, max_aoi_cloud_pct: float = 20.0,
           resolution: float = 10.0) -> tuple[dict[str, Scene], dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    aoi = parse_aoi(aoi_geojson)
    geobox, aoi_utm, aoi_mask, epsg = build_grid(aoi, resolution)
    odc.stac.configure_rio(cloud_defaults=True)

    scenes: dict[str, Scene] = {}
    outputs = {}
    for label, d in (("baseline", baseline_date), ("target", target_date)):
        if not d:
            continue
        scene = acquire_scene(label, aoi, date.fromisoformat(d), geobox, aoi_mask, window_days=window_days,
                              max_cloud=max_cloud, max_aoi_cloud_pct=max_aoi_cloud_pct)
        scene.metadata["requested_date"] = d
        outputs[label] = write_scene(scene, out_dir)
        scenes[label] = scene

    metadata = {
        "aoi_geojson": mapping(aoi),
        "aoi_area_ha": round(aoi_utm.area / 10_000, 2),
        "crs": f"EPSG:{epsg}",
        "resolution_m": resolution,
        "grid_shape": list(aoi_mask.shape),
        "grid_transform": list(geobox.affine)[:6],
        "search_parameters": {"collection": "sentinel-2-l2a", "window_days": window_days,
                              "max_scene_cloud_pct": max_cloud, "max_aoi_cloud_pct": max_aoi_cloud_pct,
                              "masked_scl_classes": list(SCL_INVALID)},
        "scenes": {label: s.metadata for label, s in scenes.items()},
        "outputs": outputs,
    }
    (out_dir / "ingestion_metadata.json").write_text(json.dumps(metadata, indent=2))
    return scenes, metadata
