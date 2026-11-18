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
    stage           TEXT,
    error           TEXT,
    is_demo         BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_sha256 TEXT,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analysis_jobs_aoi_idx ON analysis_jobs (aoi_id);
