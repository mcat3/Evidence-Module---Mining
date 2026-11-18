import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL",
        f"postgresql://{_env('POSTGRES_USER', 'terraproof')}:{_env('POSTGRES_PASSWORD', 'terraproof')}"
        f"@{_env('POSTGRES_HOST', 'localhost')}:{_env('POSTGRES_PORT', '5433')}/{_env('POSTGRES_DB', 'terraproof')}"))
    redis_url: str = field(default_factory=lambda: _env(
        "REDIS_URL", f"redis://{_env('REDIS_HOST', 'localhost')}:{_env('REDIS_PORT', '6379')}/0"))
    minio_endpoint: str = field(default_factory=lambda: _env(
        "MINIO_ENDPOINT", f"{_env('MINIO_HOST', 'localhost')}:{_env('MINIO_API_PORT', '9000')}"))
    minio_access_key: str = field(default_factory=lambda: _env("MINIO_ROOT_USER", "terraproof"))
    minio_secret_key: str = field(default_factory=lambda: _env("MINIO_ROOT_PASSWORD", "terraproof-secret"))
    evidence_bucket: str = field(default_factory=lambda: _env("EVIDENCE_BUCKET", "evidence"))
    work_dir: Path = field(default_factory=lambda: Path(_env("WORK_DIR", str(ROOT / "outputs" / "jobs"))))
    demo_dir: Path = field(default_factory=lambda: Path(_env("DEMO_DIR", str(ROOT / "demo_data" / "gevra_2021_2024"))))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()))
    max_aoi_km2: float = field(default_factory=lambda: float(_env("MAX_AOI_KM2", "150")))


settings = Settings()
