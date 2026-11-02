from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
from unittest.mock import MagicMock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.llamacloud import (
    LlamaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.llama_cloud import (
    LlamaCloudResumeConfig,
    LlamaCloudRetryableError,
    _fetch_page,
    _format_datetime,
    _format_day,
    get_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.source import LlamaCloudSource

# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# tested without sitting through the retry backoff.
_fetch_page_once = _fetch_page.__wrapped__  # type: ignore[attr-defined]


def _page(items: list[dict[str, Any]], next_page_token: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"items": items, "next_page_token": next_page_token, "total_size": len(items)})


class TestLlamaCloudTransport:
    @staticmethod
    def _driver(region: Literal["na", "eu"] = "na") -> SourceDriver:
        return SourceDriver(LlamaCloudSource(), LlamaCloudSourceConfig(api_key="llx-test", region=region))

    @parameterized.expand(
        [
            (None, "https://api.cloud.llamaindex.ai"),
            ("na", "https://api.cloud.llamaindex.ai"),
            ("eu", "https://api.cloud.eu.llamaindex.ai"),
            ("EU", "https://api.cloud.eu.llamaindex.ai"),
        ]
    )
    def test_get_base_url(self, region: str | None, expected: str) -> None:
        assert get_base_url(region) == expected

    def test_get_base_url_rejects_unknown_region(self) -> None:
        with pytest.raises(ValueError, match="region must be one of"):
            get_base_url("apac")

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 123456), "2026-03-01T12:30:45Z"),
            ("aware_datetime", datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC), "2026-03-01T12:30:45Z"),
            ("passthrough_string", "2026-03-01T12:30:45Z", "2026-03-01T12:30:45Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected

    @parameterized.expand(
        [
            ("date", date(2026, 3, 1), "2026-03-01"),
            ("datetime", datetime(2026, 3, 1, 12, 30, 45), "2026-03-01"),
            ("passthrough_string", "2026-03-01", "2026-03-01"),
        ]
    )
    def test_format_day(self, _name: str, value: Any, expected: str) -> None:
        assert _format_day(value) == expected

    def test_get_rows_paginates_with_page_token(self) -> None:
        result = self._driver().run(
            "parse_jobs",
            [
                _page([{"id": "job-1"}], next_page_token="token-1"),
                _page([{"id": "job-2"}], next_page_token=None),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "job-1"}], [{"id": "job-2"}]]
        assert result.requests[0].url.startswith("https://api.cloud.llamaindex.ai/api/v2/parse?")
        assert result.params("page_token") == [None, "token-1"]
        assert result.params("page_size") == ["100", "100"]
        assert result.saved_states == [LlamaCloudResumeConfig(next_page_token="token-1")]

    def test_get_rows_resumes_from_saved_page_token(self) -> None:
        result = self._driver().run(
            "parse_jobs", [_page([{"id": "job-3"}])], resume_state=LlamaCloudResumeConfig(next_page_token="token-2")
        )

        assert result.raised is None
        assert result.items == [[{"id": "job-3"}]]
        assert result.params("page_token") == ["token-2"]

    def test_get_rows_incremental_sends_created_at_filter(self) -> None:
        result = self._driver().run(
            "parse_jobs",
            [_page([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("created_at_on_or_after") == ["2026-01-02T03:04:05Z"]

    def test_get_rows_usage_metrics_resolves_organization_id(self) -> None:
        result = self._driver().run(
            "usage_metrics",
            [
                _page([{"id": "project-1", "organization_id": "org-1"}]),
                _page([{"id": "metric-1", "day": "2026-01-01"}], next_page_token=None),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=date(2026, 1, 1),
        )

        assert result.raised is None
        assert result.items == [[{"id": "metric-1", "day": "2026-01-01"}]]
        assert result.paths == ["/api/v2/projects", "/api/v1/beta/usage-metrics"]
        assert [request.origin for request in result.requests] == ["https://api.cloud.llamaindex.ai"] * 2
        assert result.requests[1].param("organization_id") == "org-1"
        assert result.requests[1].param("day_on_or_after") == "2026-01-01"

    def test_get_rows_usage_metrics_fails_without_resolvable_organization(self) -> None:
        result = self._driver().run("usage_metrics", [_page([])])

        assert isinstance(result.raised, ValueError)
        assert "organization id" in str(result.raised)
        assert result.paths == ["/api/v2/projects"]

    def test_get_rows_pipelines_projects_to_documented_fields(self) -> None:
        # Pipeline definitions embed third-party credentials in nested config; only the
        # documented, non-sensitive metadata reaches the warehouse. Includes token/credentials/
        # headers — the generically-named secrets a key-name denylist would let through.
        result = self._driver("eu").run(
            "pipelines",
            [
                ScriptedResponse(
                    json=[
                        {
                            "id": "pipeline-1",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-02T00:00:00Z",
                            "name": "docs",
                            "project_id": "proj-1",
                            "pipeline_type": "MANAGED",
                            "embedding_config": {"component": {"api_key": "sk-secret"}},
                            "data_sink": {
                                "component": {
                                    "token": "bearer-secret",
                                    "credentials": {"password": "hunter2"},
                                    "headers": {"Authorization": "Bearer x"},
                                }
                            },
                        }
                    ]
                )
            ],
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/pipelines"]
        assert result.requests[0].origin == "https://api.cloud.eu.llamaindex.ai"
        assert result.items == [
            [
                {
                    "id": "pipeline-1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "name": "docs",
                    "project_id": "proj-1",
                    "pipeline_type": "MANAGED",
                }
            ]
        ]

    def test_get_rows_extraction_runs_fans_out_over_agents(self) -> None:
        result = self._driver().run(
            "extraction_runs",
            [
                _page([{"id": "agent-1"}, {"id": "agent-2"}], next_page_token="agents-2"),
                _page([{"id": "agent-3"}]),
                ScriptedResponse(
                    json={"items": [{"id": "run-1", "status": "SUCCESS", "data": {"total": 42}}], "total": 2}
                ),
                ScriptedResponse(
                    json={"items": [{"id": "run-2", "status": "ERROR", "extraction_metadata": {"x": 1}}], "total": 2}
                ),
                ScriptedResponse(json={"items": [], "total": 0}),
                ScriptedResponse(
                    json={"items": [{"id": "run-3", "status": "PENDING", "file": {"name": "doc.pdf"}}], "total": 1}
                ),
            ],
        )

        assert result.raised is None
        assert result.items == [
            [{"id": "run-1", "status": "SUCCESS"}],
            [{"id": "run-2", "status": "ERROR"}],
            [{"id": "run-3", "status": "PENDING"}],
        ]
        assert result.paths == ["/api/v1/beta/extraction-agents"] * 2 + ["/api/v1/extraction/runs"] * 4
        assert result.requests[0].origin == "https://api.cloud.llamaindex.ai"
        assert result.requests[1].param("page_token") == "agents-2"
        assert [request.query for request in result.requests[2:]] == [
            {"extraction_agent_id": ("agent-1",), "skip": ("0",), "limit": ("100",)},
            {"extraction_agent_id": ("agent-1",), "skip": ("1",), "limit": ("100",)},
            {"extraction_agent_id": ("agent-2",), "skip": ("0",), "limit": ("100",)},
            {"extraction_agent_id": ("agent-3",), "skip": ("0",), "limit": ("100",)},
        ]
        assert result.saved_states == [
            LlamaCloudResumeConfig(parent_id="agent-1", skip=1),
            LlamaCloudResumeConfig(parent_id="agent-2"),
            LlamaCloudResumeConfig(parent_id="agent-3"),
        ]

    def test_get_rows_extraction_runs_resumes_from_saved_agent_and_skip(self) -> None:
        result = self._driver().run(
            "extraction_runs",
            [
                _page([{"id": "agent-1"}, {"id": "agent-2"}]),
                ScriptedResponse(json={"items": [{"id": "run-5"}], "total": 6}),
            ],
            resume_state=LlamaCloudResumeConfig(parent_id="agent-2", skip=5),
        )

        assert result.raised is None
        assert result.items == [[{"id": "run-5"}]]
        assert result.paths == ["/api/v1/beta/extraction-agents", "/api/v1/extraction/runs"]
        assert result.requests[1].query == {"extraction_agent_id": ("agent-2",), "skip": ("5",), "limit": ("100",)}

    @parameterized.expand([(429,), (500,), (503,)])
    def test_fetch_page_raises_retryable_error(self, status_code: int) -> None:
        session = MagicMock()
        response = MagicMock(status_code=status_code)
        session.get.return_value = response

        with pytest.raises(LlamaCloudRetryableError):
            _fetch_page_once(session, "https://api.cloud.llamaindex.ai/api/v2/parse", {}, {})

    def test_fetch_page_raises_http_error_for_client_errors(self) -> None:
        session = MagicMock()
        response = MagicMock(status_code=401)
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            _fetch_page_once(session, "https://api.cloud.llamaindex.ai/api/v2/parse", {}, {})

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid LlamaCloud API key: Invalid API Key. Please check your region"),
            (500, False, "LlamaCloud API returned an unexpected error"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network(
            always(ScriptedResponse(status=status_code, json={"detail": "Invalid API Key. Please check your region"}))
        ) as network:
            is_valid, message = validate_credentials("llx-test", "na")

        assert is_valid is expected_valid
        if expected_message is None:
            assert message is None
        else:
            assert message is not None and expected_message in message
        assert {request.path for request in network.requests_log} == {"/api/v2/projects"}
        assert network.requests_log[0].param("page_size") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer llx-test"

    def test_validate_credentials_handles_connection_error(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            is_valid, message = validate_credentials("llx-test", "na")

        assert is_valid is False
        assert message is not None and "Could not reach the LlamaCloud API" in message
        assert {request.path for request in network.requests_log} == {"/api/v2/projects"}

    def test_validate_credentials_rejects_unknown_region(self) -> None:
        is_valid, message = validate_credentials("llx-test", "apac")
        assert is_valid is False
        assert message is not None and "region must be one of" in message

    def test_validate_credentials_falls_back_to_response_text_on_non_json_body(self) -> None:
        # A gateway can answer an error with an HTML/text body; parsing it as JSON must not crash.
        with scripted_network([ScriptedResponse(status=401, body=b"Bad Gateway")]) as network:
            is_valid, message = validate_credentials("llx-test", "na")

        assert is_valid is False
        assert message is not None and "Bad Gateway" in message
        assert [request.path for request in network.requests_log] == ["/api/v2/projects"]

    @parameterized.expand(
        [
            # No sort param exists on the API, so incremental endpoints report "desc" — the
            # watermark only persists once the sync completes.
            ("parse_jobs", "desc", ["created_at"]),
            ("usage_metrics", "desc", None),
            ("projects", "asc", None),
            ("pipelines", "asc", None),
        ]
    )
    def test_llama_cloud_source_response_shape(
        self, endpoint: str, expected_sort_mode: str, expected_partition_keys: list[str] | None
    ) -> None:
        if endpoint == "usage_metrics":
            script = [_page([{"id": "project-1", "organization_id": "org-1"}]), _page([])]
        elif endpoint == "pipelines":
            script = [ScriptedResponse(json=[])]
        else:
            script = [_page([])]
        result = self._driver().run(endpoint, script)
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort_mode
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)
