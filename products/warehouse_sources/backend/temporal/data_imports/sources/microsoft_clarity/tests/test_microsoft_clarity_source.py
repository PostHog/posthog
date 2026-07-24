from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import (
    DIMENSION_OPTIONS,
    ENDPOINT_NAME,
    ENDPOINTS,
    NO_DIMENSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.source import (
    MicrosoftClaritySource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config(
    api_token: str = "token",
    num_of_days: str = "1",
    dimension1: str | None = NO_DIMENSION,
    dimension2: str | None = NO_DIMENSION,
    dimension3: str | None = NO_DIMENSION,
) -> Any:
    return SimpleNamespace(
        api_token=api_token,
        num_of_days=num_of_days,
        dimension1=dimension1,
        dimension2=dimension2,
        dimension3=dimension3,
    )


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert MicrosoftClaritySource().source_type == ExternalDataSourceType.MICROSOFTCLARITY

    def test_get_source_config(self) -> None:
        config = MicrosoftClaritySource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ANALYTICS
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.fields is not None
        assert len(config.fields) == 5

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    def test_num_of_days_field_options(self) -> None:
        config = MicrosoftClaritySource().get_source_config
        num_of_days_field = next(f for f in config.fields if f.name == "num_of_days")
        assert isinstance(num_of_days_field, SourceFieldSelectConfig)
        assert num_of_days_field.required is True
        assert num_of_days_field.defaultValue == "1"
        assert {option.value for option in num_of_days_field.options} == {"1", "2", "3"}

    @parameterized.expand([("dimension1",), ("dimension2",), ("dimension3",)])
    def test_dimension_fields_are_optional_with_none_default(self, field_name: str) -> None:
        config = MicrosoftClaritySource().get_source_config
        dimension_field = next(f for f in config.fields if f.name == field_name)
        assert isinstance(dimension_field, SourceFieldSelectConfig)
        assert dimension_field.required is False
        assert dimension_field.defaultValue == NO_DIMENSION
        option_values = {option.value for option in dimension_field.options}
        assert option_values == {NO_DIMENSION, *DIMENSION_OPTIONS}


class TestGetSchemas:
    def test_returns_single_endpoint(self) -> None:
        schemas = MicrosoftClaritySource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert ENDPOINTS == (ENDPOINT_NAME,)

    def test_filters_by_names(self) -> None:
        schemas = MicrosoftClaritySource().get_schemas(MagicMock(), team_id=1, names=[ENDPOINT_NAME])
        assert {s.name for s in schemas} == {ENDPOINT_NAME}

        schemas = MicrosoftClaritySource().get_schemas(MagicMock(), team_id=1, names=["not-a-real-endpoint"])
        assert schemas == []

    def test_endpoint_is_append_only_not_incremental(self) -> None:
        # The API has no server-side "since" filter, so this must never be treated as truly
        # incremental — but it should still append daily snapshots rather than overwrite them.
        schema = MicrosoftClaritySource().get_schemas(MagicMock(), team_id=1)[0]
        assert schema.supports_incremental is False
        assert schema.supports_append is True
        assert [f["field"] for f in schema.incremental_fields] == ["synced_at"]


class TestValidateCredentials:
    def test_success(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(source_module, "validate_clarity_credentials", lambda *a, **k: (True, None))
        valid, error = MicrosoftClaritySource().validate_credentials(_config(), team_id=1)
        assert valid is True
        assert error is None

    def test_failure(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(
            source_module, "validate_clarity_credentials", lambda *a, **k: (False, "Invalid or expired token")
        )
        valid, error = MicrosoftClaritySource().validate_credentials(_config(), team_id=1)
        assert valid is False
        assert error == "Invalid or expired token"

    def test_passes_configured_token(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_validate(token: str) -> tuple[bool, str | None]:
            captured["token"] = token
            return True, None

        monkeypatch.setattr(source_module, "validate_clarity_credentials", fake_validate)
        MicrosoftClaritySource().validate_credentials(_config(api_token="my-token"), team_id=1)
        assert captured["token"] == "my-token"


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://www.clarity.ms/export-data/api/v1/project-live-insights",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://www.clarity.ms/export-data/api/v1/project-live-insights",
            ),
            (
                "quota_exceeded",
                "429 Client Error: Too Many Requests for url: https://www.clarity.ms/export-data/api/v1/project-live-insights",
            ),
        ]
    )
    def test_known_error_is_non_retryable(self, _name: str, observed: str) -> None:
        errors = MicrosoftClaritySource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    def test_transient_error_remains_retryable(self) -> None:
        errors = MicrosoftClaritySource().get_non_retryable_errors()
        observed = "HTTPSConnectionPool(host='www.clarity.ms', port=443): Read timed out."
        assert not any(key in observed for key in errors)


class TestCanonicalDescriptions:
    def test_covers_the_endpoint(self) -> None:
        descriptions = MicrosoftClaritySource().get_canonical_descriptions()
        assert set(descriptions.keys()) == set(ENDPOINTS)
        assert "docs_url" in descriptions[ENDPOINT_NAME]


class TestSourceForPipeline:
    def test_plumbs_config_into_transport(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}
        sentinel = object()

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return sentinel

        monkeypatch.setattr(source_module, "microsoft_clarity_source", fake_source)

        inputs = SimpleNamespace(schema_name=ENDPOINT_NAME, team_id=1, job_id="job", logger=MagicMock())
        result = MicrosoftClaritySource().source_for_pipeline(
            _config(
                api_token="tok", num_of_days="3", dimension1="OS", dimension2=NO_DIMENSION, dimension3=NO_DIMENSION
            ),
            inputs,  # type: ignore[arg-type]
        )

        assert result is sentinel
        assert captured == {
            "token": "tok",
            "num_of_days": "3",
            "dimension1": "OS",
            "dimension2": NO_DIMENSION,
            "dimension3": NO_DIMENSION,
        }
