"""Check that PostGIS, Redis and MinIO are reachable and create the MinIO buckets."""
import os
import sys
import time
import urllib.request
from pathlib import Path

import psycopg
import redis
from minio import Minio

ROOT = Path(__file__).resolve().parents[1]
BUCKETS = ("rasters", "evidence", "demo")


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def check_postgis() -> str:
    conn = psycopg.connect(
        host="localhost",
        port=int(os.getenv("POSTGRES_PORT", 5432)),
        dbname=os.getenv("POSTGRES_DB", "terraproof"),
        user=os.getenv("POSTGRES_USER", "terraproof"),
        password=os.getenv("POSTGRES_PASSWORD", "terraproof"),
    )
    with conn, conn.cursor() as cur:
        cur.execute("SELECT postgis_full_version()")
        version = cur.fetchone()[0].split('"')[1]
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name IN ('aois', 'analysis_jobs')"
        )
        tables = cur.fetchone()[0]
        cur.execute(
            "SELECT ST_Area(ST_Transform(ST_MakeEnvelope(82.53, 22.32, 82.56, 22.35, 4326), 32644)) / 10000"
        )
        area_ha = cur.fetchone()[0]
    if tables != 2:
        raise RuntimeError(f"expected 2 app tables, found {tables}")
    return f"PostGIS {version}, tables aois+analysis_jobs present, test envelope = {area_ha:.1f} ha"


def check_redis() -> str:
    r = redis.Redis(host="localhost", port=int(os.getenv("REDIS_PORT", 6379)))
    r.set("terraproof:healthcheck", "ok", ex=30)
    assert r.get("terraproof:healthcheck") == b"ok"
    return f"Redis {r.info()['redis_version']}, read/write OK"


def check_minio() -> str:
    port = int(os.getenv("MINIO_API_PORT", 9000))
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/minio/health/live", timeout=2)
            break
        except OSError:
            time.sleep(1)
    client = Minio(
        f"localhost:{port}",
        access_key=os.getenv("MINIO_ROOT_USER", "terraproof"),
        secret_key=os.getenv("MINIO_ROOT_PASSWORD", "terraproof-secret"),
        secure=False,
    )
    for bucket in BUCKETS:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
    names = sorted(b.name for b in client.list_buckets())
    return f"MinIO OK, buckets: {', '.join(names)}"


def main() -> int:
    load_env()
    failed = False
    for name, check in (("postgis", check_postgis), ("redis", check_redis), ("minio", check_minio)):
        try:
            print(f"[PASS] {name}: {check()}")
        except Exception as exc:
            failed = True
            print(f"[FAIL] {name}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
