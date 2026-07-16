from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.llama_cloud import (
    LlamaCloudResumeConfig,
    LlamaCloudRetryableError,
    _fetch_page,
    _format_datetime,
    _format_day,
    get_base_url,
    get_rows,
    llama_cloud_source,
    validate_credentials,
)

TRANSPORT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.llama_cloud"

# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# tested without sitting through the retry backoff.
_fetch_page_once = _fetch_page.__wrapped__  # type: ignore[attr-defined]


class FakeSession:
    """Records each GET's url and a snapshot of its params, returning canned payloads.

    Params must be snapshotted because the transport mutates one params dict across pages.
    """

    def __init__(self, payloads: list[Any]) -> None:
        self._payloads = list(payloads)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, headers: dict[str, str], params: dict[str, Any], timeout: int) -> MagicMock:
        self.calls.append((url, dict(params)))
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = self._payloads.pop(0)
        response.raise_for_status.return_value = None
        return response


def _make_manager(resume_state: Optional[LlamaCloudResumeConfig] = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], next_page_token: str | None = None) -> dict[str, Any]:
    return {"items": items, "next_page_token": next_page_token, "total_size": len(items)}


class TestLlamaCloudTransport:
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
        session = FakeSession(
            [
                _page([{"id": "job-1"}], next_page_token="token-1"),
                _page([{"id": "job-2"}], next_page_token=None),
            ]
        )
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("llx-test", "na", "parse_jobs", MagicMock(), manager))

        assert batches == [[{"id": "job-1"}], [{"id": "job-2"}]]
        assert session.calls[0][0] == "https://api.cloud.llamaindex.ai/api/v2/parse"
        assert "page_token" not in session.calls[0][1]
        assert session.calls[1][1]["page_token"] == "token-1"
        assert session.calls[0][1]["page_size"] == 100

    def test_get_rows_saves_resume_state_after_yield(self) -> None:
        session = FakeSession(
            [
                _page([{"id": "job-1"}], next_page_token="token-1"),
                _page([{"id": "job-2"}], next_page_token=None),
            ]
        )
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            rows = get_rows("llx-test", "na", "parse_jobs", MagicMock(), manager)
            next(rows)
            # Suspended at the first yield: a crash here must re-yield this page on retry,
            # so the resume state can't have been persisted yet.
            manager.save_state.assert_not_called()
            next(rows)

        manager.save_state.assert_called_once_with(LlamaCloudResumeConfig(next_page_token="token-1"))

    def test_get_rows_resumes_from_saved_page_token(self) -> None:
        session = FakeSession([_page([{"id": "job-3"}], next_page_token=None)])
        manager = _make_manager(resume_state=LlamaCloudResumeConfig(next_page_token="token-2"))

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("llx-test", "na", "parse_jobs", MagicMock(), manager))

        assert batches == [[{"id": "job-3"}]]
        assert session.calls[0][1]["page_token"] == "token-2"

    def test_get_rows_incremental_sends_created_at_filter(self) -> None:
        session = FakeSession([_page([], next_page_token=None)])
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            list(
                get_rows(
                    "llx-test",
                    "na",
                    "parse_jobs",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                )
            )

        assert session.calls[0][1]["created_at_on_or_after"] == "2026-01-02T03:04:05Z"

    def test_get_rows_full_refresh_omits_incremental_filter(self) -> None:
        session = FakeSession([_page([{"id": "job-1"}], next_page_token=None)])
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            list(get_rows("llx-test", "na", "parse_jobs", MagicMock(), manager))

        assert "created_at_on_or_after" not in session.calls[0][1]

    def test_get_rows_usage_metrics_resolves_organization_id(self) -> None:
        session = FakeSession(
            [
                _page([{"id": "project-1", "organization_id": "org-1"}]),
                _page([{"id": "metric-1", "day": "2026-01-01"}], next_page_token=None),
            ]
        )
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    "llx-test",
                    "na",
                    "usage_metrics",
                    MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=date(2026, 1, 1),
                )
            )

        assert batches == [[{"id": "metric-1", "day": "2026-01-01"}]]
        assert session.calls[0][0] == "https://api.cloud.llamaindex.ai/api/v2/projects"
        metrics_url, metrics_params = session.calls[1]
        assert metrics_url == "https://api.cloud.llamaindex.ai/api/v1/beta/usage-metrics"
        assert metrics_params["organization_id"] == "org-1"
        assert metrics_params["day_on_or_after"] == "2026-01-01"

    def test_get_rows_usage_metrics_fails_without_resolvable_organization(self) -> None:
        session = FakeSession([_page([])])
        manager = _make_manager()

        with (
            patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session),
            pytest.raises(ValueError, match="organization id"),
        ):
            list(get_rows("llx-test", "na", "usage_metrics", MagicMock(), manager))

    def test_get_rows_pipelines_yields_bare_array_without_pagination(self) -> None:
        session = FakeSession([[{"id": "pipeline-1"}, {"id": "pipeline-2"}]])
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("llx-test", "eu", "pipelines", MagicMock(), manager))

        assert batches == [[{"id": "pipeline-1"}, {"id": "pipeline-2"}]]
        url, params = session.calls[0]
        assert url == "https://api.cloud.eu.llamaindex.ai/api/v1/pipelines"
        assert params == {}

    def test_get_rows_pipelines_projects_to_documented_fields(self) -> None:
        # Pipeline definitions embed third-party credentials in nested config; only the
        # documented, non-sensitive metadata reaches the warehouse. Includes token/credentials/
        # headers — the generically-named secrets a key-name denylist would let through.
        session = FakeSession(
            [
                [
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
            ]
        )
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("llx-test", "eu", "pipelines", MagicMock(), manager))

        assert batches == [
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

    def test_get_rows_sheets_jobs_projects_to_documented_fields(self) -> None:
        # Sheets jobs embed webhook credentials under nested `parameters.webhook_configurations`;
        # only the documented job metadata reaches the warehouse. Exercises the paginated
        # projection path (distinct from the bare-array pipelines endpoint).
        session = FakeSession(
            [
                _page(
                    [
                        {
                            "id": "sheet-1",
                            "created_at": "2026-01-01T00:00:00Z",
                            "updated_at": "2026-01-02T00:00:00Z",
                            "project_id": "proj-1",
                            "user_id": "user-1",
                            "status": "SUCCESS",
                            "success": True,
                            "file_id": "file-1",
                            "regions": [],
                            "worksheet_metadata": {},
                            "errors": [],
                            "parameters": {
                                "webhook_configurations": [
                                    {
                                        "webhook_signing_secret": "whsec-secret",
                                        "webhook_headers": {"Authorization": "Bearer x"},
                                    }
                                ]
                            },
                        }
                    ],
                    next_page_token=None,
                )
            ]
        )
        manager = _make_manager()

        with patch(f"{TRANSPORT_MODULE}.make_tracked_session", return_value=session):
            batches = list(get_rows("llx-test", "eu", "sheets_jobs", MagicMock(), manager))

        assert batches == [
            [
                {
                    "id": "sheet-1",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-02T00:00:00Z",
                    "project_id": "proj-1",
                    "user_id": "user-1",
                    "status": "SUCCESS",
                    "success": True,
                    "file_id": "file-1",
                    "regions": [],
                    "worksheet_metadata": {},
                    "errors": [],
                }
            ]
        ]

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
    @patch(f"{TRANSPORT_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_message: str | None, mock_session: MagicMock
    ) -> None:
        response = MagicMock(status_code=status_code)
        response.json.return_value = {"detail": "Invalid API Key. Please check your region"}
        mock_session.return_value.get.return_value = response

        is_valid, message = validate_credentials("llx-test", "na")

        assert is_valid is expected_valid
        if expected_message is None:
            assert message is None
        else:
            assert message is not None and expected_message in message

    @patch(f"{TRANSPORT_MODULE}.make_tracked_session")
    def test_validate_credentials_handles_connection_error(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, message = validate_credentials("llx-test", "na")

        assert is_valid is False
        assert message is not None and "Could not reach the LlamaCloud API" in message

    def test_validate_credentials_rejects_unknown_region(self) -> None:
        is_valid, message = validate_credentials("llx-test", "apac")
        assert is_valid is False
        assert message is not None and "region must be one of" in message

    @patch(f"{TRANSPORT_MODULE}.make_tracked_session")
    def test_validate_credentials_falls_back_to_response_text_on_non_json_body(self, mock_session: MagicMock) -> None:
        # A gateway can answer an error with an HTML/text body; parsing it as JSON must not crash.
        response = MagicMock(status_code=401)
        response.json.side_effect = ValueError("not json")
        response.text = "Bad Gateway"
        mock_session.return_value.get.return_value = response

        is_valid, message = validate_credentials("llx-test", "na")

        assert is_valid is False
        assert message is not None and "Bad Gateway" in message

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
        response = llama_cloud_source("llx-test", "na", endpoint, MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort_mode
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)
