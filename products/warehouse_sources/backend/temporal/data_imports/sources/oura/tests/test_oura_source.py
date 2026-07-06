from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.oura import source as oura_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.oura import OuraResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.oura.source import OuraSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(token: str = "tok") -> Any:
    return OuraSource().parse_config({"access_token": token})


def _inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "daily_sleep",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert OuraSource().source_type == ExternalDataSourceType.OURA

    def test_config_basics(self) -> None:
        cfg = OuraSource().get_source_config
        assert cfg.name == "Oura"
        assert cfg.category == "Analytics"
        assert cfg.releaseStatus == "alpha"
        # A finished source must be visible — no unreleasedSource flag.
        assert getattr(cfg, "unreleasedSource", None) is None

    def test_single_password_token_field(self) -> None:
        fields = OuraSource().get_source_config.fields
        assert [f.name for f in fields] == ["access_token"]
        token_field = fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.required is True
        assert token_field.type == "password"
        assert token_field.secret is True


class TestGetSchemas:
    def test_lists_every_endpoint(self) -> None:
        schemas = OuraSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("daily_sleep", True),
            ("heartrate", True),
            ("enhanced_tag", True),
            ("personal_info", False),
            ("ring_configuration", False),
        ]
    )
    def test_incremental_support_follows_date_filter(self, endpoint: str, expected: bool) -> None:
        schemas = {s.name: s for s in OuraSource().get_schemas(_config(), team_id=1)}
        assert schemas[endpoint].supports_incremental is expected
        assert schemas[endpoint].supports_append is expected

    def test_names_filter(self) -> None:
        schemas = OuraSource().get_schemas(_config(), team_id=1, names=["daily_sleep", "heartrate"])
        assert {s.name for s in schemas} == {"daily_sleep", "heartrate"}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_create_is_accepted", 403, None, True),
            ("forbidden_for_specific_schema_is_rejected", 403, "daily_sleep", False),
            ("transport_failure", -1, None, False),
        ]
    )
    def test_validation(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        with patch.object(oura_source_module, "probe_endpoint", return_value=status):
            ok, error = OuraSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        if expected_ok:
            assert error is None
        else:
            assert error is not None

    def test_probes_personal_info_at_source_create(self) -> None:
        with patch.object(oura_source_module, "probe_endpoint", return_value=200) as probe:
            OuraSource().validate_credentials(_config(), team_id=1, schema_name=None)
        probe.assert_called_once_with("tok", "/usercollection/personal_info")

    def test_probes_requested_endpoint_for_schema(self) -> None:
        with patch.object(oura_source_module, "probe_endpoint", return_value=200) as probe:
            OuraSource().validate_credentials(_config(), team_id=1, schema_name="heartrate")
        probe.assert_called_once_with("tok", "/usercollection/heartrate")


class TestResumableManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        manager = OuraSource().get_resumable_source_manager(_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OuraResumeConfig


class TestSourceForPipeline:
    def test_passes_incremental_value_only_when_incremental(self) -> None:
        with patch.object(oura_source_module, "oura_source") as mock_source:
            OuraSource().source_for_pipeline(
                _config("secret"),
                MagicMock(),
                _inputs(
                    schema_name="daily_sleep",
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2021-05-01",
                ),
            )
        kwargs = mock_source.call_args.kwargs
        assert kwargs["token"] == "secret"
        assert kwargs["endpoint"] == "daily_sleep"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2021-05-01"

    def test_drops_incremental_value_on_full_refresh(self) -> None:
        with patch.object(oura_source_module, "oura_source") as mock_source:
            OuraSource().source_for_pipeline(
                _config(),
                MagicMock(),
                _inputs(
                    schema_name="daily_sleep",
                    should_use_incremental_field=False,
                    db_incremental_field_last_value="2021-05-01",
                ),
            )
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.ouraring.com/v2/usercollection/sleep",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.ouraring.com/v2/usercollection/heartrate"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        non_retryable = OuraSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.ouraring.com"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.ouraring.com"),
            ("read_timeout", "HTTPSConnectionPool(host='api.ouraring.com', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        non_retryable = OuraSource().get_non_retryable_errors()
        assert not any(key in observed for key in non_retryable)
