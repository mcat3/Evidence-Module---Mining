"""CLI: run the TerraProof ML pipeline. Defaults to Gevra Open-Cast Coal Mine, 2021 vs 2024."""
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_pipeline.ingestion import aoi_from_point  # noqa: E402
from ml_pipeline.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--aoi", type=Path, help="GeoJSON Polygon/Feature file (WGS84). Overrides --lat/--lon.")
    p.add_argument("--lat", type=float, default=22.336)
    p.add_argument("--lon", type=float, default=82.548)
    p.add_argument("--half-size-km", type=float, default=4.0, help="Half-width of the square AOI around --lat/--lon")
    p.add_argument("--target-date", default="2024-03-01")
    p.add_argument("--baseline-date", default="2021-03-01", help="Pass an empty string to skip change detection")
    p.add_argument("--site-name", default="Gevra Open-Cast Coal Mine, Chhattisgarh")
    p.add_argument("--out", type=Path, default=ROOT / "outputs" / "gevra")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "rasterio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    aoi = json.loads(args.aoi.read_text()) if args.aoi else aoi_from_point(args.lat, args.lon, args.half_size_km)
    summary = run_pipeline(aoi, args.target_date, args.baseline_date or None, args.out, site_name=args.site_name)

    print("\n=== KPIs ===")
    for k, v in summary["kpis"].items():
        print(f"  {k:32s} {v}")
    print("=== Risk flags ===")
    for f in summary["risk_flags"] or [{"severity": "-", "message": "none"}]:
        print(f"  [{f['severity']}] {f['message']}")
    print(f"\nArtifacts written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
