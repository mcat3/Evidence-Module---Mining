FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib

RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY ml_pipeline ml_pipeline
COPY backend backend
COPY scripts scripts
COPY demo_data demo_data

RUN useradd --create-home --uid 10001 terraproof \
    && mkdir -p /app/outputs/jobs \
    && chown -R terraproof /app/outputs
USER terraproof

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
