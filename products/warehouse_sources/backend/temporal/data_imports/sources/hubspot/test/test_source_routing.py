from dataclasses import replace

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.settings import (
    DEFAULT_PROPS,
    ENDPOINTS,
    HUBSPOT_API_VERSION_2026_03,
    HUBSPOT_API_VERSION_2026_09,
    HUBSPOT_API_VERSION_V3,
    HUBSPOT_ENDPOINTS,
    HUBSPOT_METADATA_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source import (
    HubspotSource,
    HubspotSourceOldConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def _make_inputs(
    schema_name: str = "deals",
    should_use_incremental_field: bool = True,
    db_incremental_field_last_value: str | None = "2026-01-01T00:00:00.000Z",
    reset_pipeline: bool = False,
    schema_id: str = "schema-1",
    team_id: int = 1,
    source_id: str = "source-1",
    api_version: str | None = None,
) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id=schema_id,
        source_id=source_id,
        team_id=team_id,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        db_incremental_field_earliest_value=None,
        incremental_field=HUBSPOT_ENDPOINTS[schema_name].cursor_filter_property_field,
        incremental_field_type=IncrementalFieldType.DateTime,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=reset_pipeline,
        api_version=api_version,
    )


class TestGetSchemas:
    def test_filters_by_names(self) -> None:
        src = HubspotSource()
        schemas = src.get_schemas(MagicMock(), team_id=1, names=["deals", "contacts"])
        assert {s.name for s in schemas} == {"deals", "contacts"}


class TestShouldUseSearchPath:
    def test_false_when_reset_pipeline(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs(reset_pipeline=True)
        assert src._should_use_search_path(inputs) is False

    def test_false_when_endpoint_has_no_cursor(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs(schema_name="deals")
        no_cursor = replace(HUBSPOT_ENDPOINTS["deals"], cursor_filter_property_field=None)
        with patch.dict(HUBSPOT_ENDPOINTS, {"deals": no_cursor}):
            assert src._should_use_search_path(inputs) is False

    def test_false_when_db_lookup_fails(self) -> None:
        src = HubspotSource()
        inputs = _make_inputs()
        with patch(
            "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects.get",
            side_effect=Exception("db down"),
        ):
            assert src._should_use_search_path(inputs) is False


class TestSourceForPipelineRouting:
    """Verify that source_for_pipeline routes to the right get_rows/get_rows_via_search path."""

    def test_routes_to_get_when_initial_sync_not_complete(self) -> None:
        src = HubspotSource()
        from products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source import (
            HubspotSourceOldConfig,
        )

        old_config = HubspotSourceOldConfig.from_dict(
            {"hubspot_secret_key": "secret", "hubspot_refresh_token": "refresh"}
        )
        inputs = _make_inputs()
        schema = MagicMock()
        schema.initial_sync_complete = False

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source.hubspot_source",
                return_value=MagicMock(),
            ) as hubspot_source_mock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source.hubspot_access_token_is_valid",
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema.objects.get",
                return_value=schema,
            ),
        ):
            src.source_for_pipeline(old_config, MagicMock(), inputs)

        assert hubspot_source_mock.call_args.kwargs["use_search_path"] is False


class TestSettingsShape:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_endpoint_resolves_to_exactly_one_config(self, endpoint: str) -> None:
        # An endpoint in neither dict raises KeyError mid-sync; one in both would take whichever
        # branch happens to be checked first.
        assert (endpoint in HUBSPOT_ENDPOINTS) is not (endpoint in HUBSPOT_METADATA_ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(HUBSPOT_ENDPOINTS.keys()))
    def test_cursor_property_is_in_default_props(self, endpoint: str) -> None:
        config = HUBSPOT_ENDPOINTS[endpoint]
        assert config.cursor_filter_property_field is not None
        # The cursor property must be in the request so the flattened row carries it
        assert config.cursor_filter_property_field in DEFAULT_PROPS[endpoint]

    @pytest.mark.parametrize("endpoint", list(HUBSPOT_ENDPOINTS.keys()))
    def test_hs_object_id_is_in_default_props(self, endpoint: str) -> None:
        # Required so we can extract the primary key for association lookups
        assert "hs_object_id" in DEFAULT_PROPS[endpoint]


@pytest.mark.parametrize(
    "error_msg",
    [
        # fetch_page/_get, exhausted after tenacity's 5 in-process attempts (e.g. a Cloudflare 522)
        "Hubspot API error (retryable): status=522, url=https://api.hubapi.com/crm/v3/properties/meetings",
        "Hubspot API error (retryable): status=429, url=https://api.hubapi.com/crm/v3/objects/contacts",
        "Hubspot API malformed JSON response (retryable): url=https://api.hubapi.com/crm/v3/objects/deals",
        "Hubspot search error (retryable): status=503, url=https://api.hubapi.com/crm/v3/objects/contacts/search",
        "Hubspot search malformed JSON response (retryable): url=https://api.hubapi.com/crm/v3/objects/deals/search",
        "Hubspot v4 associations error (retryable): status=500, "
        "url=https://api.hubapi.com/crm/v4/associations/contacts/deals/batch/read",
        "Hubspot v4 associations malformed JSON response (retryable): "
        "url=https://api.hubapi.com/crm/v4/associations/contacts/deals/batch/read",
        # auth.hubspot_refresh_access_token, exhausted after tenacity's 5 in-process attempts
        "You have reached your rate limit.",
        # auth.hubspot_refresh_access_token, raised verbatim while HubSpot migrates a portal
        "Migration in progress and the portal is not available for access.",
    ],
)
def test_transient_http_error_is_retryable(error_msg: str) -> None:
    patterns = HubspotSource().get_retryable_errors()
    assert any(pattern in error_msg for pattern in patterns), (
        f"HubSpot error {error_msg!r} did not match any retryable pattern"
    )


class TestApiVersion:
    def test_all_versions_supported(self) -> None:
        assert set(HubspotSource().supported_versions) == {
            HUBSPOT_API_VERSION_V3,
            HUBSPOT_API_VERSION_2026_03,
            HUBSPOT_API_VERSION_2026_09,
        }

    @pytest.mark.parametrize(
        "pin,expected",
        [
            (None, HUBSPOT_API_VERSION_2026_09),
            (HUBSPOT_API_VERSION_V3, HUBSPOT_API_VERSION_V3),
            (HUBSPOT_API_VERSION_2026_03, HUBSPOT_API_VERSION_2026_03),
            (HUBSPOT_API_VERSION_2026_09, HUBSPOT_API_VERSION_2026_09),
        ],
    )
    def test_source_for_pipeline_threads_resolved_version(self, pin: str | None, expected: str) -> None:
        src = HubspotSource()
        old_config = HubspotSourceOldConfig.from_dict(
            {"hubspot_secret_key": "secret", "hubspot_refresh_token": "refresh"}
        )
        inputs = _make_inputs(should_use_incremental_field=False, api_version=pin)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source.hubspot_source",
                return_value=MagicMock(),
            ) as hubspot_source_mock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.hubspot.source.hubspot_access_token_is_valid",
                return_value=True,
            ),
        ):
            src.source_for_pipeline(old_config, MagicMock(), inputs)

        assert hubspot_source_mock.call_args.kwargs["api_version"] == expected
