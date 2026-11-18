"""TerraProof API: AOI analysis jobs, evidence artifacts, integrity verification and Interview Demo Mode."""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal

import redis
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from shapely.geometry import shape

from backend.services import demo_loader
from backend.services.evidence_builder import PACKAGE_NAME, verify_package

from . import db, storage
from .celery_app import celery_app
from .config import settings

log = logging.getLogger("terraproof.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def _wait_for_dependencies(attempts: int = 30, delay_s: float = 2.0) -> None:
    for attempt in range(1, attempts + 1):
        try:
            db.ensure_schema()
            storage.ensure_buckets()
            return
        except Exception as exc:
            if attempt == attempts:
                raise
            log.warning("Dependencies not ready (%s); retry %d/%d", exc, attempt, attempts)
            time.sleep(delay_s)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _wait_for_dependencies()
    if demo_loader.demo_available():
        try:
            demo_loader.load_demo()
        except Exception:
            log.exception("Demo case could not be preloaded; POST /api/demo/load to retry")
    yield


app = FastAPI(title="TerraProof API", version="1.0.0", lifespan=lifespan,
              description="Geospatial mining intelligence and auditable evidence generation.")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["Content-Disposition", "X-Artifact-SHA256"])


class JobRequest(BaseModel):
    aoi_geojson: dict[str, Any] = Field(description="GeoJSON Polygon (or Feature wrapping one) in WGS84")
    target_date: date
    baseline_date: date | None = None
    site_name: str = Field(default="Custom AOI", max_length=200)

    @field_validator("aoi_geojson")
    @classmethod
    def _polygon(cls, v: dict) -> dict:
        if v.get("type") == "Feature":
            v = v.get("geometry") or {}
        if v.get("type") != "Polygon":
            raise ValueError("aoi_geojson must be a GeoJSON Polygon")
        try:
            geom = shape(v)
        except Exception as exc:
            raise ValueError(f"invalid polygon: {exc}") from exc
        minx, miny, maxx, maxy = geom.bounds
        if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
            raise ValueError("coordinates must be WGS84 longitude/latitude")
        return v

    @model_validator(mode="after")
    def _dates(self):
        if self.target_date > date.today():
            raise ValueError("target_date cannot be in the future")
        if self.target_date < date(2017, 3, 28):
            raise ValueError("target_date predates Sentinel-2 L2A availability (2017-03-28)")
        if self.baseline_date and self.baseline_date >= self.target_date:
            raise ValueError("baseline_date must be before target_date")
        return self


class JobStatus(BaseModel):
    id: uuid.UUID
    status: Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]
    stage: str | None = None
    error: str | None = None
    is_demo: bool
    site_name: str
    target_date: date
    baseline_date: date | None
    evidence_sha256: str | None = None
    aoi_geojson: dict | None = None
    aoi_area_ha: float | None = None
    result: dict | None = None


def _job_or_404(job_id: uuid.UUID) -> dict:
    job = db.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


def _job_response(job: dict) -> JobStatus:
    return JobStatus(**{k: job.get(k) for k in JobStatus.model_fields})


@app.get("/api/health")
def health() -> dict:
    checks = {}
    try:
        with db.connect() as conn:
            checks["postgis"] = conn.execute("SELECT postgis_lib_version() AS v").fetchone()["v"]
    except Exception as exc:
        checks["postgis"] = f"error: {exc}"
    try:
        checks["redis"] = "ok" if redis.Redis.from_url(settings.redis_url).ping() else "error"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
    try:
        checks["minio"] = "ok" if storage.client().bucket_exists(settings.evidence_bucket) else "bucket missing"
    except Exception as exc:
        checks["minio"] = f"error: {exc}"
    ok = not any(str(v).startswith("error") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "services": checks, "demo_available": demo_loader.demo_available()}


@app.post("/api/jobs", status_code=202, response_model=JobStatus)
def create_job(req: JobRequest) -> JobStatus:
    km2, valid = db.aoi_area_km2(req.aoi_geojson)
    if not valid:
        raise HTTPException(422, "AOI polygon is not valid (self-intersecting?)")
    if km2 > settings.max_aoi_km2:
        raise HTTPException(422, f"AOI is {km2:.1f} km2; the limit is {settings.max_aoi_km2:.0f} km2")
    job_id = db.create_job(req.site_name, req.aoi_geojson, req.target_date.isoformat(),
                           req.baseline_date.isoformat() if req.baseline_date else None)
    celery_app.send_task("terraproof.run_analysis", args=[str(job_id)])
    return _job_response(db.get_job(job_id))


@app.get("/api/jobs")
def list_jobs(limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    return db.list_jobs(limit)


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job(job_id: uuid.UUID) -> JobStatus:
    return _job_response(_job_or_404(job_id))


@app.get("/api/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: uuid.UUID, name: str, download: bool = False):
    job = _job_or_404(job_id)
    artifacts = (job.get("result") or {}).get("artifacts", {})
    if name not in artifacts:
        raise HTTPException(404, "artifact not found for this job")
    obj = storage.open_object(storage.job_key(job_id, name))

    def stream():
        try:
            yield from obj.stream(1 << 16)
        finally:
            obj.close()
            obj.release_conn()

    disposition = "attachment" if download else "inline"
    filename = f"terraproof_{str(job_id)[:8]}_{name}"
    return StreamingResponse(stream(), media_type=storage.content_type(name), headers={
        "Content-Disposition": f'{disposition}; filename="{filename}"',
        "Content-Length": str(artifacts[name]["bytes"]),
        "X-Artifact-SHA256": artifacts[name]["sha256"],
        "Cache-Control": "public, max-age=3600",
    })


@app.get("/api/jobs/{job_id}/report.pdf")
def get_report(job_id: uuid.UUID, download: bool = True):
    return get_artifact(job_id, "evidence_report.pdf", download)


@app.get("/api/jobs/{job_id}/evidence.json")
def get_evidence(job_id: uuid.UUID, download: bool = True):
    return get_artifact(job_id, PACKAGE_NAME, download)


@app.get("/api/jobs/{job_id}/verify")
def verify_job(job_id: uuid.UUID, artifacts: bool = True) -> dict:
    """Re-derive every SHA-256 from what is actually in object storage."""
    job = _job_or_404(job_id)
    if job["status"] != "SUCCESS":
        raise HTTPException(409, f"job is {job['status']}")
    obj = storage.open_object(storage.job_key(job_id, PACKAGE_NAME))
    try:
        package = json.loads(obj.read())
    finally:
        obj.close()
        obj.release_conn()
    report = verify_package(package)
    failed = []
    if artifacts:
        for name, entry in package.get("artifact_manifest", {}).items():
            digest = hashlib.sha256()
            stored = storage.open_object(storage.job_key(job_id, name))
            try:
                for chunk in stored.stream(1 << 20):
                    digest.update(chunk)
            finally:
                stored.close()
                stored.release_conn()
            if digest.hexdigest() != entry["sha256"]:
                failed.append(name)
        report["artifacts_checked"] = len(package.get("artifact_manifest", {}))
        report["artifacts_failed"] = failed
    report["valid"] = all(report["checks"].values()) and not failed
    report["matches_job_record"] = report["package_sha256"] == job["evidence_sha256"]
    report["valid"] = report["valid"] and report["matches_job_record"]
    return report


@app.post("/api/verify")
def verify_uploaded_package(package: dict[str, Any]) -> dict:
    """Verify an evidence_package.json supplied by an auditor (hashes only; no artifact files)."""
    if "integrity" not in package:
        raise HTTPException(422, "not a TerraProof evidence package (no 'integrity' block)")
    return verify_package(package)


@app.get("/api/demo", response_model=JobStatus)
def get_demo() -> JobStatus:
    job = db.get_job(demo_loader.DEMO_JOB_ID)
    if job is None or job["status"] != "SUCCESS":
        return load_demo()
    return _job_response(job)


@app.post("/api/demo/load", response_model=JobStatus)
def load_demo(force: bool = False) -> JobStatus:
    try:
        return _job_response(demo_loader.load_demo(force=force))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc
