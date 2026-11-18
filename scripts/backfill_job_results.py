"""Add fields introduced after a job finished (`image_corners_wgs84`, `report_pages`) to stored job results.

Reads each job's published target_rgb.tif / evidence_report.pdf back from MinIO; evidence packages and their hashes are not touched.

Usage:  python scripts/backfill_job_results.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ml_pipeline  # noqa: E402,F401  (sanitises PROJ/GDAL env vars before rasterio loads)

from backend.app import db, storage  # noqa: E402
from backend.services.job_results import image_corners_wgs84, pdf_page_count  # noqa: E402


def main() -> int:
    updated = 0
    for row in db.list_jobs(200):
        job = db.get_job(row["id"])
        result = job["result"] or {}
        if job["status"] != "SUCCESS" or (result.get("image_corners_wgs84") and result.get("report_pages")):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            for name, key, fn in (("target_rgb.tif", "image_corners_wgs84", image_corners_wgs84),
                                  ("evidence_report.pdf", "report_pages", pdf_page_count)):
                if result.get(key) or name not in result.get("artifacts", {}):
                    continue
                path = Path(tmp) / name
                obj = storage.open_object(storage.job_key(job["id"], name))
                try:
                    path.write_bytes(obj.read())
                finally:
                    obj.close()
                    obj.release_conn()
                result[key] = fn(path)
        db.update_job(job["id"], result=result)
        updated += 1
        print(f"updated {job['id']} ({job['site_name']})")
    print(f"{updated} job(s) backfilled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
