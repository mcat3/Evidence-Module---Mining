from celery import Celery

from .config import settings

celery_app = Celery("terraproof", broker=settings.redis_url, backend=settings.redis_url,
                    include=["backend.app.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86_400,
    broker_connection_retry_on_startup=True,
)
