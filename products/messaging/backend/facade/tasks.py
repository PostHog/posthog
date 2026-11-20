"""Celery tasks other parts of PostHog schedule."""

from products.messaging.backend.tasks.tasks import close_stale_provider_import_runs

__all__ = ["close_stale_provider_import_runs"]
