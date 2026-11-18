# SYSTEM ROLE & OBJECTIVE
You are a Lead Geospatial Software Architect and Machine Learning Engineer. Your goal is to design, architect, and build an end-to-end automated geospatial intelligence platform for **Mining Activity Monitoring & Auditable Evidence Generation**. 

The platform allows a user to define an **Area of Interest (AOI)** (via GeoJSON polygon) and select a **Target Timestamp** (plus an optional Baseline Timestamp) to analyze mining operations. It fuses **RGB, Multispectral, and Hyperspectral** satellite imagery to generate tamper-evident, legally/financially auditable evidence (PDF reports, GeoJSONs, Cloud-Optimized GeoTIFFs, and structured JSON summaries) for insurance claims, regulatory compliance, and environmental impact assessments.

---

# CORE ARCHITECTURE & TECH STACK
Build the system using modular, production-ready components:
* **Data Ingestion:** Python (`pystac-client`, `planetary-computer`, `odc-stac`, `rasterio`, `xarray`) querying open STAC catalogs (Sentinel-2 L2A for RGB/Multispectral; EnMAP/PRISMA for Hyperspectral; Copernicus DEM / Sentinel-1 for elevation/radar context).
* **Geospatial & ML Processing:** Python (`scikit-learn`, `pytorch` / `segmentation-models-pytorch`, `pysptools`, `geopandas`, `shapely`).
* **Backend API & Async Workers:** `FastAPI` + `Celery` + `Redis` for asynchronous background processing of satellite scenes.
* **Database & Storage:** `PostgreSQL` + `PostGIS` for spatial metadata/AOIs; local S3-compatible storage (`MinIO` or `AWS S3`) for Cloud-Optimized GeoTIFFs (COGs) and generated reports.
* **Frontend Interface:** `Next.js` (React) + `Leaflet` or `Mapbox GL JS` with polygon drawing tools (`Geoman`), timeline slider, layer toggles, and evidence download dashboard.

---

# END-TO-END WORKFLOW & EXPECTED OUTPUTS BY STAGE

Execute the project in the following sequential stages. Do not move to the next stage until the current stage's outputs are verified.


# PROJECT: TerraProof — Geospatial Mining Intelligence & Auditable Evidence Platform

## 1. ENVIRONMENT & ZERO-COST INFRASTRUCTURE CONSTRAINTS
- **IDE & Workflow:** Built via Claude Code in VS Code. Keep all services runnable locally via a single `docker-compose.yml` with zero paid cloud dependencies.
- **Free Satellite Data APIs:** Use **Element84 Earth Search STAC API** (`https://element84.com`) and **Microsoft Planetary Computer STAC API** (`https://microsoft.com`). Both provide free, unauthenticated/free-token access to Sentinel-2 L2A (RGB + Multispectral) and Copernicus DEM without requiring AWS/Azure billing accounts.
- **Local Storage & DB:** Use `PostgreSQL + PostGIS` (spatial DB), `Redis` (task queue), and `MinIO` (local S3-compatible object storage for Cloud-Optimized GeoTIFFs and PDFs) via Docker.
- **Spatial Indexing & Fallback:** Include synthetic/mock hyperspectral spectral signature matching (simulating EnMAP/PRISMA mineral bands for Coal, Iron Ore, and Tailings) seamlessly fused with real Sentinel-2 multispectral data so the full 3-sensor workflow (RGB + Multispectral + Hyperspectral) can be demonstrated even when real hyperspectral tasking is unavailable over a sample AOI.

---

## 2. END-TO-END SYSTEM ARCHITECTURE & WORKFLOW

### Stage 1: Data Ingestion & Preprocessing (`/ml_pipeline/ingestion.py`)
- **Inputs:** `aoi_geojson` (Polygon), `target_date` (YYYY-MM-DD), `baseline_date` (YYYY-MM-DD).
- **Process:**
  1. Query STAC API for Sentinel-2 L2A scenes with `< 20%` cloud cover within ±15 days of target and baseline dates.
  2. Mask clouds/shadows using the Sentinel-2 Scene Classification Layer (`SCL` band).
  3. Clip bands (`B02` Blue, `B03` Green, `B04` Red, `B08` NIR, `B11` SWIR1, `B12` SWIR2) to the AOI and align to local UTM projection.
- **Outputs:** Aligned multi-band GeoTIFFs + `ingestion_metadata.json` (Scene IDs, timestamps, cloud %, sun elevation).

### Stage 2: Spectral Indices & Visual Composites (`/ml_pipeline/spectral.py`)
- **Process:** Compute normalized indices and render map layers:
  - `NDVI = (NIR - Red) / (NIR + Red)` -> Vegetation loss / deforestation.
  - `NDWI = (Green - NIR) / (Green + NIR)` -> Tailings ponds & water accumulation.
  - `Ferrous/Iron Oxide Index = (SWIR1 / NIR)` & `(Red / Blue)` -> Exposed overburden & mine excavation.
  - Generate True-Color (`RGB`) and False-Color (`SWIR1-NIR-Red`) PNGs and Cloud-Optimized GeoTIFFs (COGs).

### Stage 3: Machine Learning Pattern & Evidence Generation (`/ml_pipeline/models.py`)
- **Land Classification (ML):** Use a trained `RandomForestClassifier` (with spectral bands + NDVI + NDWI + Iron Oxide features, pre-trained on a curated open mining dataset or bootstrapped with spectral rule-based pseudo-labels on startup so it works out-of-the-box) to classify every pixel into 5 classes:
  - `0`: Undisturbed Vegetation
  - `1`: Active Mine Pit / Excavation
  - `2`: Overburden / Mineral Stockpile
  - `3`: Water / Tailings Pond
  - `4`: Haul Roads / Built Infrastructure
- **Change Detection & Pattern Extraction:**
  - Compare `Baseline` vs. `Target` class maps to quantify exact hectare (`ha`) changes per class.
  - Detect high-risk environmental patterns (e.g., *Pit expansion > 10%*, *Vegetation loss adjacent to water bodies*, *New stockpile formation*).
- **Hyperspectral Unmixing Module:** Run Spectral Angle Mapper (`SAM`) against USGS reference mineral spectra (Coal, Hematite/Iron Ore, Kaolinite/Clay) to tag stockpile material composition.

### Stage 4: Validation & Uncertainty Audit (`/ml_pipeline/validation.py`)
- Calculate pixel-level prediction confidence probabilities; flag regions with `< 70%` certainty as `Low Confidence`.
- Compute automated QA checks: Cloud-free AOI %, spatial co-registration alignment, and assign an overall **Evidence Reliability Grade** (`HIGH`, `MEDIUM`, `LOW`).

### Stage 5: Auditable Evidence Packaging (`/backend/services/evidence_builder.py`)
- Generate a **SHA-256 cryptographic hash** covering input satellite metadata and output spatial metrics to ensure tamper-proof integrity.
- Export:
  1. `evidence_package.json` (Full structured metrics, GeoJSON polygons, risk flags, validation audit, SHA-256 hash).
  2. `evidence_report.pdf` (Clean multi-page audit report using `ReportLab` or `WeasyPrint` featuring Executive Summary, Before/After RGB & Classified comparison images, Hectare Change Table, Risk Alerts, and Cryptographic Provenance Footer).

---

## 3. INTERVIEW DEMO MODE (CRITICAL FEATURE)
Build a dedicated **"Interview Demo Mode"** directly into the Next.js frontend and FastAPI backend so the project can be presented smoothly without waiting for live downloads:
1. **Pre-Cached Showcase Case Study:** Include a `/demo_data` seed script that pre-processes and caches a real, visually dramatic mining site (e.g., **Gevra Open-Cast Coal Mine, Chhattisgarh, India** — `Lat: 22.336, Lon: 82.548`, comparing 2021 vs. 2024).
2. **1-Click "Load Demo Case" Button:** On the frontend map UI, provide a prominent banner/button: **"Load Pre-Computed Demo (Gevra Mine 2021 vs 2024)"**. Clicking it immediately populates:
   - Interactive split-screen Before/After map slider (RGB vs. ML Classified Land Cover).
   - Real-time KPI cards (e.g., *+42.5 ha Pit Expansion*, *-38.2 ha Forest Loss*, *3 New Stockpiles Detected*, *Confidence: 91.4%*).
   - Interactive layer toggles (RGB, NDVI Heatmap, ML Segmentation Polygons, Hyperspectral Mineral Tags).
   - Instant download buttons for the generated **PDF Audit Report** and **JSON Evidence Payload**.
3. **Live Custom AOI Mode:** Keep the polygon drawing tool (`Leaflet-Geoman`) active so the user can also draw any custom box on the map and trigger a live analysis job.

---

## 4. STEP-BY-STEP EXECUTION PLAN FOR CLAUDE CODE
Follow these milestones sequentially. Pause and confirm after each milestone:
- **Milestone 1:** Initialize repository structure (`/backend`, `/ml_pipeline`, `/frontend`, `/demo_data`, `docker-compose.yml`) and verify Docker services (PostGIS, Redis, MinIO).
- **Milestone 2:** Build the Python `/ml_pipeline` (STAC ingestion, spectral indices, Random Forest land classifier, SAM mineral matcher, validation metrics) and run a CLI test script on the Gevra Mine coordinates to generate real output artifacts.
- **Milestone 3:** Build the `FastAPI` backend + `Celery` worker + `ReportLab/WeasyPrint` PDF generator, and create the `/demo_data` seed loader.
- **Milestone 4:** Build the `Next.js` interactive map dashboard with polygon drawing, Before/After comparison slider, KPI metrics panel, and PDF/JSON evidence export.

Also include a confusion matrix / IoU validation script capable of scoring model predictions against user-uploaded ground-truth GeoJSON polygons.