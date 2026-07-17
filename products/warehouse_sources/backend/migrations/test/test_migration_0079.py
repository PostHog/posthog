import uuid
import importlib

import pytest

from django.apps import apps

from products.warehouse_sources.backend.facade.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0079_pin_github_null_api_version"
)
pin_github_null_api_version = migration_module.pin_github_null_api_version


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
class TestPinGithubNullApiVersion:
    @pytest.mark.parametrize(
        "source_type, existing_pin, expected_pin",
        [
            ("Github", None, "2022-11-28"),  # unpinned GitHub rows freeze on the pre-flip version
            ("Github", "2026-03-10", "2026-03-10"),  # a real pin is never overwritten
            ("Stripe", None, None),  # other source types are untouched
        ],
    )
    def test_pin(self, source_factory, source_type, existing_pin, expected_pin):
        source = source_factory(source_type, api_version=existing_pin)

        pin_github_null_api_version(apps, None)
        pin_github_null_api_version(apps, None)  # idempotent

        source.refresh_from_db()
        assert source.api_version == expected_pin
