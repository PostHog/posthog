from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source import DigitalOceanSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DigitalOceanSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> DigitalOceanSourceConfig:
    return DigitalOceanSourceConfig(api_key="dop_v1_token")


class TestDigitalOceanSourceConfig:
    def test_source_type(self) -> None:
        assert DigitalOceanSource().source_type == ExternalDataSourceType.DIGITALOCEAN

    def test_config_exposes_single_password_token_field(self) -> None:
        config = DigitalOceanSource().get_source_config
        assert [f.name for f in config.fields] == ["api_key"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True

    def test_stays_gated_in_alpha(self) -> None:
        # The source ships hidden (unreleasedSource) and labelled alpha until it's validated
        # against a live account; a regression that flips either would expose it prematurely.
        config = DigitalOceanSource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_docs_url_matches_icon_slug(self) -> None:
        config = DigitalOceanSource().get_source_config
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/digitalocean"
        assert config.iconPath == "/static/services/digitalocean.svg"


class TestDigitalOceanGetSchemas:
    def test_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = DigitalOceanSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # DigitalOcean has no server-side timestamp filter, so nothing may advertise incremental
        # sync — otherwise "incremental" runs re-page the whole endpoint at full API cost.
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_filters_by_names(self) -> None:
        schemas = DigitalOceanSource().get_schemas(_config(), team_id=1, names=["droplets"])
        assert [s.name for s in schemas] == ["droplets"]

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True powers the public docs Supported tables section;
        # it must produce an entry per endpoint from the static catalog with no network call.
        tables = DigitalOceanSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


class TestDigitalOceanValidateCredentials:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.validate_digitalocean_credentials",
        return_value=(True, 200),
    )
    def test_accepts_valid_token(self, _mock: MagicMock) -> None:
        assert DigitalOceanSource().validate_credentials(_config(), team_id=1) == (True, None)

    @pytest.mark.parametrize("status_code", [401, 403])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.validate_digitalocean_credentials"
    )
    def test_auth_rejection_says_token_invalid(self, mock_validate: MagicMock, status_code: int) -> None:
        mock_validate.return_value = (False, status_code)
        valid, error = DigitalOceanSource().validate_credentials(_config(), team_id=1)
        assert not valid
        assert error is not None
        assert "rejected the API token" in error

    @pytest.mark.parametrize("status_code", [429, 500, 503, None])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.validate_digitalocean_credentials"
    )
    def test_transient_failure_does_not_blame_the_token(
        self, mock_validate: MagicMock, status_code: int | None
    ) -> None:
        # A rate limit, server error, or transport failure is not proof the token is bad; the
        # message must ask the user to retry rather than tell them to regenerate a good token.
        mock_validate.return_value = (False, status_code)
        valid, error = DigitalOceanSource().validate_credentials(_config(), team_id=1)
        assert not valid
        assert error is not None
        assert "rejected the API token" not in error


class TestDigitalOceanSourceForPipeline:
    @pytest.mark.parametrize(
        "endpoint,expected_pk,expects_partition",
        [
            pytest.param("droplets", ["id"], True, id="droplets_id_pk_partitioned"),
            pytest.param("domains", ["name"], False, id="domains_name_pk_no_partition"),
            pytest.param("reserved_ips", ["ip"], False, id="reserved_ips_ip_pk_no_partition"),
            pytest.param(
                "billing_history",
                ["date", "type", "amount", "description"],
                False,
                id="billing_history_composite_pk",
            ),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.digitalocean_source")
    def test_plumbs_primary_keys_and_partitioning(
        self, mock_source: MagicMock, endpoint: str, expected_pk: list[str], expects_partition: bool
    ) -> None:
        resource = MagicMock()
        resource.name = endpoint
        resource.column_hints = None
        mock_source.return_value = resource

        inputs = MagicMock()
        inputs.schema_name = endpoint
        inputs.team_id = 1
        inputs.job_id = "job-1"

        response = DigitalOceanSource().source_for_pipeline(_config(), inputs)

        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        if expects_partition:
            # Partition only on the stable created_at timestamp, never on keyless resources.
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["created_at"]
        else:
            assert response.partition_mode is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.source.digitalocean_source")
    def test_passes_token_and_endpoint_through(self, mock_source: MagicMock) -> None:
        resource = MagicMock()
        resource.name = "droplets"
        resource.column_hints = None
        mock_source.return_value = resource

        inputs = MagicMock()
        inputs.schema_name = "droplets"
        inputs.team_id = 7
        inputs.job_id = "job-42"

        DigitalOceanSource().source_for_pipeline(_config(), inputs)

        _, kwargs = mock_source.call_args
        assert kwargs == {
            "api_key": "dop_v1_token",
            "endpoint": "droplets",
            "team_id": 7,
            "job_id": "job-42",
        }


class TestDigitalOceanNonRetryableErrors:
    @pytest.mark.parametrize("status", ["401", "403"])
    def test_auth_errors_are_non_retryable(self, status: str) -> None:
        errors = DigitalOceanSource().get_non_retryable_errors()
        assert any(status in key for key in errors)

    def test_error_keys_scope_to_base_host(self) -> None:
        # Matching the base host (not a per-request URL) keeps the match stable across endpoints.
        errors = DigitalOceanSource().get_non_retryable_errors()
        assert all("https://api.digitalocean.com" in key for key in errors)


class TestDigitalOceanCanonicalDescriptions:
    def test_descriptions_key_on_real_endpoints(self) -> None:
        # Canonical descriptions are keyed by schema name; a typo'd key silently falls back to
        # LLM enrichment instead of the curated text, so keep the keys inside the endpoint set.
        descriptions = DigitalOceanSource().get_canonical_descriptions()
        assert set(descriptions.keys()) <= set(ENDPOINTS)

    def test_covers_headline_infrastructure_endpoints(self) -> None:
        descriptions: dict[str, Any] = dict(DigitalOceanSource().get_canonical_descriptions())
        for endpoint in ("droplets", "databases", "kubernetes_clusters"):
            assert descriptions[endpoint]["columns"]
