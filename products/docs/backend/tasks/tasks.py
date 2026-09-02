"""Celery tasks for docs."""

from celery import shared_task


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def sync_context_doc_task(doc_id: str) -> None:
    from products.docs.backend.facade import api  # noqa: PLC0415 — the facade imports this module lazily

    api.sync_context_doc(doc_id)


@shared_task(ignore_result=True)
def check_doc_watches_task() -> None:
    from products.docs.backend.facade import api  # noqa: PLC0415 — the facade imports this module lazily

    api.check_due_watches()
