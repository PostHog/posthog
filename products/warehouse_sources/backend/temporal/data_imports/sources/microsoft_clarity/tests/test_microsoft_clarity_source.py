from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import (
    ENDPOINT_NAME,
    NO_DIMENSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.source import (
    MicrosoftClaritySource,
)


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


class TestGetSchemas:
    def test_endpoint_is_append_only_not_incremental(self) -> None:
        # The API has no server-side "since" filter, so this must never be treated as truly
        # incremental — but it should still append daily snapshots rather than overwrite them.
        schema = MicrosoftClaritySource().get_schemas(MagicMock(), team_id=1)[0]
        assert schema.supports_incremental is False
        assert schema.supports_append is True
        assert [f["field"] for f in schema.incremental_fields] == ["synced_at"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "bad_request",
                "400 Client Error: Bad Request for url: https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=3",
            ),
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
