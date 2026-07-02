from typing import Any, Literal, cast

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SegmentSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment import SegmentResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.segment.source import SegmentSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(region: str = "api", api_token: str = "tok") -> SegmentSourceConfig:
    return SegmentSourceConfig(api_token=api_token, region=cast(Literal["api", "eu1"], region))


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert SegmentSource().source_type == ExternalDataSourceType.SEGMENT

    def test_config_category_and_release_status(self) -> None:
        config = SegmentSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Intentionally unreleased: the source is shipped behind the flag while it stabilizes.
        assert config.unreleasedSource is True

    def test_config_fields(self) -> None:
        config = SegmentSource().get_source_config
        field_names = {f.name for f in config.fields}
        assert field_names == {"region", "api_token"}

        token_field = next(f for f in config.fields if f.name == "api_token")
        assert isinstance(token_field, SourceFieldInputConfig)
        # The token is a secret and must render as a password input.
        assert token_field.type == "password"
        assert token_field.secret is True

        region_field = next(f for f in config.fields if f.name == "region")
        assert isinstance(region_field, SourceFieldSelectConfig)
        assert {o.value for o in region_field.options} == {"api", "eu1"}
        assert region_field.defaultValue == "api"


class TestGetSchemas:
    def test_returns_all_endpoints(self) -> None:
        schemas = SegmentSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_all_full_refresh(self) -> None:
        # The Public API exposes no server-side timestamp filter on these resources, so nothing is incremental.
        schemas = SegmentSource().get_schemas(_config(), team_id=1)
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_names_filter(self) -> None:
        schemas = SegmentSource().get_schemas(_config(), team_id=1, names=["sources", "labels"])
        assert {s.name for s in schemas} == {"sources", "labels"}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("missing_header", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment.make_tracked_session"
        ) as mock_session:
            response = MagicMock()
            response.status_code = status_code
            mock_session.return_value.get.return_value = response

            ok, error = SegmentSource().validate_credentials(_config(), team_id=1)
            assert ok is expected_ok
            assert (error is None) is expected_ok

    def test_validate_credentials_network_error_is_invalid(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            ok, error = SegmentSource().validate_credentials(_config(), team_id=1)
            assert ok is False
            assert error is not None

    @parameterized.expand([("us", "api"), ("eu", "eu1")])
    def test_validate_credentials_targets_region_host(self, _name: str, region: str) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.segment.make_tracked_session"
        ) as mock_session:
            response = MagicMock()
            response.status_code = 200
            mock_session.return_value.get.return_value = response

            SegmentSource().validate_credentials(_config(region=region), team_id=1)
            called_url = mock_session.return_value.get.call_args.args[0]
            assert region in called_url


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.segmentapis.com/sources"),
            ("forbidden", "403 Client Error: Forbidden for url: https://eu1.api.segmentapis.com/labels"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = SegmentSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.segmentapis.com/sources"),
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.segmentapis.com/sources"),
            ("read_timeout", "HTTPSConnectionPool(host='api.segmentapis.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable_errors = SegmentSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)


class TestResumableManager:
    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        source = SegmentSource()
        inputs = MagicMock()
        manager = source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SegmentResumeConfig


class TestSourceForPipeline:
    def test_plumbs_config_into_transport(self) -> None:
        source = SegmentSource()
        inputs = MagicMock()
        inputs.schema_name = "sources"
        manager = MagicMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.segment.source.segment_source"
        ) as mock_source:
            source.source_for_pipeline(_config(region="eu1", api_token="secret"), manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "secret"
        assert kwargs["region"] == "eu1"
        assert kwargs["endpoint"] == "sources"
        assert kwargs["resumable_source_manager"] is manager


class TestCanonicalDescriptions:
    def test_descriptions_cover_known_endpoints(self) -> None:
        descriptions = SegmentSource().get_canonical_descriptions()
        # Every documented endpoint with a curated description must be a real schema.
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "sources" in descriptions

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_described_columns_are_nonempty(self, endpoint: str) -> None:
        descriptions: dict[str, Any] = SegmentSource().get_canonical_descriptions()
        if endpoint not in descriptions:
            return
        assert descriptions[endpoint].get("description")
