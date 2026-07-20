import json
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops import (
    AIROPS_BASE_URL,
    _make_session,
    airops_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientRetryableError,
)

# All AirOps traffic (sync + credential probe) flows through _make_session, which builds its
# tracked session in the airops module — so one patch point covers every request.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops.make_tracked_session"

APPS_URL = f"{AIROPS_BASE_URL}/public_api/airops_apps"


def _response(body: Any, status: int = 200, reason: str | None = None, url: str = APPS_URL) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.reason = reason
    resp.url = url
    resp.headers["Content-Type"] = "application/json"
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's URL, params, and auth headers AT PREPARE
    TIME — the paginator mutates the params dict in place between pages, so a later look at the
    same dict would show the final page's params for every request."""
    session.headers = {}
    seen: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        prepared.headers = {}
        if request.auth is not None:
            request.auth(prepared)
        seen.append(
            {
                "url": request.url,
                "params": dict(request.params or {}),
                "auth_headers": dict(prepared.headers),
            }
        )
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return seen


def _source(endpoint: str) -> SourceResponse:
    return airops_source(api_key="k", endpoint=endpoint, team_id=1, job_id="j")


def _batches(source_response: SourceResponse) -> list[list[dict[str, Any]]]:
    return [list(page) for page in source_response.items()]


class TestMakeSession:
    def test_disables_sample_capture_and_redirects(self) -> None:
        # Executions carry free-form inputs/output that can hold user secrets the name-based
        # scrubbers can't recognise, so response capture must stay off; redirects stay pinned off
        # so a credentialed request can't be replayed against another host.
        with mock.patch(SESSION_PATCH) as make_session:
            _make_session("secret-key")
        assert make_session.call_args.kwargs["capture"] is False
        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)
        assert make_session.call_args.kwargs["headers"] == {"Accept": "application/json"}


class TestApps:
    @mock.patch(SESSION_PATCH)
    def test_yields_the_unwrapped_array(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        seen = _wire(session, [_response([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])])

        batches = _batches(_source("apps"))

        assert batches == [[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]]
        # The apps endpoint has no pagination — exactly one request.
        assert session.send.call_count == 1
        assert seen[0]["url"] == APPS_URL
        # The bearer token is applied by the framework auth at prepare time (so it's redacted).
        assert seen[0]["auth_headers"]["Authorization"] == "Bearer k"

    @mock.patch(SESSION_PATCH)
    def test_empty_apps_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        _wire(MockSession.return_value, [_response([])])
        assert _batches(_source("apps")) == []

    @mock.patch(SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession: mock.MagicMock) -> None:
        # The documented shape is a bare array; a 200 with anything else means the response shape
        # changed — fail loud rather than silently syncing 0 (or garbage) rows.
        _wire(MockSession.return_value, [_response({"data": [{"id": 1}]})])
        with pytest.raises(ValueError, match="list response body"):
            _batches(_source("apps"))


class TestExecutions:
    @mock.patch(SESSION_PATCH)
    def test_fans_out_over_apps_and_paginates(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        seen = _wire(
            session,
            [
                _response([{"id": 10}, {"id": 20}]),  # apps
                _response({"data": [{"id": "e1"}], "meta": {"has_more": True, "cursor": "c1"}}),  # app 10 page 1
                _response({"data": [{"id": "e2"}], "meta": {"has_more": False, "cursor": None}}),  # app 10 page 2
                _response({"data": [{"id": "e3"}], "meta": {"has_more": False}}),  # app 20 page 1
            ],
        )

        batches = _batches(_source("executions"))

        rows = [row for batch in batches for row in batch]
        # Every execution row is stamped with its parent app id so the flattened table can be joined
        # back and the primary key stays meaningful table-wide.
        assert rows == [
            {"id": "e1", "airops_app_id": 10},
            {"id": "e2", "airops_app_id": 10},
            {"id": "e3", "airops_app_id": 20},
        ]
        # 1 apps call + 2 pages for app 10 + 1 page for app 20.
        assert session.send.call_count == 4
        assert [s["url"] for s in seen] == [
            APPS_URL,
            f"{APPS_URL}/10/executions",
            f"{APPS_URL}/10/executions",
            f"{APPS_URL}/20/executions",
        ]
        # Page size is pinned to the endpoint's cap; the second page carries the cursor returned by
        # the first, and a fresh parent starts without one.
        assert seen[1]["params"] == {"items": 100}
        assert seen[2]["params"] == {"items": 100, "cursor": "c1"}
        assert seen[3]["params"] == {"items": 100}

    @mock.patch(SESSION_PATCH)
    def test_stops_when_cursor_missing_even_if_has_more_true(self, MockSession: mock.MagicMock) -> None:
        # A truthy has_more with no cursor would otherwise loop forever re-fetching page one.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 10}]),
                _response({"data": [{"id": "e1"}], "meta": {"has_more": True}}),
            ],
        )

        batches = _batches(_source("executions"))

        assert [row for batch in batches for row in batch] == [{"id": "e1", "airops_app_id": 10}]
        assert session.send.call_count == 2

    @mock.patch(SESSION_PATCH)
    def test_stops_when_has_more_false_even_if_cursor_present(self, MockSession: mock.MagicMock) -> None:
        # An explicit has_more=false ends the app's pagination even when a cursor is echoed back,
        # so the last page isn't paid for twice.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 10}]),
                _response({"data": [{"id": "e1"}], "meta": {"has_more": False, "cursor": "c1"}}),
            ],
        )

        batches = _batches(_source("executions"))

        assert [row for batch in batches for row in batch] == [{"id": "e1", "airops_app_id": 10}]
        assert session.send.call_count == 2

    @mock.patch(SESSION_PATCH)
    def test_paginates_when_cursor_present_without_has_more(self, MockSession: mock.MagicMock) -> None:
        # A response with a cursor but no has_more flag must still page to the next cursor.
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 10}]),
                _response({"data": [{"id": "e1"}], "meta": {"cursor": "c1"}}),
                _response({"data": [{"id": "e2"}], "meta": {"has_more": False}}),
            ],
        )

        batches = _batches(_source("executions"))

        assert [row for batch in batches for row in batch] == [
            {"id": "e1", "airops_app_id": 10},
            {"id": "e2", "airops_app_id": 10},
        ]
        assert session.send.call_count == 3

    @mock.patch(SESSION_PATCH)
    def test_fails_when_app_missing_id(self, MockSession: mock.MagicMock) -> None:
        # A missing app id must fail loudly rather than silently dropping that app's executions.
        _wire(MockSession.return_value, [_response([{"name": "no id"}])])
        with pytest.raises(ValueError, match="field 'id'"):
            _batches(_source("executions"))

    @mock.patch(SESSION_PATCH)
    def test_no_apps_yields_nothing(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])
        assert _batches(_source("executions")) == []
        assert session.send.call_count == 1


class TestUnknownEndpoint:
    def test_raises_for_unknown_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Unknown AirOps endpoint"):
            airops_source(api_key="k", endpoint="nope", team_id=1, job_id="j")


class TestErrorHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    @mock.patch(SESSION_PATCH)
    def test_retryable_statuses_retry_then_raise(self, MockSession: mock.MagicMock, status: int) -> None:
        # 429/5xx are retried by the framework client; once attempts are exhausted the last
        # retryable error is reraised. Patch tenacity's sleep so the retries don't actually wait.
        session = MockSession.return_value
        _wire(session, [_response({}, status=status) for _ in range(5)])

        with (
            mock.patch.object(RESTClient._send_request.retry, "sleep"),  # type: ignore[attr-defined]
            pytest.raises(RESTClientRetryableError),
        ):
            _batches(_source("apps"))
        assert session.send.call_count == 5

    @pytest.mark.parametrize(
        "status, reason",
        [(400, "Bad Request"), (401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")],
    )
    @mock.patch(SESSION_PATCH)
    def test_client_errors_propagate_as_httperror(self, MockSession: mock.MagicMock, status: int, reason: str) -> None:
        # 4xx (bad/expired credentials, missing app) must surface as HTTPError so
        # get_non_retryable_errors can match and permanently fail the sync.
        _wire(MockSession.return_value, [_response({"error": "nope"}, status=status, reason=reason)])
        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _batches(_source("apps"))


class TestValidateCredentials:
    @pytest.mark.parametrize(("status", "expected"), [(200, True), (401, False), (403, False)])
    @mock.patch(SESSION_PATCH)
    def test_maps_status_to_bool(self, MockSession: mock.MagicMock, status: int, expected: bool) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=status)
        assert validate_credentials("key") is expected

    @mock.patch(SESSION_PATCH)
    def test_network_failure_is_false(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("key") is False

    @mock.patch(SESSION_PATCH)
    def test_probes_apps_endpoint_with_bearer_header(self, MockSession: mock.MagicMock) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("key")

        call = MockSession.return_value.get.call_args
        called_url = call.args[0] if call.args else call.kwargs["url"]
        assert called_url == APPS_URL
        assert call.kwargs["headers"]["Authorization"] == "Bearer key"


class TestAirOpsSourceResponse:
    @pytest.mark.parametrize(
        ("endpoint", "partition_key", "primary_keys"),
        [
            ("apps", "created_at", ["id"]),
            # Executions are keyed by (app id, id) because execution ids are scoped per app.
            ("executions", "createdAt", ["airops_app_id", "id"]),
        ],
    )
    def test_partition_and_primary_keys(self, endpoint: str, partition_key: str, primary_keys: list[str]) -> None:
        # Partition on a STABLE creation timestamp (never updated_at), which differs per endpoint.
        response = _source(endpoint)
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
