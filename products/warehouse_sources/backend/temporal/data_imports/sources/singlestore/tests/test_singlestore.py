import json
from datetime import UTC, datetime
from typing import Any, cast

from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.singlestore import (
    SinglestoreSourceConfig,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.source import SinglestoreSource

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.singlestore.singlestore.make_tracked_session"
)


def _driver() -> SourceDriver:
    return SourceDriver(SinglestoreSource(), SinglestoreSourceConfig(api_key="k"))


def _json(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


def _wire(session: mock.MagicMock, responses: list[Response]) -> None:
    session.headers = {}
    session.prepare_request.side_effect = lambda request: mock.MagicMock()
    session.send.side_effect = responses


def _response(status: int, body: Any) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = b"" if body is None else json.dumps(body).encode()
    resp.url = f"{SINGLESTORE_BASE_URL}/organizations/current"
    return resp


class TestListEndpoints:
    @parameterized.expand(
        [
            (REGIONS_ENDPOINT, f"{SINGLESTORE_BASE_URL}/regions", "regionID"),
            (WORKSPACE_GROUPS_ENDPOINT, f"{SINGLESTORE_BASE_URL}/workspaceGroups", "workspaceGroupID"),
        ]
    )
    def test_yields_dicts_from_raw_array_at_expected_url(self, endpoint: str, expected_url: str, pk: str) -> None:
        result = _driver().run(endpoint, [_json([{pk: "a"}, {pk: "b"}])])
        assert [r[pk] for r in result.rows] == ["a", "b"]
        assert result.urls == [expected_url]

    def test_non_list_response_on_array_endpoint_raises(self) -> None:
        # A malformed body (object instead of array) must fail the sync loudly rather than
        # silently replacing the warehouse table with zero rows.
        result = _driver().run(REGIONS_ENDPOINT, [_json({"unexpected": "shape"})])
        assert isinstance(result.raised, ValueError)


class TestWorkspacesFanOut:
    def test_workspace_group_missing_id_is_skipped(self) -> None:
        # A group row missing its id can't be fanned out into a `workspaceGroupID` filter; skip it
        # rather than sending a request with an empty/garbage value.
        result = _driver().run(
            WORKSPACES_ENDPOINT,
            [
                _json([{"workspaceGroupID": "wg1"}, {"name": "no id"}]),
                _json([{"workspaceID": "ws1", "workspaceGroupID": "wg1"}]),
            ],
        )
        assert [r["workspaceID"] for r in result.rows] == ["ws1"]
        assert len(result.requests) == 2
        assert result.requests[1].param("workspaceGroupID") == "wg1"


class TestBillingUsage:
    def _billing_response(self, groups: list[dict[str, Any]]) -> ScriptedResponse:
        return _json({"billingUsage": groups})

    def test_flattens_usage_items_and_stamps_metric_and_description(self) -> None:
        result = _driver().run(
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
        assert result.rows == [
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
            _wire(session, [_response(200, {"billingUsage": []})])
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
    def test_persistent_5xx_raises_after_retries(self) -> None:
        result = _driver().run(REGIONS_ENDPOINT, always(ScriptedResponse(status=500, json={"error": "boom"})))
        assert result.raised is not None
        assert len(result.requests) > 1

    @parameterized.expand([(401,), (403,)])
    def test_auth_errors_raise_immediately(self, status: int) -> None:
        result = _driver().run(REGIONS_ENDPOINT, [_json({"error": "denied"}, status)])
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand([(429, True), (500, True)])
    def test_status_mapping(self, status: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status))):
            ok, error = validate_credentials("k")
        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_request_exception_does_not_block_creation(self) -> None:
        # An unreachable API is transient, not a credential rejection; a genuine auth failure
        # still surfaces at sync time.
        with scripted_network(always(ConnectionError("boom"))):
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
        result = _driver().run(endpoint, always(ScriptedResponse(json=[])))
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pk
        assert response.sort_mode is None
