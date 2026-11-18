# TerraProof

TerraProof monitors mining activity from open Sentinel-2 imagery and packages the results as tamper-evident evidence. It compares a baseline and a target acquisition of an AOI. It then:

- classifies every 10 m pixel with a Random Forest
- quantifies hectare change and risk patterns
- tags stockpile mineralogy with a spectral angle mapper
- seals the outputs in a SHA-256 evidence package, with a PDF audit dossier

## Run the full stack

```bash
docker compose up -d          # postgis, redis, minio, api, worker, frontend
```

| Service   | URL                          | Notes                                                   |
|-----------|------------------------------|---------------------------------------------------------|
| Dashboard | http://localhost:3000        | Next.js + Leaflet; proxies `/api/*` to the API          |
| API       | http://localhost:8000/docs   | FastAPI (OpenAPI UI)                                    |
| MinIO     | http://localhost:9001        | Object storage console (credentials in `.env`)          |
| PostGIS   | localhost:5433               | Port 5433 avoids clashing with a local PostgreSQL       |

The API loads the pre-computed Gevra demo case (`demo_data/gevra_2021_2024`) into PostGIS and MinIO when it starts.

## Dashboard

- **Load Pre-Computed Demo (Gevra Mine 2021 vs 2024)** in the top bar opens the showcase instantly. Use `/?demo=1` to deep-link to it, or `/?job=<id>` for any job.
- **Case-study switcher:** opens completed live analyses or starts a new custom AOI.
- **Split-screen swipe:** compares baseline and target imagery. Turn on True-color RGB, False-color SWIR, NDVI or the ML classification raster, then drag the divider. ML land-classification polygons swipe with the comparison. Mineral tags, new stockpiles and low-confidence zones are target-date products, so they show on the target side only.
- **Basemaps:** Esri World Imagery and OpenStreetMap. Neither needs an API key.
- **Raster placement:** the pipeline renders rasters on a UTM grid, which is rotated relative to lon/lat. The dashboard places each raster through its true corner coordinates (`image_corners_wgs84`) with an affine transform, so imagery and vector polygons stay registered.
- **Sidebar:**
  - the 6 core KPIs, risk alerts, the SAM mineral breakdown, land-cover change and the validation audit
  - **Verify Cryptographic Integrity**, which re-hashes every artifact stored in MinIO
  - PDF dossier and evidence JSON downloads
- **Custom AOI:** draw a rectangle or polygon (Leaflet-Geoman), choose the dates and run a live job. A stage tracker follows the Celery worker, and the results open automatically when it finishes (about 1–2 minutes).

## Local development

```bash
pip install -r requirements.txt
docker compose up -d postgis redis minio
uvicorn backend.app.main:app --port 8000
celery -A backend.app.celery_app worker --pool=solo --loglevel=INFO     # --pool=solo on Windows

cd frontend && npm install && npm run dev                               # http://localhost:3000
```

The frontend reads the API address from `API_INTERNAL_URL` at runtime. It defaults to `http://localhost:8000`.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run_pipeline.py` | Run the 4-stage ML pipeline from the CLI. Defaults to Gevra, 2021 vs 2024. |
| `demo_data/seed_demo.py` | Rebuild the demo showcase from `outputs/gevra`. Pass `--rerun` to fetch fresh STAC data. |
| `scripts/score_ground_truth.py` | Score a class map against ground-truth GeoJSON polygons (confusion matrix, IoU, kappa). |
| `scripts/backfill_job_results.py` | Add dashboard fields introduced later to stored job results. Evidence hashes are untouched. |
| `scripts/verify_services.py` | Check PostGIS, Redis and MinIO, and create the buckets. |

## Caveats

- **Simulated hyperspectral data:** the hyperspectral cube is a simulated EnMAP-like product, synthesised from real Sentinel-2 pixels. It is not a measured acquisition.
- **Classifier agreement is not accuracy:** the classifier is trained on rule-based pseudo-labels. Its hold-out agreement measures consistency with those rules, not accuracy. Use `scripts/score_ground_truth.py` with surveyed polygons for accuracy figures.
