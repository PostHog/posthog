"""Redshift source discovery against a live Postgres.

Redshift speaks the Postgres wire protocol and derives its catalogs from Postgres, and no Redshift
cluster is reachable from CI, so the Django test database stands in for the cluster. Postgres hides
a materialized view from `information_schema.columns` for real (`relkind = 'm'`), which is the same
symptom the Redshift `pg_catalog` fallback exists for, so these tests fail without it.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from unittest import mock

import psycopg
from rest_framework import status
from rest_framework.test import APIClient

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.test_jobs_db import (
    _get_test_database_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift import RedshiftImplementation
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import RedshiftSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SCHEMA = "redshift_e2e"
MATERIALIZED_VIEW = "daily_totals_mv"


@pytest.fixture
def materialized_view() -> Iterator[None]:
    with psycopg.connect(_get_test_database_url(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        conn.execute(
            f"CREATE TABLE {SCHEMA}.orders "
            "(id bigint PRIMARY KEY, amount numeric(18,2), label varchar(256), created_at timestamp)"
        )
        conn.execute(f"INSERT INTO {SCHEMA}.orders VALUES (1, 10.5, 'first', now())")
        conn.execute(
            f"CREATE MATERIALIZED VIEW {SCHEMA}.{MATERIALIZED_VIEW} AS "
            f"SELECT id, created_at::date AS day, sum(amount) AS total, max(created_at) AS refreshed_at "
            f"FROM {SCHEMA}.orders GROUP BY 1, 2"
        )
        try:
            yield
        finally:
            conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


@contextmanager
def _redshift_backed_by_test_database() -> Iterator[None]:
    """Route the Redshift driver's connection to the test database, keeping every query real."""

    @contextmanager
    def connect(self: RedshiftImplementation, config: object, *, team_id: int | None = None):
        with psycopg.connect(_get_test_database_url()) as conn:
            yield conn

    with (
        mock.patch.object(RedshiftImplementation, "connect", connect),
        mock.patch.object(RedshiftSource, "is_database_host_valid", return_value=(True, None)),
    ):
        yield


@pytest.mark.django_db
@pytest.mark.usefixtures("materialized_view")
def test_incremental_fields_for_a_materialized_view_hidden_from_information_schema(team, user):
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        source_type=ExternalDataSourceType.REDSHIFT,
        job_inputs={
            "host": "redshift.example.com",
            "port": "5439",
            "database": "warehouse",
            "user": "posthog",
            "password": "not-a-real-password",
            "schema": SCHEMA,
        },
    )
    schema = ExternalDataSchema.objects.create(
        team=team, source=source, name=MATERIALIZED_VIEW, should_sync=True, sync_type="full_refresh"
    )
    client = APIClient()
    client.force_login(user)

    with _redshift_backed_by_test_database():
        response = client.post(f"/api/environments/{team.pk}/external_data_schemas/{schema.id}/incremental_fields")

    assert response.status_code == status.HTTP_200_OK, response.json()
    body = response.json()
    assert body["incremental_available"] is True
    assert {(f["field"], f["field_type"]) for f in body["incremental_fields"]} == {
        ("id", "integer"),
        ("day", "date"),
        ("refreshed_at", "timestamp"),
    }
    assert {c["field"] for c in body["available_columns"]} == {"id", "day", "total", "refreshed_at"}


@pytest.mark.usefixtures("materialized_view")
def test_sync_time_metadata_for_a_materialized_view_hidden_from_information_schema():
    with psycopg.connect(_get_test_database_url(), autocommit=True) as conn, conn.cursor() as cursor:
        table = RedshiftImplementation().get_table_metadata(cursor, SCHEMA, MATERIALIZED_VIEW)

    assert [(column.name, column.data_type) for column in table.columns] == [
        ("id", "bigint"),
        ("day", "date"),
        ("total", "numeric"),
        ("refreshed_at", "timestamp without time zone"),
    ]
    assert str(table.to_arrow_schema().field("total").type) == "decimal128(38, 18)"
