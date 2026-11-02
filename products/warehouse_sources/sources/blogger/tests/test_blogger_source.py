from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.blogger import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.source import BloggerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blogger import (
    BloggerSourceConfig,
)


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "posts",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestBloggerCredentials:
    @parameterized.expand(
        [
            (
                "bad_request",
                "400 Client Error: Bad Request for url: https://www.googleapis.com/blogger/v3/blogs/1/posts",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = BloggerSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)


class TestBloggerPipelinePlumbing:
    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        captured: dict[str, Any] = {}

        def fake_source(**kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        config = SimpleNamespace(api_key="K", blog_id="BID")
        inputs = _make_inputs(
            schema_name="comments",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="published",
        )
        with patch.object(source_module, "blogger_source", fake_source):
            BloggerSource().source_for_pipeline(config, MagicMock(), inputs)  # type: ignore[arg-type]

        assert captured["api_key"] == "K"
        assert captured["blog_id"] == "BID"
        assert captured["endpoint"] == "comments"
        assert captured["team_id"] == 1
        assert captured["job_id"] == "job-id"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_clears_last_value_when_not_incremental(self) -> None:
        driver = SourceDriver(BloggerSource(), BloggerSourceConfig(api_key="K", blog_id="BID"))
        result = driver.run(
            "posts",
            [ScriptedResponse(json={"items": [{"id": "p1"}]})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        # When the run isn't incremental, the stale watermark must not leak through as a startDate.
        assert result.raised is None
        assert result.rows == [{"id": "p1"}]
        assert result.requests[0].param("startDate") is None
