import logging
import shutil

import ml_pipeline  # noqa: F401  (sanitises PROJ/GDAL env vars before rasterio loads)
from ml_pipeline.pipeline import run_pipeline

from backend.services.evidence_builder import PACKAGE_NAME, PUBLISHED_ARTIFACTS, REPORT_NAME
from backend.services.job_results import build_job_result, publish_artifacts
from backend.services.pdf_report import build_evidence

from . import db
from .celery_app import celery_app
from .config import settings

log = logging.getLogger(__name__)


@celery_app.task(name="terraproof.run_analysis")
def run_analysis(job_id: str) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    db.update_job(job_id, status="RUNNING", stage="Queued for processing")
    work_dir = settings.work_dir / job_id
    try:
        summary = run_pipeline(
            job["aoi_geojson"], job["target_date"].isoformat(),
            job["baseline_date"].isoformat() if job["baseline_date"] else None, work_dir,
            site_name=job["site_name"], progress=lambda stage: db.update_job(job_id, stage=stage))
        db.update_job(job_id, stage="Stage 5: evidence packaging (SHA-256 + PDF)")
        evidence = build_evidence(summary, work_dir, job_id=job_id)
        db.update_job(job_id, stage="Uploading artifacts to object storage")
        artifacts = publish_artifacts(job_id, work_dir, (*PUBLISHED_ARTIFACTS, PACKAGE_NAME, REPORT_NAME))
        result = build_job_result(summary, evidence, artifacts, work_dir)
        db.update_job(job_id, status="SUCCESS", stage="Complete", result=result,
                      evidence_sha256=evidence["package_sha256"])
        return {"job_id": job_id, "package_sha256": evidence["package_sha256"]}
    except Exception as exc:
        log.exception("job %s failed", job_id)
        db.update_job(job_id, status="FAILED", stage="Failed", error=f"{type(exc).__name__}: {exc}"[:2000])
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
