"""CLI: score a classified land-cover GeoTIFF against ground-truth GeoJSON polygons (confusion matrix, IoU, kappa)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rasterio  # noqa: E402

from ml_pipeline.validation import score_against_ground_truth  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prediction", type=Path, required=True, help="e.g. outputs/gevra/target_landcover.tif")
    p.add_argument("--ground-truth", type=Path, required=True, help="GeoJSON FeatureCollection in WGS84")
    p.add_argument("--class-property", default="class_id", help="Feature property holding class id (0-4) or name")
    p.add_argument("--out", type=Path, help="Optional path to write the JSON report")
    args = p.parse_args()

    with rasterio.open(args.prediction) as src:
        report = score_against_ground_truth(src.read(1), src.transform, src.crs.to_string(), args.ground_truth,
                                            class_property=args.class_property)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
