import json
import uuid
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE IF NOT EXISTS aois (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    geom        GEOMETRY(Polygon, 4326) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS aois_geom_idx ON aois USING GIST (geom);
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aoi_id          UUID NOT NULL REFERENCES aois(id) ON DELETE CASCADE,
    target_date     DATE NOT NULL,
    baseline_date   DATE,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    is_demo         BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_sha256 TEXT,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS error TEXT;
CREATE INDEX IF NOT EXISTS analysis_jobs_aoi_idx ON analysis_jobs (aoi_id);
"""

JOB_COLUMNS = """
    j.id, j.status, j.stage, j.error, j.is_demo, j.target_date, j.baseline_date, j.evidence_sha256,
    j.result, j.created_at, j.updated_at, a.name AS site_name,
    ST_AsGeoJSON(a.geom)::json AS aoi_geojson, ST_Area(a.geom::geography) / 10000 AS aoi_area_ha
"""


@contextmanager
def connect():
    with psycopg.connect(settings.database_url, row_factory=dict_row) as conn:
        yield conn


def ensure_schema() -> None:
    with connect() as conn:
        conn.execute(SCHEMA_SQL)


def aoi_area_km2(aoi_geojson: dict) -> tuple[float, bool]:
    with connect() as conn:
        row = conn.execute(
            "SELECT ST_Area(g::geography) / 1e6 AS km2, ST_IsValid(g) AS valid "
            "FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326) AS g) s",
            (json.dumps(aoi_geojson),)).fetchone()
    return float(row["km2"]), bool(row["valid"])


def create_job(name: str, aoi_geojson: dict, target_date: str, baseline_date: str | None, *,
               job_id: uuid.UUID | None = None, is_demo: bool = False) -> uuid.UUID:
    job_id = job_id or uuid.uuid4()
    with connect() as conn:
        aoi_id = conn.execute(
            "INSERT INTO aois (name, geom) VALUES (%s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)) RETURNING id",
            (name, json.dumps(aoi_geojson))).fetchone()["id"]
        conn.execute(
            "INSERT INTO analysis_jobs (id, aoi_id, target_date, baseline_date, status, is_demo) "
            "VALUES (%s, %s, %s, %s, 'PENDING', %s)",
            (job_id, aoi_id, target_date, baseline_date, is_demo))
    return job_id


def update_job(job_id, *, status: str | None = None, stage: str | None = None, error: str | None = None,
               result: dict | None = None, evidence_sha256: str | None = None) -> None:
    sets, params = ["updated_at = now()"], []
    for col, val in (("status", status), ("stage", stage), ("error", error), ("evidence_sha256", evidence_sha256)):
        if val is not None:
            sets.append(f"{col} = %s")
            params.append(val)
    if result is not None:
        sets.append("result = %s")
        params.append(Jsonb(result))
    with connect() as conn:
        conn.execute(f"UPDATE analysis_jobs SET {', '.join(sets)} WHERE id = %s", (*params, job_id))


def get_job(job_id) -> dict | None:
    with connect() as conn:
        return conn.execute(f"SELECT {JOB_COLUMNS} FROM analysis_jobs j JOIN aois a ON a.id = j.aoi_id "
                            "WHERE j.id = %s", (job_id,)).fetchone()


def list_jobs(limit: int = 50) -> list[dict]:
    with connect() as conn:
        return conn.execute(
            "SELECT j.id, j.status, j.stage, j.is_demo, j.target_date, j.baseline_date, j.evidence_sha256, "
            "j.created_at, j.updated_at, a.name AS site_name FROM analysis_jobs j JOIN aois a ON a.id = j.aoi_id "
            "ORDER BY j.created_at DESC LIMIT %s", (limit,)).fetchall()


def delete_job(job_id) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM aois WHERE id = (SELECT aoi_id FROM analysis_jobs WHERE id = %s)", (job_id,))
