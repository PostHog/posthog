import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops import (
    AirOpsRetryableError,
    _fetch_json,
    _make_session,
    airops_source,
    get_rows,
    validate_credentials,
)


def _response(body: Any, status: int = 200, url: str = "https://api.airops.com/public_api/airops_apps") -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = url
    resp.headers["Content-Type"] = "application/json"
    return resp


def _run(endpoint: str, responses: list[Response]) -> tuple[list[list[dict]], MagicMock]:
    session = MagicMock()
    session.get.side_effect = responses
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops.make_tracked_session",
        return_value=session,
    ):
        batches = list(get_rows(api_key="k", endpoint=endpoint, logger=MagicMock()))
    return batches, session


class TestMakeSession:
    def test_disables_sample_capture_and_redirects(self) -> None:
        # Executions carry free-form inputs/output that can hold user secrets the name-based
        # scrubbers can't recognise, so response capture must stay off; redirects stay pinned off
        # so a credentialed request can't be replayed against another host.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops.make_tracked_session"
        ) as make_session:
            _make_session("secret-key")
        assert make_session.call_args.kwargs["capture"] is False
        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["redact_values"] == ("secret-key",)


class TestGetApps:
    def test_yields_the_unwrapped_array(self) -> None:
        batches, session = _run("apps", [_response([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])])
        assert batches == [[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]]
        assert session.get.call_count == 1

    def test_tolerates_data_envelope(self) -> None:
        # Defensive fallback: the docs describe a bare array, but a beta API could wrap it.
        batches, _ = _run("apps", [_response({"data": [{"id": 1}]})])
        assert batches == [[{"id": 1}]]

    def test_empty_apps_yields_nothing(self) -> None:
        batches, _ = _run("apps", [_response([])])
        assert batches == []


class TestGetExecutions:
    def test_fans_out_over_apps_and_paginates(self) -> None:
        responses = [
            _response([{"id": 10}, {"id": 20}]),  # apps
            _response({"data": [{"id": "e1"}], "meta": {"has_more": True, "cursor": "c1"}}),  # app 10 page 1
            _response({"data": [{"id": "e2"}], "meta": {"has_more": False, "cursor": None}}),  # app 10 page 2
            _response({"data": [{"id": "e3"}], "meta": {"has_more": False}}),  # app 20 page 1
        ]
        batches, session = _run("executions", responses)

        rows = [row for batch in batches for row in batch]
        # Every execution row is stamped with its parent app id so the flattened table can be joined
        # back and the primary key stays meaningful table-wide.
        assert rows == [
            {"id": "e1", "airops_app_id": 10},
            {"id": "e2", "airops_app_id": 10},
            {"id": "e3", "airops_app_id": 20},
        ]
        # 1 apps call + 2 pages for app 10 + 1 page for app 20.
        assert session.get.call_count == 4
        # The second page carries the cursor returned by the first.
        page_two_url = session.get.call_args_list[2].args[0]
        assert "cursor=c1" in page_two_url

    def test_stops_when_cursor_missing_even_if_has_more_true(self) -> None:
        # A truthy has_more with no cursor would otherwise loop forever re-fetching page one.
        responses = [
            _response([{"id": 10}]),
            _response({"data": [{"id": "e1"}], "meta": {"has_more": True}}),
        ]
        batches, session = _run("executions", responses)
        assert [row for batch in batches for row in batch] == [{"id": "e1", "airops_app_id": 10}]
        assert session.get.call_count == 2

    def test_fails_when_app_missing_id(self) -> None:
        # A missing app id must fail loudly rather than silently dropping that app's executions.
        responses = [_response([{"name": "no id"}])]
        with pytest.raises(KeyError):
            _run("executions", responses)

    def test_paginates_when_cursor_present_without_has_more(self) -> None:
        # A response with a cursor but no has_more flag must still page to the next cursor.
        responses = [
            _response([{"id": 10}]),
            _response({"data": [{"id": "e1"}], "meta": {"cursor": "c1"}}),
            _response({"data": [{"id": "e2"}], "meta": {"has_more": False}}),
        ]
        batches, session = _run("executions", responses)
        assert [row for batch in batches for row in batch] == [
            {"id": "e1", "airops_app_id": 10},
            {"id": "e2", "airops_app_id": 10},
        ]
        assert session.get.call_count == 3


class TestGetRowsUnknownEndpoint:
    def test_raises_for_unknown_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Unknown AirOps endpoint"):
            list(get_rows(api_key="k", endpoint="nope", logger=MagicMock()))


class TestFetchJsonStatusHandling:
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses_raise_retryable_error(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status=status)
        # Call the undecorated function so tenacity's retry/backoff doesn't sleep in the test.
        with pytest.raises(AirOpsRetryableError):
            _fetch_json.__wrapped__(session, "https://api.airops.com/x", MagicMock())  # type: ignore[attr-defined]

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_errors_propagate_as_httperror(self, status: int) -> None:
        # 4xx (bad/expired credentials, missing app) must surface as HTTPError so
        # get_non_retryable_errors can match and permanently fail the sync.
        session = MagicMock()
        session.get.return_value = _response({"error": "nope"}, status=status)
        with pytest.raises(requests.HTTPError):
            _fetch_json.__wrapped__(session, "https://api.airops.com/x", MagicMock())  # type: ignore[attr-defined]


class TestValidateCredentials:
    @pytest.mark.parametrize(("status", "expected"), [(200, True), (401, False), (403, False)])
    def test_maps_status_to_bool(self, status: int, expected: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response({}, status=status)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops.make_tracked_session",
            return_value=session,
        ):
            assert validate_credentials("key") is expected

    def test_network_failure_is_false(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.airops.airops.make_tracked_session",
            return_value=session,
        ):
            assert validate_credentials("key") is False


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
        response = airops_source(api_key="k", endpoint=endpoint, logger=MagicMock())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == [partition_key]
        assert response.partition_mode == "datetime"
