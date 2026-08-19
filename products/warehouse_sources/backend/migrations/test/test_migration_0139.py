import uuid
import importlib

import pytest

from django.apps import apps

from products.warehouse_sources.backend.facade.models import ExternalDataSource

migration_module = importlib.import_module(
    "products.warehouse_sources.backend.migrations.0139_repin_linkedin_ads_api_version"
)
repin_linkedin_ads_v1_to_202607 = migration_module.repin_linkedin_ads_v1_to_202607


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
class TestRepinLinkedinAdsApiVersion:
    def test_repins_only_v1_pinned_linkedin_ads_rows(self, source_factory):
        legacy_pinned = source_factory("LinkedinAds", api_version="v1")
        already_current = source_factory("LinkedinAds", api_version="202607")
        unpinned = source_factory("LinkedinAds", api_version=None)
        other_source = source_factory("Stripe", api_version="v1")

        repin_linkedin_ads_v1_to_202607(apps, None)

        legacy_pinned.refresh_from_db()
        already_current.refresh_from_db()
        unpinned.refresh_from_db()
        other_source.refresh_from_db()
        assert legacy_pinned.api_version == "202607"
        # A pin already on the current default is untouched.
        assert already_current.api_version == "202607"
        # NULL already resolves to the (now "202607") default, so it's left alone rather than
        # stamped with a concrete value.
        assert unpinned.api_version is None
        # Non-LinkedinAds sources on the same legacy label are untouched.
        assert other_source.api_version == "v1"

    def test_is_idempotent(self, source_factory):
        source = source_factory("LinkedinAds", api_version="v1")

        repin_linkedin_ads_v1_to_202607(apps, None)
        repin_linkedin_ads_v1_to_202607(apps, None)

        source.refresh_from_db()
        assert source.api_version == "202607"
