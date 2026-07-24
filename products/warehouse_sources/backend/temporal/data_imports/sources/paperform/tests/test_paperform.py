import json
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.paperform import (
    PAGE_SIZE,
    PaperformResumeConfig,
    _format_after_date,
    paperform_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import (
    ENDPOINTS,
    PAPERFORM_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module; validate_credentials
# builds its own tracked session in the paperform module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
PAPERFORM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.paperform.paperform.make_tracked_session"
)
# tenacity sleeps between retries; patch it so the retry-path test doesn't actually wait.
TENACITY_SLEEP_PATCH = "tenacity.nap.time.sleep"


def _resp(results_key: str, items: list[dict[str, Any]], *, has_more: bool = False, status: int = 200) -> Response:
    body = {"status": "ok", "results": {results_key: items}, "has_more": has_more, "total": len(items)}
    resp = Response()
    resp.status_code = status
    resp.url = "https://api.paperform.co/v1/forms"
    resp._content = json.dumps(body).encode()
    return resp


def _raw_resp(body: Any, *, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = "https://api.paperform.co/v1/forms"
    resp._content = json.dumps(body).encode()
    return resp


class _FakeManager:
    def __init__(self, state: PaperformResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[PaperformResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> PaperformResumeConfig | None:
        return self._state

    def save_state(self, data: PaperformResumeConfig) -> None:
        self.saved.append(data)


def _capture(session: mock.MagicMock, responses: list[Response]) -> list[tuple[str, dict[str, Any]]]:
    """Wire a mock session and capture each request's (url, params) AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so a copy must be taken as
    each request is prepared rather than inspected after the run.
    """
    session.headers = {}
    calls: list[tuple[str, dict[str, Any]]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        calls.append((request.url, dict(request.params or {})))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return calls


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _build(
    manager: _FakeManager,
    endpoint: str,
    responses: list[Response],
    MockSession: mock.MagicMock,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    session = MockSession.return_value
    calls = _capture(session, responses)
    response = paperform_source(
        api_key="pf-key",
        endpoint=endpoint,
        team_id=1,
        job_id="job",
        resumable_source_manager=manager,  # type: ignore[arg-type]
        **kwargs,
    )
    return _rows(response), calls


class TestTopLevel:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_yields_and_stops(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        rows, calls = _build(manager, "forms", [_resp("forms", [{"id": "f1"}, {"id": "f2"}])], MockSession)

        assert rows == [{"id": "f1"}, {"id": "f2"}]
        assert len(calls) == 1
        assert calls[0][1] == {"limit": PAGE_SIZE, "sort": "ASC"}
        # has_more is false, so no resume state is persisted.
        assert manager.saved == []

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_after_id_cursor_until_has_more_false(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        rows, calls = _build(
            manager,
            "forms",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}], has_more=True),
                _resp("forms", [{"id": "f3"}]),
            ],
            MockSession,
        )

        assert [r["id"] for r in rows] == ["f1", "f2", "f3"]
        # Page one carries no cursor; page two advances on the last id of page one.
        assert "after_id" not in calls[0][1]
        assert calls[1][1]["after_id"] == "f2"
        # Every page requests the largest page size in stable ascending creation order.
        assert all(params["limit"] == PAGE_SIZE and params["sort"] == "ASC" for _url, params in calls)
        # Checkpoint saved after the first page (points at the next page), then pagination ends.
        assert [s.cursor for s in manager.saved] == ["f2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_cursor(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager(PaperformResumeConfig(cursor="f2"))
        rows, calls = _build(manager, "forms", [_resp("forms", [{"id": "f3"}])], MockSession)

        assert rows == [{"id": "f3"}]
        # The resumed run starts at the saved cursor rather than re-fetching page one.
        assert calls[0][1]["after_id"] == "f2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_results_key_fails_loud(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        # A 200 body without the expected results key means the response shape changed.
        with pytest.raises(ValueError, match="matched nothing"):
            _build(manager, "forms", [_raw_resp({"status": "ok", "results": {}})], MockSession)


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_injects_form_id_and_paginates_each_form(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        rows, calls = _build(
            manager,
            "submissions",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("submissions", [{"id": "s1"}, {"id": "s2"}], has_more=True),
                _resp("submissions", [{"id": "s3"}]),
                _resp("submissions", [{"id": "s4"}]),
            ],
            MockSession,
        )

        assert rows == [
            {"form_id": "f1", "id": "s1"},
            {"form_id": "f1", "id": "s2"},
            {"form_id": "f1", "id": "s3"},
            {"form_id": "f2", "id": "s4"},
        ]
        # Fan-out progress is checkpointed so a crash resumes mid-stream.
        assert manager.saved
        assert manager.saved[-1].fanout_state is not None

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_skips_completed_forms(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager(
            PaperformResumeConfig(
                fanout_state={
                    "completed": ["/forms/f1/submissions"],
                    "current": "/forms/f2/submissions",
                    "child_state": {"cursor": "s9"},
                }
            )
        )
        rows, calls = _build(
            manager,
            "submissions",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("submissions", [{"id": "s10"}]),
            ],
            MockSession,
        )

        # f1 was fully synced before the crash and must not be re-fetched; f2 resumes at its cursor.
        assert rows == [{"form_id": "f2", "id": "s10"}]
        urls = [url for url, _params in calls]
        assert "https://api.paperform.co/v1/forms/f1/submissions" not in urls
        submission_call = next(params for url, params in calls if url.endswith("/forms/f2/submissions"))
        assert submission_call["after_id"] == "s9"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_old_shape_resume_state_restarts_fresh(self, MockSession: mock.MagicMock) -> None:
        # Resume state written before the migration only bookmarked a form id; it can't seed the
        # framework fan-out, so the whole fan-out restarts (the merge dedupes re-pulled rows).
        manager = _FakeManager(PaperformResumeConfig(cursor="s9", form_id="deleted-form"))
        rows, _calls = _build(
            manager,
            "submissions",
            [
                _resp("forms", [{"id": "f1"}]),
                _resp("submissions", [{"id": "s1"}]),
            ],
            MockSession,
        )

        assert rows == [{"form_id": "f1", "id": "s1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_paginated_endpoint_fetches_each_form_once(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        rows, calls = _build(
            manager,
            "products",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("products", [{"SKU": "P-1"}]),
                _resp("products", []),
            ],
            MockSession,
        )

        assert rows == [{"form_id": "f1", "SKU": "P-1"}]
        # Non-paginated child requests carry no pagination params.
        product_calls = [params for url, params in calls if url.endswith("/products")]
        assert product_calls == [{}, {}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_watermark_first_page_of_each_form_only(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        _rows_out, calls = _build(
            manager,
            "submissions",
            [
                _resp("forms", [{"id": "f1"}, {"id": "f2"}]),
                _resp("submissions", [{"id": "s1"}], has_more=True),
                _resp("submissions", [{"id": "s2"}]),
                _resp("submissions", []),
            ],
            MockSession,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, 999999, tzinfo=UTC),
        )

        by_url_cursor = {(url, params.get("after_id")): params for url, params in calls}
        # The forms listing that drives the fan-out is never date-filtered.
        assert "after_date" not in by_url_cursor[("https://api.paperform.co/v1/forms", None)]
        # Each form's first page carries the watermark (truncated down to whole seconds)...
        f1_first = by_url_cursor[("https://api.paperform.co/v1/forms/f1/submissions", None)]
        f2_first = by_url_cursor[("https://api.paperform.co/v1/forms/f2/submissions", None)]
        assert f1_first["after_date"] == "2024-01-02T03:04:05Z"
        assert f2_first["after_date"] == "2024-01-02T03:04:05Z"
        # ...and later pages advance purely on after_id (after_id supersedes after_date server-side).
        assert "after_date" not in by_url_cursor[("https://api.paperform.co/v1/forms/f1/submissions", "s1")]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_ignores_stale_watermark(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        # partial_submissions declares no incremental fields, so a leftover watermark must not filter.
        _rows_out, calls = _build(
            manager,
            "partial_submissions",
            [
                _resp("forms", [{"id": "f1"}]),
                _resp("partial-submissions", [{"id": "p1"}]),
            ],
            MockSession,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
        )

        assert all("after_date" not in params for _url, params in calls)


class TestRetryAndErrors:
    @mock.patch(TENACITY_SLEEP_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried(self, MockSession: mock.MagicMock, _sleep: mock.MagicMock) -> None:
        manager = _FakeManager()
        # A 500 is retried by the client; the follow-up 200 completes the page.
        rows, _calls = _build(
            manager,
            "forms",
            [_resp("forms", [], status=500), _resp("forms", [{"id": "f1"}])],
            MockSession,
        )
        assert rows == [{"id": "f1"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises(self, MockSession: mock.MagicMock) -> None:
        manager = _FakeManager()
        with pytest.raises(HTTPError):
            _build(manager, "forms", [_resp("forms", [], status=401)], MockSession)


class TestFormatAfterDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2024, 5, 6, 7, 8, 9, 123456, tzinfo=UTC), "2024-05-06T07:08:09Z"),
            ("naive_datetime_assumed_utc", datetime(2024, 5, 6, 7, 8, 9), "2024-05-06T07:08:09Z"),
            ("string_passthrough", "2024-05-06T07:08:09Z", "2024-05-06T07:08:09Z"),
        ]
    )
    def test_formats_watermark(self, _name: str, value: Any, expected: str) -> None:
        assert _format_after_date(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "Invalid Paperform API key"),
            (
                "forbidden_no_api_plan",
                403,
                False,
                "Your Paperform plan does not include API access. API access requires a Pro, Business, or Agency plan.",
            ),
            ("server_error", 500, False, "Paperform returned HTTP 500"),
        ]
    )
    @mock.patch(PAPERFORM_SESSION_PATCH)
    def test_maps_status_to_message(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_session: mock.MagicMock,
    ) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("pf-key") == (expected_valid, expected_message)

    @mock.patch(PAPERFORM_SESSION_PATCH)
    def test_connection_error_is_not_validated(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        valid, message = validate_credentials("pf-key")
        assert valid is False
        assert message == "Could not connect to Paperform to validate the API key"


class TestSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_shape(self, endpoint: str) -> None:
        config = PAPERFORM_ENDPOINTS[endpoint]
        response = paperform_source(
            api_key="pf-key",
            endpoint=endpoint,
            team_id=1,
            job_id="job",
            resumable_source_manager=_FakeManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_form_scoped_endpoints_include_form_id_in_primary_key(self) -> None:
        # These tables aggregate rows across every form, so per-form identifiers (submission id,
        # field key, SKU, coupon code) are only unique with the parent form id in the key.
        for config in PAPERFORM_ENDPOINTS.values():
            if config.form_scoped:
                assert config.primary_keys[0] == "form_id"
