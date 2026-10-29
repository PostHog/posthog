from typing import Any

import pytest

import psycopg

from products.warehouse_sources_queue.backend.testing import ensure_queue_tables, get_test_database_url


@pytest.fixture(scope="package")
def _queue_tables(django_db_setup: Any, django_db_blocker: Any) -> None:
    with django_db_blocker.unblock():
        with psycopg.connect(get_test_database_url(), autocommit=True) as conn:
            ensure_queue_tables(conn)


@pytest.fixture
def queue_database(_queue_tables: None, settings: Any) -> str:
    url = get_test_database_url()
    settings.WAREHOUSE_SOURCES_DATABASE_URL = url
    return url
