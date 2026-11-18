"""Hyperspectral mineral tagging with the Spectral Angle Mapper (SAM).

Real EnMAP/PRISMA tasking is rarely available over an arbitrary AOI, so this module simulates an
EnMAP-like cube (400-2500 nm, 10 nm) from real Sentinel-2 pixels: each pixel is unmixed against the
reference library resampled to Sentinel-2 bands, then re-synthesised at full spectral resolution with
sensor noise. SAM is run on both the real 6-band spectra and the simulated cube, and every output
is labelled as simulated so it is never mistaken for a measured hyperspectral product.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import nnls

from .ingestion import BANDS, Scene

WAVELENGTHS_NM = np.arange(400, 2501, 10, dtype=np.float64)
S2_SRF = {"blue": (492.4, 66.0), "green": (559.8, 36.0), "red": (664.6, 31.0),
          "nir": (832.8, 106.0), "swir1": (1613.7, 91.0), "swir2": (2202.4, 175.0)}
MINERALS = {1: "Coal", 2: "Hematite / Iron Ore", 3: "Kaolinite / Clay Tailings", 4: "Sandstone / Shale Overburden"}
UNCLASSIFIED = 0
NODATA = 255
COAL_MAX_ALBEDO = 0.12


def _gauss(wl, center, width):
    return np.exp(-0.5 * ((wl - center) / width) ** 2)


def _sigmoid(wl, center, scale):
    return 1.0 / (1.0 + np.exp(-(wl - center) / scale))


def reference_library() -> np.ndarray:
    """Analytic approximations of USGS splib07 mineral spectra, keeping their diagnostic features."""
    wl = WAVELENGTHS_NM
    coal = 0.045 + 0.03 * (wl - 400) / 2100 - 0.006 * _gauss(wl, 1730, 40) - 0.008 * _gauss(wl, 2310, 40)
    hematite = (0.06 + 0.22 * _sigmoid(wl, 600, 30) - 0.08 * _gauss(wl, 880, 70)
                + 0.07 * _sigmoid(wl, 1250, 150) - 0.02 * _gauss(wl, 2200, 120))
    kaolinite = (0.50 + 0.25 * _sigmoid(wl, 550, 90) - 0.12 * _gauss(wl, 1395, 12) - 0.05 * _gauss(wl, 1415, 12)
                 - 0.12 * _gauss(wl, 1910, 25) - 0.07 * _gauss(wl, 2165, 10) - 0.15 * _gauss(wl, 2208, 12)
                 - 0.05 * _gauss(wl, 2380, 40))
    # Grey-brown Gondwana sandstone/shale: moderate albedo rising gently into SWIR, weak ferric slope,
    # weak 1.4/1.9 um water bands and a shallow 2.2 um Al-OH feature from illite/clay in the shale fraction.
    sandstone_shale = (np.interp(wl, [400, 490, 560, 665, 830, 1100, 1600, 2100, 2500],
                                 [0.15, 0.17, 0.19, 0.22, 0.25, 0.29, 0.32, 0.32, 0.29])
                       - 0.015 * _gauss(wl, 1415, 15) - 0.03 * _gauss(wl, 1910, 25) - 0.03 * _gauss(wl, 2205, 15))
    return np.clip(np.vstack([coal, hematite, kaolinite, sandstone_shale]), 0.01, 1.0)


def resample_to_s2(spectra: np.ndarray) -> np.ndarray:
    out = []
    for name in BANDS:
        center, fwhm = S2_SRF[name]
        w = _gauss(WAVELENGTHS_NM, center, fwhm / 2.355)
        out.append(spectra @ (w / w.sum()))
    return np.stack(out, axis=-1)


def spectral_angle(spectra: np.ndarray, refs: np.ndarray) -> np.ndarray:
    num = spectra @ refs.T
    denom = np.linalg.norm(spectra, axis=1, keepdims=True) * np.linalg.norm(refs, axis=1)[None, :]
    return np.arccos(np.clip(num / np.maximum(denom, 1e-12), -1, 1))


def simulate_hyperspectral(pixels_s2: np.ndarray, refs_hs: np.ndarray, refs_s2: np.ndarray,
                           rng: np.random.Generator, snr: float = 150.0):
    abundances = np.array([nnls(refs_s2.T, px)[0] for px in pixels_s2])
    cube = abundances @ refs_hs
    cube += rng.normal(0, 1, cube.shape) * cube / snr
    return np.clip(cube, 1e-4, None), abundances


def _tag(angles: np.ndarray, albedo: np.ndarray, threshold: float) -> np.ndarray:
    # SAM is albedo-invariant, so bright, spectrally flat grey overburden would otherwise match the
    # flat coal signature; coal is only accepted for dark pixels.
    angles = angles.copy()
    angles[albedo > COAL_MAX_ALBEDO, 0] = np.inf
    best = angles.argmin(axis=1)
    return np.where(angles.min(axis=1) <= threshold, best + 1, UNCLASSIFIED).astype(np.uint8)


def tag_minerals(scene: Scene, class_map: np.ndarray, out_dir: Path, *, classes=(1, 2),
                 angle_threshold_rad: float = 0.10, snr: float = 150.0, seed: int = 42,
                 chunk: int = 100_000) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(seed)
    refs_hs = reference_library()
    refs_s2 = resample_to_s2(refs_hs)
    mask = np.isin(class_map, classes) & scene.valid
    pixels = np.stack([scene.bands[b][mask] for b in BANDS], axis=-1).astype(np.float64)

    tags_hs = np.empty(len(pixels), dtype=np.uint8)
    tags_ms = np.empty(len(pixels), dtype=np.uint8)
    min_angle = np.empty(len(pixels), dtype=np.float32)
    mean_cube = {m: np.zeros(len(WAVELENGTHS_NM)) for m in MINERALS}
    counts = {m: 0 for m in MINERALS}
    for start in range(0, len(pixels), chunk):
        px = pixels[start:start + chunk]
        albedo = px.mean(axis=1)
        cube, _ = simulate_hyperspectral(px, refs_hs, refs_s2, rng, snr)
        ang_hs = spectral_angle(cube, refs_hs)
        tags_hs[start:start + chunk] = _tag(ang_hs, albedo, angle_threshold_rad)
        tags_ms[start:start + chunk] = _tag(spectral_angle(px, refs_s2), albedo, angle_threshold_rad)
        min_angle[start:start + chunk] = ang_hs.min(axis=1)
        for m in MINERALS:
            sel = tags_hs[start:start + chunk] == m
            mean_cube[m] += cube[sel].sum(axis=0)
            counts[m] += int(sel.sum())

    mineral_map = np.full(class_map.shape, NODATA, dtype=np.uint8)
    mineral_map[mask] = tags_hs
    pixel_ha = scene.pixel_area_ha
    tagged = tags_hs != UNCLASSIFIED
    composition = {MINERALS[m]: {"area_ha": round(float((tags_hs == m).sum() * pixel_ha), 2),
                                 "pct_of_tagged": round(float(100 * (tags_hs == m).sum() / max(tagged.sum(), 1)), 2)}
                   for m in MINERALS}
    library_path = out_dir / "mineral_reference_library.json"
    library_path.write_text(json.dumps({
        "source": "analytic approximations of USGS splib07 spectra (diagnostic absorption features preserved)",
        "wavelengths_nm": WAVELENGTHS_NM.tolist(),
        "spectra": {MINERALS[i + 1]: np.round(refs_hs[i], 5).tolist() for i in range(len(MINERALS))},
        "sentinel2_resampled": {MINERALS[i + 1]: np.round(refs_s2[i], 5).tolist() for i in range(len(MINERALS))},
    }))
    plot_path = out_dir / "hyperspectral_signatures.png"
    _plot_signatures(plot_path, refs_hs, {m: mean_cube[m] / counts[m] for m in MINERALS if counts[m]})

    summary = {
        "method": "Spectral Angle Mapper",
        "data_source": "SIMULATED EnMAP-like cube (211 bands, 400-2500 nm) synthesised from real Sentinel-2 L2A "
                       "pixels via linear unmixing + sensor noise; not a measured hyperspectral acquisition",
        "simulated_snr": snr,
        "angle_threshold_rad": angle_threshold_rad,
        "coal_max_albedo": COAL_MAX_ALBEDO,
        "analysed_classes": [int(c) for c in classes],
        "pixels_analysed": int(len(pixels)),
        "tagged_pct": round(float(100 * tagged.mean()) if len(pixels) else 0.0, 2),
        "mean_min_angle_rad": round(float(min_angle.mean()) if len(pixels) else 0.0, 4),
        "multispectral_vs_hyperspectral_tag_agreement_pct":
            round(float(100 * (tags_ms == tags_hs).mean()) if len(pixels) else 0.0, 2),
        "composition": composition,
        "files": {"reference_library": str(library_path), "signature_plot": str(plot_path)},
    }
    return mineral_map, summary


def _plot_signatures(path: Path, refs_hs: np.ndarray, observed: dict[int, np.ndarray]) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    colors = {1: "#333333", 2: "#b5442b", 3: "#c9a227", 4: "#7d8fa3"}
    for m, name in MINERALS.items():
        ax.plot(WAVELENGTHS_NM, refs_hs[m - 1], color=colors[m], lw=2, label=f"{name} (reference)")
        if m in observed:
            ax.plot(WAVELENGTHS_NM, observed[m], color=colors[m], lw=1, ls="--", label=f"{name} (simulated pixels, mean)")
    for name in BANDS:
        c, w = S2_SRF[name]
        ax.axvspan(c - w / 2, c + w / 2, color="#4a90d9", alpha=0.08)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Reflectance")
    ax.set_title("Mineral reference spectra vs. simulated hyperspectral pixels (shaded: Sentinel-2 bands)")
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def stockpile_mineral_tags(components: np.ndarray, mineral_map: np.ndarray, pixel_ha: float, min_area_ha: float) -> dict:
    """Dominant SAM mineral per labelled component id."""
    tags = {}
    for comp_id in np.unique(components[components > 0]):
        sel = mineral_map[components == comp_id]
        if sel.size * pixel_ha < min_area_ha:
            continue
        counts = np.bincount(sel[sel != NODATA], minlength=len(MINERALS) + 1)
        tagged = counts[1:].sum()
        dominant = int(counts[1:].argmax() + 1) if tagged else UNCLASSIFIED
        tags[int(comp_id)] = {
            "dominant_mineral": MINERALS.get(dominant, "Unclassified"),
            "mineral_purity_pct": round(float(100 * counts[dominant] / sel.size), 1) if tagged else 0.0,
        }
    return tags
