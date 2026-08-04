import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.onepagecrm import (
    OnepagecrmResumeConfig,
    _to_epoch,
    modified_since_anchor,
    onepagecrm_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ENDPOINTS,
    ONEPAGECRM_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the onepagecrm module.
ONEPAGECRM_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.onepagecrm.make_tracked_session"
)


def _make_manager(resume_state: OnepagecrmResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _list_page(
    data_key: str,
    item_key: str,
    records: list[dict[str, Any]],
    page: int,
    max_page: Optional[int],
) -> Response:
    return _response(
        {
            "status": 0,
            "message": "OK",
            "data": {
                data_key: [{item_key: record} for record in records],
                "total_count": len(records),
                "page": page,
                "per_page": 100,
                "max_page": max_page,
            },
        }
    )


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages (the paginator injects ``page``),
    so snapshot a copy when each request is prepared instead of inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(session_mock: mock.MagicMock, endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return onepagecrm_source(
        "uid",
        "key",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


class TestToEpoch:
    @parameterized.expand(
        [
            (None, None),
            (True, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-timestamp", None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected

    def test_anchor_backs_off_one_second(self):
        assert modified_since_anchor(1700000000) == "1699999999"
        assert modified_since_anchor(None) is None


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_max_page_and_unwraps_records(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _list_page("contacts", "contact", [{"id": "a1"}, {"id": "a2"}], page=1, max_page=2),
                _list_page("contacts", "contact", [{"id": "a3"}], page=2, max_page=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source(session, "contacts", manager))

        assert [r["id"] for r in rows] == ["a1", "a2", "a3"]
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == 100
        assert params[1]["page"] == 2
        # Checkpoint saved after the first page (points at the next page); the last page ends it.
        manager.save_state.assert_called_once_with(OnepagecrmResumeConfig(page=2, modified_since=None))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_sorts_by_stable_creation_field(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_list_page("contacts", "contact", [{"id": "a1"}], page=1, max_page=1)])

        _rows(_source(session, "contacts", _make_manager()))

        assert params[0]["sort_by"] == "created_at"
        assert params[0]["order"] == "asc"
        assert "modified_since" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_run_pins_anchor_across_pages(self, MockSession):
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _list_page("deals", "deal", [{"id": "d1"}], page=1, max_page=2),
                _list_page("deals", "deal", [{"id": "d2"}], page=2, max_page=2),
            ],
        )

        manager = _make_manager()
        _rows(
            _source(
                session,
                "deals",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000,
            )
        )

        for snapshot in params:
            assert snapshot["modified_since"] == "1699999999"
            assert snapshot["sort_by"] == "modified_at"
        manager.save_state.assert_called_once_with(OnepagecrmResumeConfig(page=2, modified_since="1699999999"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page_and_saved_anchor(self, MockSession):
        session = MockSession.return_value
        params = _wire(session, [_list_page("deals", "deal", [{"id": "d9"}], page=5, max_page=5)])

        manager = _make_manager(OnepagecrmResumeConfig(page=5, modified_since="1600000000"))
        _rows(
            _source(
                session,
                "deals",
                manager,
                should_use_incremental_field=True,
                # A fresher watermark must NOT replace the saved anchor: page numbers are only
                # stable for the query the run started with.
                db_incremental_field_last_value=1700000000,
            )
        )

        assert params[0]["page"] == 5
        assert params[0]["modified_since"] == "1600000000"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_terminates_when_max_page_missing(self, MockSession):
        session = MockSession.return_value
        page = _list_page("contacts", "contact", [{"id": "a1"}], page=1, max_page=None)
        body = page.json()
        body["data"].pop("max_page")
        page._content = json.dumps(body).encode()
        _wire(session, [page])

        manager = _make_manager()
        rows = _rows(_source(session, "contacts", manager))

        assert [r["id"] for r in rows] == ["a1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_stops_without_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_list_page("contacts", "contact", [], page=1, max_page=1)])

        manager = _make_manager()
        assert _rows(_source(session, "contacts", manager)) == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("users", {"data": [{"user": {"id": "u1"}}, {"user": {"id": "u2"}}]}, ["u1", "u2"]),
            ("statuses", {"data": [{"status": {"id": "s1"}}]}, ["s1"]),
            ("lead_sources", {"data": [{"id": "advertisement"}, {"id": "web"}]}, ["advertisement", "web"]),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_config_endpoints_yield_bare_array_records(self, endpoint, body, expected_ids, MockSession):
        session = MockSession.return_value
        _wire(session, [_response(body)])

        rows = _rows(_source(session, endpoint, _make_manager()))

        assert [r["id"] for r in rows] == expected_ids
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_raises_loudly(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"status": 0, "message": "OK"})])

        # A 200 body missing the data list means the response shape changed — fail loud.
        with pytest.raises(ValueError, match="matched nothing"):
            _rows(_source(session, "contacts", _make_manager()))


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid OnePageCRM user ID or API key"),
            (403, False, "Invalid OnePageCRM user ID or API key"),
            (500, False, "OnePageCRM returned HTTP 500"),
        ]
    )
    @mock.patch(ONEPAGECRM_SESSION_PATCH)
    def test_status_mapping(self, status_code, expected_valid, expected_message, mock_session):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)

        valid, message = validate_credentials("uid", "key")

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(ONEPAGECRM_SESSION_PATCH)
    def test_connection_error_reports_failure(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")

        valid, message = validate_credentials("uid", "key")

        assert valid is False
        assert message is not None and "Could not connect to OnePageCRM" in message


class TestOnepagecrmSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ONEPAGECRM_ENDPOINTS[endpoint]
        response = _source(mock.MagicMock(), endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @parameterized.expand([(name,) for name, c in ONEPAGECRM_ENDPOINTS.items() if c.partition_key])
    def test_partition_keys_are_stable_creation_fields(self, endpoint):
        assert ONEPAGECRM_ENDPOINTS[endpoint].partition_key == "created_at"
