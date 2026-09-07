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
    SINGLESTORE_ENDPOINTS,
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

    def test_empty_array_yields_no_rows(self) -> None:
        rows, _ = _run(REGIONS_ENDPOINT, [_response(200, [])])
        assert rows == []

    def test_single_object_endpoint_yields_one_row(self) -> None:
        # organizations/current returns a bare object, not an array; it must still become one row.
        rows, snapshots = _run(
            ORGANIZATION_ENDPOINT,
            [_response(200, {"orgID": "org1", "name": "Acme", "firewallRanges": ["0.0.0.0/0"]})],
        )
        assert rows == [{"orgID": "org1", "name": "Acme", "firewallRanges": ["0.0.0.0/0"]}]
        assert [s["url"] for s in snapshots] == [f"{SINGLESTORE_BASE_URL}/organizations/current"]


class TestWorkspacesFanOut:
    def test_fans_out_over_every_workspace_group(self) -> None:
        rows, snapshots = _run(
            WORKSPACES_ENDPOINT,
            [
                _response(
                    200,
                    [{"workspaceGroupID": "wg1"}, {"workspaceGroupID": "wg2"}],
                    url=f"{SINGLESTORE_BASE_URL}/workspaceGroups",
                ),
                _response(200, [{"workspaceID": "ws1", "workspaceGroupID": "wg1"}]),
                _response(200, [{"workspaceID": "ws2", "workspaceGroupID": "wg2"}]),
            ],
        )
        assert [r["workspaceID"] for r in rows] == ["ws1", "ws2"]
        assert [s["url"] for s in snapshots] == [
            f"{SINGLESTORE_BASE_URL}/workspaceGroups",
            f"{SINGLESTORE_BASE_URL}/workspaces",
            f"{SINGLESTORE_BASE_URL}/workspaces",
        ]
        assert [s["params"].get("workspaceGroupID") for s in snapshots[1:]] == ["wg1", "wg2"]

    def test_no_workspace_groups_yields_no_workspaces(self) -> None:
        rows, _ = _run(WORKSPACES_ENDPOINT, [_response(200, [], url=f"{SINGLESTORE_BASE_URL}/workspaceGroups")])
        assert rows == []

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

    def test_empty_billing_usage_yields_no_rows(self) -> None:
        rows, _ = _run(BILLING_USAGE_ENDPOINT, [self._billing_response([])])
        assert rows == []

    def test_missing_billing_usage_key_yields_no_rows_rather_than_raising(self) -> None:
        # Documented as a best-effort selector: an unexpected body shape degrades to zero rows
        # instead of failing the sync, since the exact live shape isn't verified against an account.
        rows, _ = _run(BILLING_USAGE_ENDPOINT, [_response(200, {"unexpected": "shape"})])
        assert rows == []

    def test_full_refresh_requests_default_lookback_window(self) -> None:
        _, snapshots = _run(BILLING_USAGE_ENDPOINT, [self._billing_response([])])
        params = snapshots[0]["params"]
        assert params["aggregateBy"] == "day"
        start = datetime.strptime(params["startTime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        end = datetime.strptime(params["endTime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert (end - start).days == 30

    def test_incremental_sync_requests_window_from_last_value(self) -> None:
        last_value = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        _, snapshots = _run(
            BILLING_USAGE_ENDPOINT,
            [self._billing_response([])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
        )
        assert snapshots[0]["params"]["startTime"] == "2026-01-01T12:00:00Z"

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

    def test_probes_organizations_current_with_bearer_auth(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(SESSION_PATCH, lambda *a, **k: session):
            validate_credentials("secret")
        args, kwargs = session.get.call_args
        assert args[0] == f"{SINGLESTORE_BASE_URL}/organizations/current"
        assert kwargs["headers"]["Authorization"] == "Bearer secret"

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

    def test_every_declared_endpoint_has_a_response(self) -> None:
        with mock.patch(SESSION_PATCH, lambda *a, **k: mock.MagicMock(headers={})):
            for endpoint, config in SINGLESTORE_ENDPOINTS.items():
                response = singlestore_source(api_key="k", endpoint=endpoint, team_id=1, job_id="j")
                assert response.primary_keys == config.primary_keys
