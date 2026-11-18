import mimetypes
from functools import lru_cache
from pathlib import Path

from minio import Minio

from .config import settings

BUCKETS = ("rasters", "evidence", "demo")
CONTENT_TYPES = {".geojson": "application/geo+json", ".tif": "image/tiff", ".json": "application/json",
                 ".pdf": "application/pdf", ".png": "image/png", ".joblib": "application/octet-stream"}


@lru_cache
def client() -> Minio:
    return Minio(settings.minio_endpoint, access_key=settings.minio_access_key,
                 secret_key=settings.minio_secret_key, secure=False)


def ensure_buckets() -> None:
    for bucket in BUCKETS:
        if not client().bucket_exists(bucket):
            client().make_bucket(bucket)


def content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return CONTENT_TYPES.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def job_key(job_id, name: str) -> str:
    return f"jobs/{job_id}/{name}"


def upload_file(job_id, path: Path, name: str | None = None) -> str:
    name = name or path.name
    key = job_key(job_id, name)
    client().fput_object(settings.evidence_bucket, key, str(path), content_type=content_type(name))
    return key


def open_object(key: str):
    return client().get_object(settings.evidence_bucket, key)


def stat_object(key: str):
    return client().stat_object(settings.evidence_bucket, key)


def delete_prefix(job_id) -> None:
    for obj in client().list_objects(settings.evidence_bucket, prefix=f"jobs/{job_id}/", recursive=True):
        client().remove_object(settings.evidence_bucket, obj.object_name)
