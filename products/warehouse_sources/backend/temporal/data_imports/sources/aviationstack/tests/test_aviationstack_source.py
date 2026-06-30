from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.aviationstack import (
    AviationstackResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source import AviationstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _make_config(access_key: str = "key") -> Any:
    config = MagicMock()
    config.access_key = access_key
    return config


class TestAviationstackSource:
    def test_source_type(self) -> None:
        assert AviationstackSource().source_type == ExternalDataSourceType.AVIATIONSTACK

    def test_source_config_has_single_access_key_field(self) -> None:
        config = AviationstackSource().get_source_config
        assert [f.name for f in config.fields] == ["access_key"]
        access_key_field = config.fields[0]
        assert isinstance(access_key_field, SourceFieldInputConfig)
        # The access key is a secret credential, so it must render as a password input.
        assert access_key_field.type == "password"
        assert access_key_field.secret is True
        assert access_key_field.required is True

    def test_source_config_stays_unreleased_alpha(self) -> None:
        config = AviationstackSource().get_source_config
        assert config.unreleasedSource is True
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aviationstack"

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = AviationstackSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # aviationstack has no server-side updated-at cursor, so nothing supports incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = AviationstackSource().get_schemas(_make_config(), team_id=1, names=["airlines", "airports"])
        assert {s.name for s in schemas} == {"airlines", "airports"}

    @parameterized.expand(
        [
            ("valid", True, True, None),
            ("invalid", False, False, "Invalid aviationstack access key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, expected_message: str | None
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.aviationstack.source.validate_aviationstack_credentials",
            return_value=probe_result,
        ):
            ok, message = AviationstackSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = MagicMock()
        inputs.logger = MagicMock()
        manager = AviationstackSource().get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is AviationstackResumeConfig

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "airlines"
        inputs.logger = MagicMock()
        manager = MagicMock()

        response = AviationstackSource().source_for_pipeline(_make_config("abc"), manager, inputs)

        assert response.name == "airlines"
        # Reference tables carry a stable row id.
        assert response.primary_keys == ["id"]

    def test_source_for_pipeline_keyless_for_flight_feeds(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "flights"
        inputs.logger = MagicMock()
        response = AviationstackSource().source_for_pipeline(_make_config(), MagicMock(), inputs)
        assert response.primary_keys is None

    @parameterized.expand(
        [
            ("http_unauthorized", "401 Client Error: Unauthorized for url: https://api.aviationstack.com"),
            ("body_invalid_key", "aviationstack API error [invalid_access_key]"),
            ("body_usage_limit", "aviationstack API error [usage_limit_reached]"),
            ("body_function_restricted", "aviationstack API error [function_access_restricted]"),
        ]
    )
    def test_non_retryable_errors_cover_permanent_failures(self, _name: str, expected_key: str) -> None:
        errors = AviationstackSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = AviationstackSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert "flights" in descriptions
        assert "airlines" in descriptions
