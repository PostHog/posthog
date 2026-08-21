import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleplayconsole import (
    GooglePlayConsoleKeyFileConfig,
    GooglePlayConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.settings import (
    ENDPOINTS,
    METRIC_SETS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_play_console.source import (
    GooglePlayConsoleSource,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

SOURCE_MODULE = GooglePlayConsoleSource.__module__


def _config(app_package_names: str | None = None) -> GooglePlayConsoleSourceConfig:
    return GooglePlayConsoleSourceConfig(
        key_file=GooglePlayConsoleKeyFileConfig(
            client_email="reporting@example.iam.gserviceaccount.com",
            private_key="private-key",
            private_key_id="private-key-id",
            token_uri="https://oauth2.googleapis.com/token",
        ),
        app_package_names=app_package_names,
    )


def test_api_version_metadata() -> None:
    source = GooglePlayConsoleSource()

    assert source.supported_versions == ("v1beta1",)
    assert source.default_version == "v1beta1"
    assert source.api_docs_url is not None and source.api_docs_url.startswith("https://")


@pytest.mark.parametrize("name", sorted(METRIC_SETS))
def test_metric_sets_sync_incrementally_on_date_but_never_append(name: str) -> None:
    schema = next(s for s in GooglePlayConsoleSource().get_schemas(_config(), team_id=1) if s.name == name)

    assert schema.supports_incremental is True
    # Play restates recent days, so appending would keep the stale rows alongside the corrections.
    assert schema.supports_append is False
    assert [field["field"] for field in schema.incremental_fields] == ["date"]
    assert schema.incremental_fields[0]["field_type"] == IncrementalFieldType.Date
    assert schema.default_incremental_lookback_seconds == 7 * 24 * 60 * 60


def test_error_reports_sync_incrementally_on_event_time() -> None:
    schema = next(s for s in GooglePlayConsoleSource().get_schemas(_config(), team_id=1) if s.name == "error_reports")

    assert schema.supports_incremental is True
    assert schema.supports_append is True
    assert [field["field"] for field in schema.incremental_fields] == ["eventTime"]
    assert schema.default_incremental_lookback_seconds == 24 * 60 * 60


def test_canonical_descriptions_cover_every_endpoint() -> None:
    assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
    for name, entry in CANONICAL_DESCRIPTIONS.items():
        assert entry["description"], name
        assert entry["docs_url"].startswith("https://"), name
        assert entry["columns"], name
