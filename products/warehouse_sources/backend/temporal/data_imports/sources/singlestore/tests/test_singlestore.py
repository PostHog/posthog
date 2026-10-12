import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.settings import (
    BILLING_USAGE_ENDPOINT,
    ORGANIZATION_ENDPOINT,
    REGIONS_ENDPOINT,
    WORKSPACE_GROUPS_ENDPOINT,
    WORKSPACES_ENDPOINT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.singlestore import (
    SINGLESTORE_BASE_URL,
    singlestore_source,
    validate_credentials,
)

# Every builder in singlestore.py reaches for its own `make_tracked_session(...)` call, so a
# single module-level patch covers the declarative resources and the hand-rolled workspaces client.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.singlestore.make_tracked_session"
)
# tenacity sleeps between retries; patch it so retry-exhaustion tests don't actually wait.
SLEEP_PATCH = "tenacity.nap.time.sleep"


def _response(status: int, body: Any, url: str = f"{SINGLESTORE_BASE_URL}/organizations/current") -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = b"" if body is None else json.dumps(body).encode()
    resp.url = url
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's url + params AT SEND TIME."""
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(endpoint: str, responses: list[Response], **kwargs: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with mock.patch(SESSION_PATCH) as make_session:
        session = mock.MagicMock()
        snapshots = _wire(session, responses)
        make_session.return_value = session
        rows = _rows(singlestore_source(api_key="k", endpoint=endpoint, team_id=1, job_id="j", **kwargs))
    return rows, snapshots


class TestListEndpoints:
    @parameterized.expand(
        [
            (REGIONS_ENDPOINT, f"{SINGLESTORE_BASE_URL}/regions", "regionID"),
            (WORKSPACE_GROUPS_ENDPOINT, f"{SINGLESTORE_BASE_URL}/workspaceGroups", "workspaceGroupID"),
        ]
    )
    def test_yields_dicts_from_raw_array_at_expected_url(self, endpoint: str, expected_url: str, pk: str) -> None:
        rows, snapshots = _run(endpoint, [_response(200, [{pk: "a"}, {pk: "b"}], url=expected_url)])
        assert [r[pk] for r in rows] == ["a", "b"]
        assert [s["url"] for s in snapshots] == [expected_url]

    def test_non_list_response_on_array_endpoint_raises(self) -> None:
        # A malformed body (object instead of array) must fail the sync loudly rather than
        # silently replacing the warehouse table with zero rows.
        with pytest.raises(ValueError):
            _run(REGIONS_ENDPOINT, [_response(200, {"unexpected": "shape"})])


class TestWorkspacesFanOut:
    def test_workspace_group_missing_id_is_skipped(self) -> None:
        # A group row missing its id can't be fanned out into a `workspaceGroupID` filter; skip it
        # rather than sending a request with an empty/garbage value.
        rows, snapshots = _run(
            WORKSPACES_ENDPOINT,
            [
                _response(
                    200,
                    [{"workspaceGroupID": "wg1"}, {"name": "no id"}],
                    url=f"{SINGLESTORE_BASE_URL}/workspaceGroups",
                ),
                _response(200, [{"workspaceID": "ws1", "workspaceGroupID": "wg1"}]),
            ],
        )
        assert [r["workspaceID"] for r in rows] == ["ws1"]
        assert len(snapshots) == 2


class TestBillingUsage:
    def _billing_response(self, groups: list[dict[str, Any]]) -> Response:
        return _response(200, {"billingUsage": groups}, url=f"{SINGLESTORE_BASE_URL}/billing/usage")

    def test_flattens_usage_items_and_stamps_metric_and_description(self) -> None:
        rows, _ = _run(
            BILLING_USAGE_ENDPOINT,
            [
                self._billing_response(
                    [
                        {
                            "metric": "computeCredit",
                            "description": "Compute credits used",
                            "usage": [
                                {
                                    "startTime": "2026-01-01T00:00:00Z",
                                    "endTime": "2026-01-02T00:00:00Z",
                                    "resourceName": "ws1",
                                    "value": "1.5",
                                }
                            ],
                        },
                        {
                            "metric": "storageAvgByte",
                            "description": "Average storage bytes",
                            "usage": [
                                {
                                    "startTime": "2026-01-01T00:00:00Z",
                                    "endTime": "2026-01-02T00:00:00Z",
                                    "resourceName": "ws1",
                                    "value": "1000",
                                }
                            ],
                        },
                    ]
                )
            ],
        )
        assert rows == [
            {
                "startTime": "2026-01-01T00:00:00Z",
                "endTime": "2026-01-02T00:00:00Z",
                "resourceName": "ws1",
                "value": "1.5",
                "metric": "computeCredit",
                "description": "Compute credits used",
            },
            {
                "startTime": "2026-01-01T00:00:00Z",
                "endTime": "2026-01-02T00:00:00Z",
                "resourceName": "ws1",
                "value": "1000",
                "metric": "storageAvgByte",
                "description": "Average storage bytes",
            },
        ]

    @parameterized.expand([(False, "replace"), (True, {"disposition": "merge", "strategy": "upsert"})])
    def test_write_disposition_matches_incremental_flag(
        self, should_use_incremental_field: bool, expected: Any
    ) -> None:
        # Full refresh must replace the table wholesale; an incremental sync must merge on
        # primary_keys instead of duplicating rows already synced by an earlier window.
        with mock.patch(SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            _wire(session, [self._billing_response([])])
            make_session.return_value = session
            response = singlestore_source(
                api_key="k",
                endpoint=BILLING_USAGE_ENDPOINT,
                team_id=1,
                job_id="j",
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC)
                if should_use_incremental_field
                else None,
            )
        resource = cast(Resource, response.items())
        assert resource._hints.get("write_disposition") == expected


class TestRetryAndAuthClassification:
    @mock.patch(SLEEP_PATCH)
    def test_persistent_5xx_raises_after_retries(self, _sleep: Any) -> None:
        with mock.patch(SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.headers = {}
            session.prepare_request.side_effect = lambda request: mock.MagicMock()
            session.send.side_effect = lambda *a, **k: _response(500, {"error": "boom"})
            make_session.return_value = session
            with pytest.raises(Exception):
                _rows(singlestore_source(api_key="k", endpoint=REGIONS_ENDPOINT, team_id=1, job_id="j"))
            assert session.send.call_count > 1

    @parameterized.expand([(401,), (403,)])
    def test_auth_errors_raise_immediately(self, status: int) -> None:
        with mock.patch(SESSION_PATCH) as make_session:
            session = mock.MagicMock()
            session.headers = {}
            session.prepare_request.side_effect = lambda request: mock.MagicMock()
            session.send.side_effect = lambda *a, **k: _response(status, {"error": "denied"})
            make_session.return_value = session
            with pytest.raises(requests.HTTPError):
                _rows(singlestore_source(api_key="k", endpoint=REGIONS_ENDPOINT, team_id=1, job_id="j"))
            assert session.send.call_count == 1


class TestValidateCredentials:
    @parameterized.expand([(200, True), (401, False), (403, False), (429, True), (500, True)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        response = mock.MagicMock(status_code=status)
        session = mock.MagicMock()
        session.get.return_value = response
        with mock.patch(SESSION_PATCH, lambda *a, **k: session):
            ok, error = validate_credentials("k")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_request_exception_does_not_block_creation(self) -> None:
        # An unreachable API is transient, not a credential rejection; a genuine auth failure
        # still surfaces at sync time.
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(SESSION_PATCH, lambda *a, **k: session):
            ok, error = validate_credentials("k")
        assert ok is True
        assert error is None


class TestSourceResponseShape:
    @parameterized.expand(
        [
            (ORGANIZATION_ENDPOINT, ["orgID"]),
            (REGIONS_ENDPOINT, ["regionID"]),
            (WORKSPACE_GROUPS_ENDPOINT, ["workspaceGroupID"]),
            (WORKSPACES_ENDPOINT, ["workspaceID"]),
            (BILLING_USAGE_ENDPOINT, ["metric", "resourceName", "startTime"]),
        ]
    )
    def test_primary_keys_and_sort_mode(self, endpoint: str, expected_pk: list[str]) -> None:
        with mock.patch(SESSION_PATCH, lambda *a, **k: mock.MagicMock(headers={})):
            response = singlestore_source(api_key="k", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode == "asc"
