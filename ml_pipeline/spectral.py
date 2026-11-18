"""Stage 2: spectral indices, true/false colour composites, COG and PNG rendering."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from rasterio.io import MemoryFile
from rasterio.shutil import copy as rio_copy

from .ingestion import Scene

EPS = 1e-6
INDEX_NAMES = ("ndvi", "ndwi", "iron_swir_nir", "iron_red_blue")


def compute_indices(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    blue, green, red, nir, swir1 = (bands[k] for k in ("blue", "green", "red", "nir", "swir1"))
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "ndvi": ((nir - red) / (nir + red + EPS)).astype(np.float32),
            "ndwi": ((green - nir) / (green + nir + EPS)).astype(np.float32),
            "iron_swir_nir": np.clip(swir1 / (nir + EPS), 0, 5).astype(np.float32),
            "iron_red_blue": np.clip(red / (blue + EPS), 0, 5).astype(np.float32),
        }


def write_cog(path: Path, data: np.ndarray, transform, crs: str, *, nodata=None, descriptions=None,
              colormap: dict | None = None, categorical: bool = False) -> str:
    if data.ndim == 2:
        data = data[np.newaxis]
    count, height, width = data.shape
    profile = dict(driver="GTiff", height=height, width=width, count=count, dtype=data.dtype.name,
                   crs=crs, transform=transform, nodata=nodata)
    with MemoryFile() as mem:
        with mem.open(**profile) as dst:
            dst.write(data)
            for i, desc in enumerate(descriptions or [], start=1):
                dst.set_band_description(i, desc)
            if colormap:
                dst.write_colormap(1, colormap)
        with mem.open() as src:
            rio_copy(src, str(path), driver="COG", compress="DEFLATE",
                     overview_resampling="NEAREST" if categorical else "AVERAGE")
    return str(path)


def stretch_params(scenes: list[Scene], band_names: tuple[str, str, str], lo=2.0, hi=98.0) -> list[tuple]:
    """Percentile stretch pooled across dates so before/after images are directly comparable."""
    params = []
    for name in band_names:
        pooled = np.concatenate([s.bands[name][s.valid] for s in scenes])
        params.append(tuple(np.percentile(pooled, [lo, hi])))
    return params


def to_rgb8(scene: Scene, band_names: tuple[str, str, str], params: list[tuple]) -> np.ndarray:
    channels = []
    for name, (lo, hi) in zip(band_names, params):
        x = np.clip((scene.bands[name] - lo) / (hi - lo + EPS), 0, 1)
        channels.append(np.nan_to_num(x * 254 + 1, nan=0).astype(np.uint8))
    rgb = np.stack(channels)
    rgb[:, ~scene.aoi_mask] = 0
    return rgb


def save_png(path: Path, rgb8: np.ndarray, alpha_mask: np.ndarray) -> str:
    rgba = np.dstack([np.moveaxis(rgb8, 0, -1), (alpha_mask * 255).astype(np.uint8)])
    plt.imsave(path, rgba)
    return str(path)


def save_index_png(path: Path, index: np.ndarray, mask: np.ndarray, cmap: str, vmin: float, vmax: float) -> str:
    rgba = plt.get_cmap(cmap)(np.clip((index - vmin) / (vmax - vmin), 0, 1))
    rgba[..., 3] = mask.astype(float)
    plt.imsave(path, np.nan_to_num(rgba))
    return str(path)


def process_spectral(scenes: dict[str, Scene], out_dir: str | Path) -> tuple[dict[str, dict], dict]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    true_bands, false_bands = ("red", "green", "blue"), ("swir1", "nir", "red")
    true_params = stretch_params(list(scenes.values()), true_bands)
    false_params = stretch_params(list(scenes.values()), false_bands)

    indices, files = {}, {}
    for label, scene in scenes.items():
        idx = compute_indices(scene.bands)
        indices[label] = idx
        rgb = to_rgb8(scene, true_bands, true_params)
        fcc = to_rgb8(scene, false_bands, false_params)
        stack = np.stack([np.where(scene.valid, idx[k], np.nan) for k in INDEX_NAMES]).astype(np.float32)
        files[label] = {
            "rgb_cog": write_cog(out_dir / f"{label}_rgb.tif", rgb, scene.transform, scene.crs, nodata=0,
                                 descriptions=["Red B04", "Green B03", "Blue B02"]),
            "false_color_cog": write_cog(out_dir / f"{label}_false_color.tif", fcc, scene.transform, scene.crs,
                                         nodata=0, descriptions=["SWIR1 B11", "NIR B08", "Red B04"]),
            "indices_cog": write_cog(out_dir / f"{label}_indices.tif", stack, scene.transform, scene.crs,
                                     nodata=np.nan, descriptions=["NDVI", "NDWI", "SWIR1/NIR", "Red/Blue"]),
            "rgb_png": save_png(out_dir / f"{label}_rgb.png", rgb, scene.aoi_mask),
            "false_color_png": save_png(out_dir / f"{label}_false_color.png", fcc, scene.aoi_mask),
            "ndvi_png": save_index_png(out_dir / f"{label}_ndvi.png", idx["ndvi"], scene.valid, "RdYlGn", -0.2, 0.8),
        }
    return indices, files


def index_summary(indices: dict[str, np.ndarray], valid: np.ndarray) -> dict:
    return {k: {"mean": round(float(np.nanmean(v[valid])), 4), "p10": round(float(np.nanpercentile(v[valid], 10)), 4),
                "p90": round(float(np.nanpercentile(v[valid], 90)), 4)} for k, v in indices.items()}
