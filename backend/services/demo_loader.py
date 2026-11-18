"""Load the pre-computed Gevra showcase from /demo_data into PostGIS + MinIO (idempotent)."""
from __future__ import annotations

import json
import logging
import uuid

from backend.app import db, storage
from backend.app.config import settings
from backend.services.job_results import build_job_result, publish_artifacts

log = logging.getLogger(__name__)

DEMO_JOB_ID = uuid.uuid5(uuid.NAMESPACE_URL, "terraproof/demo/gevra-2021-2024")
MANIFEST_NAME = "demo_manifest.json"


def demo_available() -> bool:
    return (settings.demo_dir / MANIFEST_NAME).exists()


def load_demo(force: bool = False) -> dict:
    demo_dir = settings.demo_dir
    if not demo_available():
        raise FileNotFoundError(f"{demo_dir / MANIFEST_NAME} missing - run `python demo_data/seed_demo.py` first")
    manifest = json.loads((demo_dir / MANIFEST_NAME).read_text())

    job = db.get_job(DEMO_JOB_ID)
    if (job and not force and job["status"] == "SUCCESS"
            and job["evidence_sha256"] == manifest["evidence"]["package_sha256"]
            and (job["result"] or {}).get("report_pages")):
        return job
    if job:
        storage.delete_prefix(DEMO_JOB_ID)
        db.delete_job(DEMO_JOB_ID)

    summary = json.loads((demo_dir / "pipeline_summary.json").read_text())
    db.create_job(manifest["site_name"], manifest["aoi_geojson"], manifest["target_date"], manifest["baseline_date"],
                  job_id=DEMO_JOB_ID, is_demo=True)
    artifacts = publish_artifacts(DEMO_JOB_ID, demo_dir, manifest["artifacts"])
    result = build_job_result(summary, manifest["evidence"], artifacts, demo_dir)
    db.update_job(DEMO_JOB_ID, status="SUCCESS", stage="Complete (pre-computed demo)", result=result,
                  evidence_sha256=manifest["evidence"]["package_sha256"])
    log.info("Demo case loaded: %d artifacts", len(artifacts))
    return db.get_job(DEMO_JOB_ID)
