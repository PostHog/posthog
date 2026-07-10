import uuid
import importlib

import pytest

from django.apps import apps

from products.warehouse_sources.backend.facade.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0062_backfill_externaldatasource_api_version"
)
backfill_api_version = migration_module.backfill_api_version


@pytest.fixture
def source_factory(team):
    def _create(source_type, api_version=None):
        return ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type=source_type,
            api_version=api_version,
            job_inputs={},
        )

    return _create


@pytest.mark.django_db
class TestBackfillApiVersion:
    @pytest.mark.parametrize(
        "source_type, existing_pin, expected_pin",
        [
            ("Stripe", None, "2024-09-30.acacia"),  # snapshot mapping applies
            ("Postgres", None, "v1"),  # unversioned type falls back to the default label
            ("Stripe", "2026-02-25.clover", "2026-02-25.clover"),  # existing pins are never overwritten
        ],
    )
    def test_backfill(self, source_factory, source_type, existing_pin, expected_pin):
        source = source_factory(source_type, api_version=existing_pin)

        backfill_api_version(apps, None)
        backfill_api_version(apps, None)  # idempotent

        source.refresh_from_db()
        assert source.api_version == expected_pin
