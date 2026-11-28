"""
Which queue a caller talks to while the batch queue moves to another queue.

Outside a migration there is one queue and every function here answers with it.
During a migration ``WAREHOUSE_SOURCES_DRAINING_DATABASE_URL`` names the old queue:

- A new run inserts into the active queue. A run that already has batches in the draining
  queue stays there, because the claim gates and the completion checks read one run from
  one queue.
- A loader consumes one queue (``run_warehouse_sources_load --queue``). Code that runs for a
  claimed batch reads that batch's own run from ``consuming_queue_url()``.
- Everything keyed by a job or a schema, not by a claimed batch, visits ``all_queue_urls()``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings

import psycopg

from products.warehouse_sources_queue.backend.core.queue_migration import queue_has_run

_consuming_queue_url: str | None = None


def active_queue_url() -> str:
    return settings.WAREHOUSE_SOURCES_DATABASE_URL


def draining_queue_url() -> str | None:
    url = getattr(settings, "WAREHOUSE_SOURCES_DRAINING_DATABASE_URL", "")
    if not url or url == active_queue_url():
        return None
    return url


def all_queue_urls() -> list[str]:
    """The active queue first, then the draining queue while a migration runs."""
    draining = draining_queue_url()
    return [active_queue_url()] if draining is None else [active_queue_url(), draining]


def set_consuming_queue_url(url: str) -> None:
    """Called once by the loader process, before it claims its first batch."""
    global _consuming_queue_url
    _consuming_queue_url = url


def consuming_queue_url() -> str:
    """The queue this loader process claims from. The active queue in every other process."""
    return _consuming_queue_url or active_queue_url()


def queue_url_for_run(*run_uuids: str | None) -> str:
    """The queue a producer of these runs inserts into.

    Raises when the draining queue cannot be read. A guess could split one run over two
    queues, and the caller's retry is cheaper than that.
    """
    draining = draining_queue_url()
    known = [run_uuid for run_uuid in run_uuids if run_uuid]
    if draining is None or not known:
        return active_queue_url()
    with psycopg.Connection.connect(draining, autocommit=True, connect_timeout=10) as conn:
        return draining if queue_has_run(conn, run_uuids=known) else active_queue_url()


@contextmanager
def queue_connection(url: str) -> Iterator[psycopg.Connection[Any]]:
    conn = psycopg.Connection.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()
