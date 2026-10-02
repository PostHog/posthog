import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru import (
    GuruResumeConfig,
    _build_params,
    _ensure_event_id,
    _format_last_modified,
    _normalize_member,
    guru_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guru.settings import GURU_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the guru module.
GURU_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.guru.guru.make_tracked_session"


def _response(items: Any, next_link: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(items).encode()
    if next_link:
        # requests parses `response.links` from the RFC 5988 Link header.
        resp.headers["Link"] = f'<{next_link}>; rel="next-page"'
    return resp


def _whoami_response(team_id: str) -> Response:
    return _response({"team": {"id": team_id}, "tokenType": "API"})


def _redirect(location: str) -> Response:
    resp = Response()
    resp.status_code = 302
    resp.headers["Location"] = location
    resp._content = b""
    return resp


def _make_manager(resume_state: GuruResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session, capturing each request's params and URL AT PREPARE TIME.

    ``request.params``/``request.url`` are mutated in place across pages, so snapshot copies when
    each request is prepared. The returned prepared object carries the real URL so the client's
    SSRF host check runs against it.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return guru_source(
        "user@company.com",
        "token",
        endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatLastModified:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05+00:00"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05+00:00"),
            (date(2024, 1, 2), "2024-01-02T00:00:00+00:00"),
            ("2024-01-02T03:04:05+00:00", "2024-01-02T03:04:05+00:00"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_last_modified(value) == expected


class TestBuildParams:
    def test_incremental_cards_filters_and_sorts_on_cursor_field(self):
        params = _build_params(
            GURU_ENDPOINTS["cards"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastModified",
        )

        assert params["q"] == "lastModified >= 2024-01-01T00:00:00+00:00"
        assert params["sortField"] == "lastModified"
        assert params["sortOrder"] == "asc"
        assert params["queryType"] == "cards"

    def test_incremental_without_last_value_falls_back_to_full_refresh_sort(self):
        params = _build_params(
            GURU_ENDPOINTS["cards"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="lastModified",
        )

        assert "q" not in params
        assert params["sortField"] == "dateCreated"
        assert params["sortOrder"] == "asc"

    def test_full_refresh_cards_sorts_on_stable_creation_date(self):
        params = _build_params(
            GURU_ENDPOINTS["cards"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert "q" not in params
        assert params["sortField"] == "dateCreated"
        assert params["sortOrder"] == "asc"

    @pytest.mark.parametrize(
        "last_value, expected_from_date",
        [
            (datetime(2024, 1, 2, 3, 4, 5, 678901, tzinfo=UTC), "2024-01-02T03:04:05.678+00:00"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000+00:00"),
        ],
    )
    def test_incremental_analytics_uses_from_date_not_gql(self, last_value, expected_from_date):
        params = _build_params(
            GURU_ENDPOINTS["analytics_events"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            incremental_field="eventDate",
        )

        assert params == {"fromDate": expected_from_date}

    def test_full_refresh_analytics_sends_no_from_date(self):
        params = _build_params(
            GURU_ENDPOINTS["analytics_events"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params == {}

    @pytest.mark.parametrize("endpoint", ["collections", "groups", "members", "folders", "tag_categories", "tags"])
    def test_non_incremental_endpoints_have_no_search_params(self, endpoint):
        params = _build_params(
            GURU_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )

        assert params == {}


class TestNormalizeMember:
    def test_copies_nested_user_email_to_top_level(self):
        item = {"user": {"email": "jane@company.com", "firstName": "Jane"}, "groups": []}
        assert _normalize_member(item)["email"] == "jane@company.com"

    def test_keeps_existing_top_level_email(self):
        item = {"email": "top@company.com", "user": {"email": "nested@company.com"}}
        assert _normalize_member(item)["email"] == "top@company.com"

    @pytest.mark.parametrize(
        "item",
        [
            {"user": None},
            {},
        ],
    )
    def test_leaves_items_without_email_untouched(self, item):
        assert _normalize_member(item) == item

    def test_missing_nested_email_raises_keyerror(self):
        # email is the primary key, so a member nesting a user dict without an email must
        # fail loudly rather than produce a row with a null primary key.
        with pytest.raises(KeyError):
            _normalize_member({"user": {"firstName": "Jane"}})


class TestEnsureEventId:
    def test_keeps_vendor_id(self):
        event = {"id": "e1", "type": "card-viewed"}
        assert _ensure_event_id(event) == event

    def test_documented_event_without_id_gets_stable_content_key(self):
        event = {
            "type": "card-viewed",
            "user": "jane@company.com",
            "eventDate": "2016-01-20T03:10:11.351+0000",
            "properties": {"cardId": "c1"},
        }
        other = {**event, "eventDate": "2016-01-20T03:10:12.000+0000"}

        first = _ensure_event_id(event)["id"]

        assert first and first == _ensure_event_id(dict(event))["id"]
        assert first != _ensure_event_id(other)["id"]


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
    @mock.patch(GURU_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("user@company.com", "token") is expected

    @mock.patch(GURU_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("user@company.com", "token") is False

    @mock.patch(GURU_SESSION_PATCH)
    def test_probe_disables_redirects_to_protect_credential(self, mock_session):
        # The Basic-auth credential rides on the probe; the session must be built with redirects
        # pinned off so a redirect can't replay it to the redirect target during validation.
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("user@company.com", "token")
        assert mock_session.call_args.kwargs.get("allow_redirects") is False


class TestGetRows:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_via_link_header(self, MockSession):
        session = MockSession.return_value
        next_url = "https://api.getguru.com/api/v1/collections?token=abc"
        _wire(session, [_response([{"id": "1"}, {"id": "2"}], next_link=next_url), _response([{"id": "3"}])])

        manager = _make_manager()
        rows = _rows(_source("collections", manager))

        assert [row["id"] for row in rows] == ["1", "2", "3"]
        # State is saved only while a next page exists, after the page is yielded.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession):
        session = MockSession.return_value
        _, urls = _wire(session, [_response([{"id": "9"}])])

        resume_url = "https://api.getguru.com/api/v1/collections?token=resume"
        manager = _make_manager(GuruResumeConfig(next_url=resume_url))

        _rows(_source("collections", manager))

        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_next_url_with_foreign_host(self, MockSession):
        # A tampered Link header pointing off-host must not move the credentialed request; the
        # SSRF host pin rejects it loudly rather than silently exfiltrating the Basic auth header.
        session = MockSession.return_value
        evil_url = "http://169.254.169.254/latest/meta-data"
        _wire(session, [_response([{"id": "1"}], next_link=evil_url), _response([{"id": "2"}])])

        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("collections", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_resume_url_with_foreign_host(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"id": "9"}])])

        manager = _make_manager(GuruResumeConfig(next_url="http://169.254.169.254/latest/meta-data"))
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source("collections", manager))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_redirect_response(self, MockSession):
        # Redirects are disabled so a 3xx can't silently move the credentialed request off-host.
        session = MockSession.return_value
        _wire(session, [_redirect("http://169.254.169.254/latest/meta-data")])

        with pytest.raises(ValueError, match="[Rr]edirect"):
            _rows(_source("collections", _make_manager()))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_members_rows_are_normalized(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([{"user": {"email": "jane@company.com"}}])])

        rows = _rows(_source("members", _make_manager()))

        assert rows == [{"user": {"email": "jane@company.com"}, "email": "jane@company.com"}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_request_includes_gql_filter(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_response([])])

        _rows(
            _source(
                "cards",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="lastModified",
            )
        )

        assert params[0]["q"] == "lastModified >= 2024-01-01T00:00:00+00:00"
        assert params[0]["sortField"] == "lastModified"
        assert params[0]["sortOrder"] == "asc"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_stops_without_saving_state(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("cards", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_response_fails_loud(self, MockSession):
        # A 200 body that isn't a bare array means the response shape changed — fail loud rather
        # than wrapping the stray object as a single row.
        session = MockSession.return_value
        _wire(session, [_response({"error": "unexpected"})])

        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("cards", _make_manager()))


class TestTeamScopedEndpoints:
    @mock.patch(GURU_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tags_are_flattened_from_categories_under_resolved_team(self, MockSession, mock_whoami_session):
        mock_whoami_session.return_value.get.return_value = _whoami_response("team-1")
        session = MockSession.return_value
        _, urls = _wire(
            session,
            [
                _response(
                    [
                        {"id": "cat-1", "name": "Fruits", "tags": [{"id": "t1", "value": "Apple"}]},
                        {"id": "cat-2", "name": "Empty", "tags": []},
                    ]
                )
            ],
        )

        rows = _rows(_source("tags", _make_manager()))

        assert urls[0].endswith("/teams/team-1/tagcategories")
        assert rows == [{"categoryId": "cat-1", "categoryName": "Fruits", "id": "t1", "value": "Apple"}]

    @mock.patch(GURU_SESSION_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_analytics_incremental_request_filters_by_from_date(self, MockSession, mock_whoami_session):
        mock_whoami_session.return_value.get.return_value = _whoami_response("team-1")
        session = MockSession.return_value
        params, urls = _wire(session, [_response([{"id": "e1", "eventDate": "2024-01-02T00:00:00.000+0000"}])])

        response = _source(
            "analytics_events",
            _make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="eventDate",
        )
        rows = _rows(response)

        assert urls[0].endswith("/teams/team-1/analytics")
        assert params[0] == {"fromDate": "2024-01-01T00:00:00.000+00:00"}
        assert [row["id"] for row in rows] == ["e1"]
        # Guru documents no order for the export, so the watermark must not checkpoint mid-run.
        assert response.sort_mode == "desc"

    @mock.patch(GURU_SESSION_PATCH)
    def test_whoami_auth_failure_surfaces_as_http_error(self, mock_whoami_session):
        failed = Response()
        failed.status_code = 401
        failed.url = "https://api.getguru.com/api/v1/whoami"
        failed.reason = "Unauthorized"
        mock_whoami_session.return_value.get.return_value = failed

        with pytest.raises(HTTPError, match="401 Client Error: Unauthorized for url: https://api.getguru.com"):
            _source("analytics_events", _make_manager())


class TestFanoutEndpoints:
    @pytest.mark.parametrize(
        "endpoint, parent_id, child_path, child_rows, expected",
        [
            (
                "group_members",
                "g1",
                "/groups/g1/members",
                [{"id": "m1", "user": {"email": "jane@company.com"}}],
                [{"id": "m1", "user": {"email": "jane@company.com"}, "group_id": "g1", "email": "jane@company.com"}],
            ),
            (
                "folder_items",
                "f1",
                "/folders/f1/items",
                [{"id": "c1", "type": "card"}],
                [{"id": "c1", "type": "card", "folder_id": "f1"}],
            ),
        ],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_rows_carry_parent_id(self, MockSession, endpoint, parent_id, child_path, child_rows, expected):
        session = MockSession.return_value
        _, urls = _wire(session, [_response([{"id": parent_id}]), _response(child_rows)])

        response = _source(endpoint, _make_manager())
        rows = _rows(response)

        assert urls[1].endswith(child_path)
        assert rows == expected
        assert all(row[key] is not None for row in rows for key in response.primary_keys)


class TestGuruSourceResponse:
    @pytest.mark.parametrize("endpoint", [name for name, config in GURU_ENDPOINTS.items() if config.fanout is None])
    @mock.patch(GURU_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, mock_whoami_session, endpoint):
        mock_whoami_session.return_value.get.return_value = _whoami_response("team-1")
        config = GURU_ENDPOINTS[endpoint]
        response = _source(endpoint, _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(GURU_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in ("dateCreated", "eventDate")
