import uuid
import importlib

import pytest

from django.apps import apps

from products.warehouse_sources.backend.facade.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0131_pin_leadfeeder_null_api_version_to_v1"
)
pin_null_leadfeeder_rows_to_v1 = migration_module.pin_null_leadfeeder_rows_to_v1


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
class TestPinLeadfeederNullApiVersion:
    def test_pins_only_null_leadfeeder_rows(self, source_factory):
        unpinned = source_factory("Leadfeeder", api_version=None)
        pinned_unified = source_factory("Leadfeeder", api_version="2026-08-07")
        other_source = source_factory("Stripe", api_version=None)

        pin_null_leadfeeder_rows_to_v1(apps, None)

        unpinned.refresh_from_db()
        pinned_unified.refresh_from_db()
        other_source.refresh_from_db()
        assert unpinned.api_version == "v1"
        # An existing concrete pin (e.g. a source already moved to the unified API) must never be
        # overwritten.
        assert pinned_unified.api_version == "2026-08-07"
        # Non-Leadfeeder sources are untouched.
        assert other_source.api_version is None

    def test_is_idempotent(self, source_factory):
        source = source_factory("Leadfeeder", api_version=None)

        pin_null_leadfeeder_rows_to_v1(apps, None)
        pin_null_leadfeeder_rows_to_v1(apps, None)

        source.refresh_from_db()
        assert source.api_version == "v1"
