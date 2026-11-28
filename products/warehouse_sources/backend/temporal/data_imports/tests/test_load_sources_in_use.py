import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources import load_sources_in_use, source_module_path
from products.warehouse_sources.backend.types import ExternalDataSourceType


@pytest.mark.django_db
def test_load_sources_in_use_imports_only_the_types_that_have_a_live_source():
    team = Team.objects.create(organization=Organization.objects.create(name="org"))
    for source_type, deleted in [
        (ExternalDataSourceType.PYPI, False),
        (ExternalDataSourceType.PYPI, False),
        (ExternalDataSourceType.STRIPE, True),
        ("NoSuchSource", False),
    ]:
        ExternalDataSource.objects.create(
            team=team, source_id="id", connection_id="id", status="Completed", source_type=source_type, deleted=deleted
        )

    imported_modules: list[str] = []
    # The import is recorded, not run, because a module that an earlier test imported registers nothing again.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources._load_source", new=imported_modules.append
    ):
        load_sources_in_use()

    assert imported_modules == [source_module_path(ExternalDataSourceType.PYPI)]
