import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce import (
    BabelforceResumeConfig,
    _base_url,
    _build_params,
    _to_epoch,
    babelforce_source,
    is_environment_valid,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.settings import (
    BABELFORCE_ENDPOINTS,
    ENDPOINTS,
)

# babelforce builds its own hardened session and hands it to the REST client, so the tracked
# session is created (and patched) in the babelforce module itself.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.make_tracked_session"
)


def _make_manager(resume_state: BabelforceResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], current: Optional[int], pages: Optional[int]) -> Response:
    pagination: dict[str, Any] = {"total": 0, "max": 100}
    if current is not None:
        pagination["current"] = current
    if pages is not None:
        pagination["pages"] = pages
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"items": items, "pagination": pagination}).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response], urls: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is one dict the paginator mutates in place across pages, so snapshot a copy
    when each request is prepared rather than inspecting the final state. Pass ``urls`` to collect
    each request's URL alongside them.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        if urls is not None:
            urls.append(request.url)
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            ("2023-11-14T22:13:20.000Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-date", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestEnvironmentValidation:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("services", True),
            ("us-east", True),
            (" services ", True),
            ("My-Env-1", True),
            ("", False),
            ("-leading-dash", False),
            ("evil.example.com", False),
            ("evil/path", False),
            ("host:8443", False),
            ("a b", False),
        ],
    )
    def test_is_environment_valid(self, environment, expected):
        assert is_environment_valid(environment) is expected

    def test_base_url_rejects_invalid_environment(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")

    def test_base_url_environment_becomes_subdomain(self):
        assert _base_url("services") == "https://services.babelforce.com/api/v2"
        assert _base_url("us-east").startswith("https://us-east.babelforce.com/")


class TestBuildParams:
    def test_filter_capable_endpoint_includes_window(self):
        params = _build_params(BABELFORCE_ENDPOINTS["calls"], from_timestamp=1700000000, to_timestamp=1700000100)
        assert params["dateCreated.start"] == 1700000000
        assert params["dateCreated.end"] == 1700000100
        assert params["max"] == 100

    def test_full_refresh_endpoint_never_gets_window(self):
        params = _build_params(BABELFORCE_ENDPOINTS["agents"], from_timestamp=1700000000, to_timestamp=1700000100)
        assert "dateCreated.start" not in params
        assert "dateCreated.end" not in params

    def test_unpaginated_endpoint_omits_the_page_size(self):
        # The outbound and event endpoints document no paging params; sending `max` could cap a
        # response that otherwise carries the whole collection.
        assert _build_params(BABELFORCE_ENDPOINTS["outbound_campaigns"], None, None) == {}

    def test_no_watermark_omits_start(self):
        params = _build_params(BABELFORCE_ENDPOINTS["calls"], from_timestamp=None, to_timestamp=1700000100)
        assert "dateCreated.start" not in params
        assert params["dateCreated.end"] == 1700000100


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("services", "id", "token") is expected

    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("services", "id", "token") is False


class TestSessionHardening:
    @mock.patch(SESSION_PATCH)
    def test_sessions_redact_credentials_and_disable_redirects_and_capture(self, mock_session):
        # The token rides a custom header the sampler's denylist doesn't know and that requests
        # would forward on a cross-host redirect; dropping any of these would leak a usable
        # credential into HTTP samples or to a redirect target. Both the validation probe and the
        # sync path must build the session with all three protections.
        session = mock_session.return_value
        session.get.return_value = mock.MagicMock(status_code=200)
        _wire(session, [_page([], current=1, pages=1)])

        validate_credentials("services", "id", "token")
        _rows(
            babelforce_source(
                "services", "id", "token", "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert len(mock_session.call_args_list) >= 2
        for call in mock_session.call_args_list:
            assert call.kwargs["redact_values"] == ("id", "token")
            assert call.kwargs["allow_redirects"] is False
            assert call.kwargs["capture"] is False


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_paginates_until_last_page(self, mock_session):
        session = mock_session.return_value
        params = _wire(
            session,
            [
                _page([{"id": "1"}, {"id": "2"}], current=1, pages=2),
                _page([{"id": "3"}], current=2, pages=2),
            ],
        )

        manager = _make_manager()
        rows = _rows(
            babelforce_source(
                "services", "id", "token", "agents", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        # First request omits `page` (first-page index is undocumented); second requests page 2.
        assert "page" not in params[0]
        assert params[1]["page"] == 2
        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_page == 2

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_state(self, mock_session):
        session = mock_session.return_value
        params = _wire(session, [_page([{"id": "9"}], current=5, pages=5)])

        manager = _make_manager(BabelforceResumeConfig(next_page=5, params={"max": 100, "dateCreated.end": 1700000100}))
        rows = _rows(
            babelforce_source(
                "services", "id", "token", "calls", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        assert [row["id"] for row in rows] == ["9"]
        # The saved window and page are reused so the resumed run continues the same query.
        assert params[0]["page"] == 5
        assert params[0]["dateCreated.end"] == 1700000100

    @mock.patch(SESSION_PATCH)
    def test_terminates_when_page_param_is_ignored(self, mock_session):
        # If the server ignores `page` and re-serves the same page, the paginator detects the
        # non-advancing `current` and stops — preventing an infinite loop. The repeated page is
        # deduped downstream by primary key.
        session = mock_session.return_value
        _wire(session, [_page([{"id": "1"}], current=1, pages=3), _page([{"id": "1"}], current=1, pages=3)])

        manager = _make_manager()
        rows = _rows(
            babelforce_source("services", "id", "token", "sms", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert session.send.call_count == 2
        assert [row["id"] for row in rows] == ["1", "1"]

    @mock.patch(SESSION_PATCH)
    def test_stops_when_pagination_current_missing(self, mock_session):
        session = mock_session.return_value
        _wire(session, [_page([{"id": "1"}], current=None, pages=None)])

        rows = _rows(
            babelforce_source(
                "services", "id", "token", "agents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert [row["id"] for row in rows] == ["1"]
        assert session.send.call_count == 1

    @mock.patch(SESSION_PATCH)
    def test_empty_response_yields_no_rows(self, mock_session):
        session = mock_session.return_value
        _wire(session, [_page([], current=1, pages=1)])

        manager = _make_manager()
        rows = _rows(
            babelforce_source(
                "services", "id", "token", "calls", team_id=1, job_id="j", resumable_source_manager=manager
            )
        )

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.babelforce.babelforce.time")
    @mock.patch(SESSION_PATCH)
    def test_incremental_run_windows_the_query(self, mock_session, mock_time):
        mock_time.time.return_value = 1700000100
        session = mock_session.return_value
        params = _wire(session, [_page([{"id": "1"}], current=1, pages=1)])

        _rows(
            babelforce_source(
                "services",
                "id",
                "token",
                "calls",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2023-11-14T22:13:20.000Z",
            )
        )

        assert params[0]["dateCreated.start"] == 1700000000
        assert params[0]["dateCreated.end"] == 1700000100


class TestBabelforceSourceResponse:
    @mock.patch(SESSION_PATCH)
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, mock_session, endpoint):
        config = BABELFORCE_ENDPOINTS[endpoint]
        response = babelforce_source(
            "services", "id", "token", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Reporting order is undocumented, so the watermark must only finalize on completion.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", [c for c in BABELFORCE_ENDPOINTS.values() if c.partition_key])
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key == "dateCreated"


# Each fan-out child, the path its parent id resolves into, and the field that id is injected as.
FANOUT_CASES = [
    ("conversation_events", "/conversations/p1/events", "conversationId"),
    ("outbound_leads", "/outbound/lists/p1/leads", "listId"),
    ("outbound_campaign_statistics", "/outbound/campaigns/p1/statistics", "campaignId"),
]


class TestFanout:
    @pytest.mark.parametrize("endpoint, child_path, parent_key", FANOUT_CASES)
    @mock.patch(SESSION_PATCH)
    def test_child_rows_carry_the_parent_key(self, mock_session, endpoint, child_path, parent_key):
        # Child rows are keyed by their parent, so the injected field has to be the one the
        # primary key names - otherwise rows from different parents collide on merge.
        session = mock_session.return_value
        urls: list[str] = []
        _wire(session, [_page([{"id": "p1"}], current=1, pages=1), _page([{"probe": "row"}], current=1, pages=1)], urls)

        rows = _rows(
            babelforce_source(
                "services", "id", "token", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )

        assert urls[1].endswith(child_path)
        assert rows == [{"probe": "row", parent_key: "p1"}]
        assert parent_key in BABELFORCE_ENDPOINTS[endpoint].primary_keys

    @mock.patch(SESSION_PATCH)
    def test_unpaginated_fan_out_reads_one_page_without_paging_params(self, mock_session):
        # Both pages advertise more to come. The outbound endpoints document no `pagination`
        # object and take no `page`/`max` params, so neither is sent and neither is followed.
        session = mock_session.return_value
        params = _wire(session, [_page([{"id": "l1"}], current=1, pages=3), _page([{"id": "d1"}], current=1, pages=3)])

        rows = _rows(
            babelforce_source(
                "services",
                "id",
                "token",
                "outbound_leads",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )

        assert params == [{}, {}]
        assert session.send.call_count == 2
        assert [row["id"] for row in rows] == ["d1"]

    @mock.patch(SESSION_PATCH)
    def test_fan_out_checkpoints_each_parent(self, mock_session):
        session = mock_session.return_value
        _wire(
            session,
            [
                _page([{"id": "c1"}, {"id": "c2"}], current=1, pages=1),
                _page([{"id": "e1"}], current=1, pages=1),
                _page([{"id": "e2"}], current=1, pages=1),
            ],
        )

        manager = _make_manager()
        rows = _rows(
            babelforce_source(
                "services",
                "id",
                "token",
                "conversation_events",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
        )

        assert [row["id"] for row in rows] == ["e1", "e2"]
        assert manager.save_state.call_args.args[0].fanout["completed"] == [
            "/conversations/c1/events",
            "/conversations/c2/events",
        ]

    @mock.patch(SESSION_PATCH)
    def test_fan_out_resume_skips_completed_parents(self, mock_session):
        session = mock_session.return_value
        _wire(
            session,
            [
                _page([{"id": "c1"}, {"id": "c2"}], current=1, pages=1),
                _page([{"id": "e2"}], current=1, pages=1),
            ],
        )

        manager = _make_manager(
            BabelforceResumeConfig(
                fanout={"completed": ["/conversations/c1/events"], "current": None, "child_state": None}
            )
        )
        rows = _rows(
            babelforce_source(
                "services",
                "id",
                "token",
                "conversation_events",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
        )

        # The parent list is re-read, but only the unfinished conversation is fetched again.
        assert [row["id"] for row in rows] == ["e2"]
        assert session.send.call_count == 2
