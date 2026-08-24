import json
import datetime
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.harvest import (
    HARVEST_API_HOST,
    HARVEST_USER_AGENT,
    HarvestResumeConfig,
    _to_iso8601,
    harvest_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.harvest.settings import (
    ENDPOINTS,
    HARVEST_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the harvest module.
HARVEST_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.harvest.harvest.make_tracked_session"
)


def _page(
    rows: list[dict[str, Any]] | None,
    *,
    data_key: str = "time_entries",
    next_url: str | None = None,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {"links": {"next": next_url}}
    if not drop_key:
        body[data_key] = rows or []
    response = Response()
    response.status_code = 200
    response._content = json.dumps(body).encode()
    return response


def _make_manager(resume_state: HarvestResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str], list[Any]]:
    """Wire a mock session, snapshotting params/url/auth AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so reading it after the run
    only shows the final state.
    """
    session.headers = {}
    params: list[dict[str, Any]] = []
    urls: list[str] = []
    auths: list[Any] = []

    def _prepare(request: Any) -> mock.MagicMock:
        params.append(dict(request.params or {}))
        urls.append(request.url)
        auths.append(request.auth)
        # The client host-pins on the prepared URL, so it has to be a real string.
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return params, urls, auths


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


def _source(
    endpoint: str = "time_entries",
    manager: mock.MagicMock | None = None,
    *,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Any:
    return harvest_source(
        account_id="123456",
        access_token="pat-secret",
        endpoint=endpoint,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager if manager is not None else _make_manager(),
        api_version="v2",
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


class TestHarvestTransport:
    @parameterized.expand(
        [
            ("none", None, None),
            ("aware_datetime", datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC), "2026-05-04T09:30:00Z"),
            ("naive_datetime", datetime.datetime(2026, 5, 4, 9, 30), "2026-05-04T09:30:00Z"),
            (
                "offset_datetime",
                datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=2))),
                "2026-05-04T07:30:00Z",
            ),
            ("date", datetime.date(2026, 5, 4), "2026-05-04"),
            ("string_passthrough", "2026-05-04T09:30:00Z", "2026-05-04T09:30:00Z"),
        ]
    )
    def test_to_iso8601(self, _name: str, value: Any, expected: str | None) -> None:
        # `updated_since` only filters when it receives ISO 8601; a naive repr would be ignored
        # or rejected, silently turning an incremental sync into a full one.
        assert _to_iso8601(value) == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_account_and_user_agent_headers_and_bearer_auth(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _params, _urls, auths = _wire(session, [_page([{"id": 1}])])

        _rows(_source())

        # A token can reach several accounts, so Harvest 401s without the account header, and
        # 400s without a descriptive User-Agent.
        assert session.headers["Harvest-Account-Id"] == "123456"
        assert session.headers["User-Agent"] == HARVEST_USER_AGENT
        auth = auths[0]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "pat-secret"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_links_next_across_pages(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = f"https://{HARVEST_API_HOST}/v2/time_entries?cursor=abc&per_page=1000"
        params, urls, _auths = _wire(
            session,
            [
                _page([{"id": 1}], next_url=next_url),
                _page([{"id": 2}]),
            ],
        )

        rows = _rows(_source())

        assert [r["id"] for r in rows] == [1, 2]
        # The next link is self-contained, so the original params must not be re-appended.
        assert urls[1] == next_url
        assert params[1] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_resume_state_only_while_a_next_page_remains(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        next_url = f"https://{HARVEST_API_HOST}/v2/time_entries?cursor=abc"
        _wire(session, [_page([{"id": 1}], next_url=next_url), _page([{"id": 2}])])

        manager = _make_manager()
        _rows(_source(manager=manager))

        manager.save_state.assert_called_once_with(HarvestResumeConfig(next_url=next_url))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        saved = f"https://{HARVEST_API_HOST}/v2/time_entries?cursor=xyz"
        _params, urls, _auths = _wire(session, [_page([{"id": 3}])])

        rows = _rows(_source(manager=_make_manager(HarvestResumeConfig(next_url=saved))))

        # Picks up at the saved page rather than restarting at the first one.
        assert urls[0] == saved
        assert [r["id"] for r in rows] == [3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_link_is_rejected(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page([{"id": 1}], next_url="https://evil.example.com/v2/time_entries")])

        # Following a spoofed next link would replay the bearer token off-host.
        with pytest.raises(ValueError, match="disallowed host"):
            _rows(_source())

    @parameterized.expand(
        [
            ("first_sync", True, None, None),
            ("with_watermark", True, datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC), "2026-05-04T09:30:00Z"),
            ("full_refresh", False, datetime.datetime(2026, 5, 4, 9, 30, tzinfo=datetime.UTC), None),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_updated_since_is_sent_only_for_incremental_syncs(
        self, _name: str, incremental: bool, last_value: Any, expected: str | None, MockSession: mock.MagicMock
    ) -> None:
        session = MockSession.return_value
        params, _urls, _auths = _wire(session, [_page([{"id": 1}])])

        _rows(
            _source(
                should_use_incremental_field=incremental,
                db_incremental_field_last_value=last_value,
            )
        )

        assert params[0].get("updated_since") == expected
        assert params[0]["per_page"] == HARVEST_ENDPOINTS["time_entries"].page_size

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_endpoint_without_updated_since_never_sends_the_filter(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        params, _urls, _auths = _wire(session, [_page([{"id": 1}], data_key="roles")])

        # Roles has no server-side modified-since filter; sending one would be ignored at best.
        _rows(
            _source(
                "roles",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.datetime(2026, 5, 4, tzinfo=datetime.UTC),
            )
        )

        assert "updated_since" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_envelope_key_fails_loud(self, MockSession: mock.MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_page(None, drop_key=True)])

        # A changed response shape must fail rather than silently sync zero rows.
        with pytest.raises(Exception, match="time_entries"):
            _rows(_source())

    @parameterized.expand(ENDPOINTS)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_every_endpoint_reads_its_own_envelope_and_path(self, endpoint: str, MockSession: mock.MagicMock) -> None:
        config = HARVEST_ENDPOINTS[endpoint]
        session = MockSession.return_value
        _params, urls, _auths = _wire(session, [_page([{"id": 1}], data_key=config.data_key)])

        response = _source(endpoint)
        rows = _rows(response)

        # A wrong path 404s; a wrong envelope key yields zero rows.
        assert urls[0].startswith(f"https://{HARVEST_API_HOST}/v2/{config.path}")
        assert [r["id"] for r in rows] == [1]
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys

    @parameterized.expand([("time_entries", "created_at"), ("invoices", "created_at"), ("roles", None)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_partitioning_matches_the_endpoint_config(
        self, endpoint: str, partition_key: str | None, MockSession: mock.MagicMock
    ) -> None:
        response = _source(endpoint)
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_sort_mode_is_desc(self, MockSession: mock.MagicMock) -> None:
        # Harvest lists newest-first by a domain date and exposes no sort param, so rows never
        # arrive ordered by updated_at. "asc" would checkpoint the watermark mid-sync and skip
        # rows an interrupted run had not reached.
        assert _source().sort_mode == "desc"


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @mock.patch(HARVEST_SESSION_PATCH)
    def test_status_mapping(self, _name: str, status: int, expected_ok: bool, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status)
        ok, reported = validate_credentials("123456", "pat-secret", "v2")
        assert ok is expected_ok
        assert reported == status

    @mock.patch(HARVEST_SESSION_PATCH)
    def test_transport_errors_do_not_raise(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("123456", "pat-secret", "v2") == (False, None)

    @mock.patch(HARVEST_SESSION_PATCH)
    def test_probe_targets_users_me_with_both_credentials(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        validate_credentials("123456", "pat-secret", "v2")

        args, kwargs = mock_session.return_value.get.call_args
        # /users/me is readable by every role, unlike listing users, which needs an admin.
        assert args[0] == f"https://{HARVEST_API_HOST}/v2/users/me"
        assert kwargs["headers"]["Authorization"] == "Bearer pat-secret"
        assert kwargs["headers"]["Harvest-Account-Id"] == "123456"
        # Custom credential headers are not stripped by requests on a cross-origin redirect.
        assert kwargs["allow_redirects"] is False
