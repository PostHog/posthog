"""Celery beat schedules for social_signals.

No periodic tasks yet — analyzers run on-demand after ingestion.
"""

CELERY_BEAT_SCHEDULE: dict = {}
