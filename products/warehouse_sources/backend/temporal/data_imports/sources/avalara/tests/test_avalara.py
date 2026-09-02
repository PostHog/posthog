import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara import (
    AVALARA_ENVIRONMENT_HOSTS,
    RECORDSET_COUNT_PATH,
    AvalaraResumeConfig,
    _build_params,
    _format_filter_date,
    _incremental_config_factory,
    _list_paginator,
    avalara_source,
    base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.avalara.settings import AVALARA_ENDPOINTS

# rest_api_resource builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
AVALARA_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara.make_tracked_session"
)


class TestBaseUrl:
    @parameterized.expand(
        [
            ("production", "https://rest.avatax.com"),
            ("sandbox", "https://sandbox-rest.avatax.com"),
        ]
    )
    def test_known_environments(self, environment: str, expected_host: str) -> None:
        assert base_url(environment) == expected_host
        assert AVALARA_ENVIRONMENT_HOSTS[environment] == expected_host

    def test_unknown_environment_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Avalara environment"):
            base_url("staging")


class TestFormatFilterDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_filter_date(value) == expected


class TestBuildParams:
    def test_full_refresh_only_sets_order_by(self) -> None:
        params = _build_params("modifiedDate", should_use_incremental_field=False, db_incremental_field_last_value=None)
        assert params == {"$orderBy": "modifiedDate ASC"}

    def test_incremental_without_cursor_omits_filter(self) -> None:
        params = _build_params("modifiedDate", should_use_incremental_field=True, db_incremental_field_last_value=None)
        assert params == {"$orderBy": "modifiedDate ASC"}

    def test_incremental_with_cursor_adds_filter(self) -> None:
        params = _build_params(
            "modifiedDate",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params == {
            "$orderBy": "modifiedDate ASC",
            "$filter": "modifiedDate gt '2026-03-04T02:58:14Z'",
        }


class TestIncrementalConfigFactory:
    def test_builds_odata_filter_expression(self) -> None:
        config = _incremental_config_factory("modifiedDate")
        assert config["start_param"] == "$filter"
        convert = config["convert"]
        assert convert is not None
        assert convert(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)) == "modifiedDate gt '2026-03-04T02:58:14Z'"


class TestListPaginator:
    def test_uses_odata_param_names_and_recordset_count(self) -> None:
        paginator = _list_paginator(AVALARA_ENDPOINTS["Companies"])
        assert paginator.offset_param == "$skip"
        assert paginator.limit_param == "$top"
        assert paginator.total_path == RECORDSET_COUNT_PATH
        assert paginator.limit == AVALARA_ENDPOINTS["Companies"].page_size


def _response(
    items: list[dict[str, Any]] | None, *, recordset_count: int | None = None, drop_value_key: bool = False
) -> Response:
    body: dict[str, Any] = {}
    if not drop_value_key:
        body["value"] = items or []
    if recordset_count is not None:
        body["@recordsetCount"] = recordset_count
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AvalaraResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return avalara_source(
        account_id="12345",
        license_key="key",
        environment="production",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestAvalaraSourceNonFanout:
    @mock.patch.object(AVALARA_ENDPOINTS["Companies"], "page_size", 2)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_recordset_count_reached(self, MockSession) -> None:
        # A full (page_size-length) first page is required: OffsetPaginator treats a page shorter
        # than the limit as terminal even when @recordsetCount says more remain.
        session = MockSession.return_value
        snapshots = _wire(
            session,
            [
                _response([{"id": 1}, {"id": 2}], recordset_count=3),
                _response([{"id": 3}], recordset_count=3),
            ],
        )

        rows = _rows(_source("Companies", _make_manager()))

        assert [r["id"] for r in rows] == [1, 2, 3]
        assert session.send.call_count == 2
        assert snapshots[0]["params"]["$skip"] == 0
        assert snapshots[1]["params"]["$skip"] == 2
        assert snapshots[0]["params"]["$orderBy"] == "modifiedDate ASC"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cursor_added_as_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}], recordset_count=1)])

        _rows(
            _source(
                "Companies",
                _make_manager(),
                should_use_incremental_field=True,
                incremental_field="modifiedDate",
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["$filter"] == "modifiedDate gt '2026-03-04T02:58:14Z'"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_never_sends_filter(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 1}], recordset_count=1)])

        _rows(_source("Companies", _make_manager(), should_use_incremental_field=False))

        assert "$filter" not in snapshots[0]["params"]

    @mock.patch.object(AVALARA_ENDPOINTS["Companies"], "page_size", 1)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": 1}], recordset_count=2),
                _response([{"id": 2}], recordset_count=2),
            ],
        )

        manager = _make_manager()
        _rows(_source("Companies", manager))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == AvalaraResumeConfig(next_offset=1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": 2}], recordset_count=2)])

        rows = _rows(_source("Companies", _make_manager(AvalaraResumeConfig(next_offset=1))))

        assert [r["id"] for r in rows] == [2]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["$skip"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], recordset_count=0)])

        manager = _make_manager()
        rows = _rows(_source("Companies", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_value_key_treated_as_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(None, drop_value_key=True)])

        rows = _rows(_source("Companies", _make_manager()))

        assert rows == []
        assert session.send.call_count == 1


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict[str, Any]]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


class TestAvalaraSourceFanout:
    @parameterized.expand(["Transactions", "Nexus", "Customers", "ExemptionCertificates"])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara.build_dependent_resource"
    )
    def test_fanout_wires_selectors_and_page_size_param(self, endpoint: str, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        _source(endpoint, _make_manager())

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] == "$top"
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "value"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "value"
        assert kwargs["fanout"].parent_name == "Companies"
        assert kwargs["fanout"].child_params == {"$orderBy": "modifiedDate ASC"}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara.build_dependent_resource"
    )
    def test_transactions_resolves_on_company_code(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        _source("Transactions", _make_manager())

        fanout = mock_build_dependent_resource.call_args.kwargs["fanout"]
        assert fanout.resolve_param == "companyCode"
        assert fanout.resolve_field == "companyCode"

    @parameterized.expand(["Nexus", "Customers", "ExemptionCertificates"])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara.build_dependent_resource"
    )
    def test_company_scoped_endpoints_resolve_on_company_id(self, endpoint: str, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        _source(endpoint, _make_manager())

        fanout = mock_build_dependent_resource.call_args.kwargs["fanout"]
        assert fanout.resolve_param == "companyId"
        assert fanout.resolve_field == "id"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_transactions_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("Companies", [{"id": 1, "companyCode": "DEFAULT"}]),
            _FakeDltResource("Transactions", [{"id": 100, "code": "TXN-1"}]),
        ]

        response = _source("Transactions", _make_manager())

        rows = list(cast(Iterable[Any], response.items()))
        assert rows == [{"id": 100, "code": "TXN-1"}]
        assert response.primary_keys == ["id"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.avalara.avalara.build_dependent_resource"
    )
    def test_incremental_fanout_uses_incremental_config_factory(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        _source(
            "Transactions",
            _make_manager(),
            should_use_incremental_field=True,
            incremental_field="modifiedDate",
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "modifiedDate"
        assert kwargs["incremental_config_factory"] is _incremental_config_factory


class TestValidateCredentials:
    @mock.patch(AVALARA_SESSION_PATCH)
    def test_authenticated_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(
            status_code=200, json=lambda: {"authenticated": True}
        )
        assert validate_credentials("12345", "key", "production") == (True, None)

    @mock.patch(AVALARA_SESSION_PATCH)
    def test_unauthenticated_ping_reports_bad_credentials(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(
            status_code=200, json=lambda: {"authenticated": False}
        )
        is_valid, message = validate_credentials("12345", "wrong-key", "production")
        assert is_valid is False
        assert message == "Avalara authentication failed. Check your account ID and license key."

    @mock.patch(AVALARA_SESSION_PATCH)
    def test_unexpected_status_code(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=500)
        is_valid, message = validate_credentials("12345", "key", "production")
        assert is_valid is False
        assert message is not None and "500" in message

    @mock.patch(AVALARA_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, message = validate_credentials("12345", "key", "production")
        assert is_valid is False
        assert message is not None and "Could not reach Avalara" in message

    @mock.patch(AVALARA_SESSION_PATCH)
    def test_probes_ping_endpoint_for_selected_environment(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(
            status_code=200, json=lambda: {"authenticated": True}
        )

        validate_credentials("12345", "key", "sandbox")

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://sandbox-rest.avatax.com/api/v2/utilities/ping"
        assert call.kwargs["auth"] == ("12345", "key")

    def test_unknown_environment_fails_without_a_request(self) -> None:
        with mock.patch(AVALARA_SESSION_PATCH) as mock_session:
            is_valid, message = validate_credentials("12345", "key", "staging")
        assert is_valid is False
        assert message is not None and "Unknown Avalara environment" in message
        mock_session.assert_not_called()
