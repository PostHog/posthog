from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.groq.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.source import GroqSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.groq.source"


def _make_config(api_key: str = "gsk_test") -> Any:
    config = MagicMock()
    config.api_key = api_key
    return config


class TestGroqSource:
    def test_source_type(self) -> None:
        assert GroqSource().source_type == ExternalDataSourceType.GROQ

    def test_source_config_has_single_password_api_key_field(self) -> None:
        config = GroqSource().get_source_config
        assert [f.name for f in config.fields] == ["api_key"]
        (api_key_field,) = config.fields
        assert isinstance(api_key_field, SourceFieldInputConfig)
        # The API key is a secret credential, so it must render as a password input.
        assert api_key_field.type == "password"
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_source_config_stays_unreleased_alpha(self) -> None:
        config = GroqSource().get_source_config
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/groq"

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog with no I/O, so the public docs can render tables.
        assert GroqSource.lists_tables_without_credentials is True

    def test_get_schemas_returns_every_endpoint_as_full_refresh(self) -> None:
        schemas = GroqSource().get_schemas(_make_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Groq exposes no server-side timestamp filter, so nothing supports incremental/append.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_exposes_primary_keys(self) -> None:
        schemas = {s.name: s for s in GroqSource().get_schemas(_make_config(), team_id=1)}
        assert schemas["batches"].detected_primary_keys == ["id"]
        assert schemas["files"].detected_primary_keys == ["id"]
        assert schemas["models"].detected_primary_keys == ["id"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = GroqSource().get_schemas(_make_config(), team_id=1, names=["batches", "models"])
        assert {s.name for s in schemas} == {"batches", "models"}

    @parameterized.expand(
        [
            ("valid", True, 200, True, None),
            ("invalid_key", False, 401, False, "Invalid Groq API key"),
            (
                "forbidden",
                False,
                403,
                False,
                "Your Groq API key is missing the permissions needed to sync this data",
            ),
            ("other_failure", False, 500, False, "Could not connect to Groq with the provided API key"),
            ("no_connection", False, None, False, "Could not connect to Groq with the provided API key"),
        ]
    )
    def test_validate_credentials(
        self,
        _name: str,
        probe_ok: bool,
        probe_status: int | None,
        expected_ok: bool,
        expected_message: str | None,
    ) -> None:
        with patch(f"{MODULE}.validate_groq_credentials", return_value=(probe_ok, probe_status)):
            ok, message = GroqSource().validate_credentials(_make_config(), team_id=1)
        assert ok is expected_ok
        assert message == expected_message

    def test_source_for_pipeline_plumbs_key_and_endpoint(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "batches"
        inputs.logger = MagicMock()
        with patch(f"{MODULE}.groq_source") as source_fn:
            GroqSource().source_for_pipeline(_make_config("gsk_abc"), inputs)
        source_fn.assert_called_once()
        kwargs = source_fn.call_args.kwargs
        assert kwargs["api_key"] == "gsk_abc"
        assert kwargs["endpoint"] == "batches"

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.groq.com"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.groq.com"),
        ]
    )
    def test_non_retryable_errors_cover_auth_failures(self, _name: str, expected_key: str) -> None:
        errors = GroqSource().get_non_retryable_errors()
        assert expected_key in errors
        assert errors[expected_key]

    def test_canonical_descriptions_keyed_by_endpoint(self) -> None:
        descriptions = GroqSource().get_canonical_descriptions()
        # Every documented entry must map to a real endpoint or the docs render orphaned tables.
        assert set(descriptions.keys()) <= set(ENDPOINTS)
        assert {"batches", "files", "models"} <= set(descriptions.keys())
