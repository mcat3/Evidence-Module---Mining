"""Build the Interview Demo Mode showcase (Gevra Open-Cast Coal Mine, 2021 vs 2024) from real pipeline outputs.

Usage:
    python demo_data/seed_demo.py            # reuse outputs/gevra if present, else run the pipeline
    python demo_data/seed_demo.py --rerun    # always re-run the pipeline against live STAC data
"""
import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ml_pipeline  # noqa: E402,F401
from ml_pipeline.ingestion import aoi_from_point  # noqa: E402
from ml_pipeline.pipeline import run_pipeline  # noqa: E402

from backend.services.demo_loader import DEMO_JOB_ID, MANIFEST_NAME  # noqa: E402
from backend.services.evidence_builder import PACKAGE_NAME, REPORT_NAME  # noqa: E402
from backend.services.pdf_report import build_evidence  # noqa: E402

SITE_NAME = "Gevra Open-Cast Coal Mine, Chhattisgarh"
LAT, LON, HALF_SIZE_KM = 22.336, 82.548, 4.0
TARGET_DATE, BASELINE_DATE = "2024-03-01", "2021-03-01"
# Everything the dashboard and dossier need; the 11 MB float index stacks and raw band stacks are left out.
DEMO_ARTIFACTS = (
    "baseline_rgb.png", "target_rgb.png", "baseline_false_color.png", "target_false_color.png",
    "baseline_ndvi.png", "target_ndvi.png", "baseline_landcover.png", "target_landcover.png",
    "baseline_landcover.geojson", "target_landcover.geojson", "new_stockpiles.geojson",
    "target_mineral_tags.geojson", "target_low_confidence.geojson",
    "baseline_rgb.tif", "target_rgb.tif", "baseline_landcover.tif", "target_landcover.tif",
    "target_confidence.tif", "target_mineral_tags.tif",
    "hyperspectral_signatures.png", "mineral_reference_library.json", "ingestion_metadata.json",
    "pipeline_summary.json",
)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rerun", action="store_true", help="re-run the pipeline even if outputs/gevra exists")
    p.add_argument("--work", type=Path, default=ROOT / "outputs" / "gevra")
    p.add_argument("--dest", type=Path, default=ROOT / "demo_data" / "gevra_2021_2024")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "rasterio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    summary_path = args.work / "pipeline_summary.json"
    if args.rerun or not summary_path.exists():
        summary = run_pipeline(aoi_from_point(LAT, LON, HALF_SIZE_KM), TARGET_DATE, BASELINE_DATE, args.work,
                               site_name=SITE_NAME)
    else:
        summary = json.loads(summary_path.read_text())

    evidence = build_evidence(summary, args.work, job_id=str(DEMO_JOB_ID), artifact_names=DEMO_ARTIFACTS)

    # Empty the folder rather than removing it: synced folders (e.g. OneDrive) often lock the directory itself.
    args.dest.mkdir(parents=True, exist_ok=True)
    for stale in args.dest.iterdir():
        if stale.is_file():
            stale.unlink()
    for name in (*DEMO_ARTIFACTS, PACKAGE_NAME, REPORT_NAME):
        shutil.copy2(args.work / name, args.dest / name)

    manifest = {
        "job_id": str(DEMO_JOB_ID),
        "site_name": SITE_NAME,
        "aoi_geojson": summary["inputs"]["aoi_geojson"],
        "target_date": TARGET_DATE,
        "baseline_date": BASELINE_DATE,
        "kpis": summary["kpis"],
        "evidence": {k: evidence[k] for k in ("package_sha256", "package_file_sha256", "report_sha256")},
        "artifacts": [*DEMO_ARTIFACTS, PACKAGE_NAME, REPORT_NAME],
    }
    (args.dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))

    size_mb = sum(f.stat().st_size for f in args.dest.iterdir()) / 1e6
    print(f"Demo seeded at {args.dest} ({size_mb:.1f} MB)")
    print(f"Evidence package SHA-256: {evidence['package_sha256']}")
    for k, v in summary["kpis"].items():
        print(f"  {k:32s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
