import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm import (
    CAPSULE_CRM_BASE_URL,
    CapsuleCRMResumeConfig,
    CapsuleCRMUntrustedURLError,
    _clamp_future_value_to_now,
    _format_since_value,
    _validate_pagination_url,
    capsule_crm_source,
    validate_credentials,
)

# capsule_crm_source builds its own SSRF-guarded session in the capsule_crm module (passed to the
# REST client), so both the pagination path and validate_credentials patch the module-level factory.
SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.capsule_crm.make_tracked_session"
)


def _response(
    body: dict[str, Any], *, next_url: str | None = None, status_code: int = 200, url: str | None = None
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.url = url or f"{CAPSULE_CRM_BASE_URL}/parties"
    if next_url:
        resp.headers["Link"] = f'<{next_url}>; rel="next"'
    return resp


def _make_manager(resume_state: CapsuleCRMResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[requests.Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request's url/params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(manager: mock.MagicMock, endpoint: str = "parties", access_token: str = "tok", **kwargs: Any):
    return capsule_crm_source(
        access_token=access_token, endpoint=endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestFormatSinceValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_since_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_since_value(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Capsule expects a Z suffix, not the +00:00 offset isoformat() produces.
        assert "+00:00" not in _format_since_value(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))

    def test_non_utc_datetime_is_converted_to_utc(self) -> None:
        value = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone(timedelta(hours=5)))
        assert _format_since_value(value) == "2026-03-04T07:00:00Z"


class TestClampFutureValueToNow:
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_naive_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, 21, 46, 42)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )

    @freeze_time("2026-06-15T12:00:00Z")
    def test_past_datetime_is_unchanged(self) -> None:
        value = datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC)
        assert _clamp_future_value_to_now(value) == value

    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_date_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(date(2027, 2, 5)) == date(2026, 6, 15)

    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("some-cursor") == "some-cursor"


class TestRequestParams:
    @mock.patch(SESSION_PATCH)
    def test_full_refresh_request_has_no_since(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"users": [{"id": 1}]})])

        _rows(_source(_make_manager(), endpoint="users"))

        assert snapshots[0]["url"] == f"{CAPSULE_CRM_BASE_URL}/users"
        assert snapshots[0]["params"] == {"perPage": 100}

    @mock.patch(SESSION_PATCH)
    def test_incremental_endpoint_embeds_related_data(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"parties": [{"id": 1}]})])

        _rows(_source(_make_manager()))

        # embed values are folded in to reduce round-trips.
        assert snapshots[0]["params"]["embed"] == "tags,fields,organisation"
        assert "since" not in snapshots[0]["params"]

    @mock.patch(SESSION_PATCH)
    def test_first_incremental_sync_omits_since(self, MockSession) -> None:
        # No watermark yet -> pull full history, no `since` filter.
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"opportunities": []})])

        _rows(
            _source(
                _make_manager(),
                endpoint="opportunities",
                should_use_incremental_field=True,
                db_incremental_field_last_value=None,
            )
        )

        assert "since" not in snapshots[0]["params"]

    @mock.patch(SESSION_PATCH)
    def test_incremental_sync_with_watermark_adds_since(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"opportunities": []})])

        _rows(
            _source(
                _make_manager(),
                endpoint="opportunities",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["since"] == "2026-03-04T02:58:14Z"

    @mock.patch(SESSION_PATCH)
    @freeze_time("2026-06-15T12:00:00Z")
    def test_future_watermark_is_clamped_to_now(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"parties": []})])

        _rows(
            _source(
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2027, 2, 5, 21, 46, 42, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["since"] == "2026-06-15T12:00:00Z"

    @mock.patch(SESSION_PATCH)
    def test_since_ignored_for_full_refresh_only_endpoint(self, MockSession) -> None:
        # tasks has no server-side `since` filter, so a watermark must not produce a `since` param.
        session = MockSession.return_value
        snapshots = _wire(session, [_response({"tasks": []})])

        _rows(
            _source(
                _make_manager(),
                endpoint="tasks",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert "since" not in snapshots[0]["params"]


class TestPagination:
    @mock.patch(SESSION_PATCH)
    def test_follows_link_header_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        snapshots = _wire(
            session,
            [
                _response({"parties": [{"id": 1}, {"id": 2}]}, next_url=page2),
                _response({"parties": [{"id": 3}]}),
            ],
        )

        rows = _rows(_source(_make_manager()))

        assert rows == [{"id": 1}, {"id": 2}, {"id": 3}]
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert snapshots[1]["url"] == page2
        assert snapshots[1]["params"] == {}

    @mock.patch(SESSION_PATCH)
    def test_saves_resume_state_after_each_page_with_more(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        _wire(
            session,
            [
                _response({"parties": [{"id": 1}]}, next_url=page2),
                _response({"parties": [{"id": 2}]}),
            ],
        )

        manager = _make_manager()
        _rows(_source(manager))

        # State saved once (after page 1, which still had a next page); not after the final page.
        manager.save_state.assert_called_once_with(CapsuleCRMResumeConfig(next_url=page2))

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"
        snapshots = _wire(session, [_response({"parties": [{"id": 2}]})])

        manager = _make_manager(CapsuleCRMResumeConfig(next_url=page2))
        rows = _rows(_source(manager))

        assert rows == [{"id": 2}]
        # The starting URL must NOT be fetched when resuming.
        assert session.send.call_count == 1
        assert snapshots[0]["url"] == page2
        assert snapshots[0]["params"] == {}

    @mock.patch(SESSION_PATCH)
    def test_extracts_rows_from_endpoint_specific_wrapper_key(self, MockSession) -> None:
        # lost_reasons nests its array under "lostReasons", not the endpoint name.
        session = MockSession.return_value
        _wire(session, [_response({"lostReasons": [{"id": 7, "name": "No budget"}]})])

        rows = _rows(_source(_make_manager(), endpoint="lost_reasons"))

        assert rows == [{"id": 7, "name": "No budget"}]

    @mock.patch(SESSION_PATCH)
    def test_missing_wrapper_key_is_treated_as_empty_page(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"unexpected": []})])

        assert _rows(_source(_make_manager())) == []

    @mock.patch(SESSION_PATCH)
    def test_hostile_upstream_next_url_is_rejected(self, MockSession) -> None:
        # An upstream Link header pointing at another host must abort before the bearer token is sent
        # there, and the poisoned URL must not be persisted as resume state.
        session = MockSession.return_value
        _wire(
            session,
            [_response({"parties": [{"id": 1}]}, next_url="https://evil.example.com/api/v2/parties")],
        )

        manager = _make_manager()
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _rows(_source(manager))
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH)
    def test_hostile_resumed_next_url_is_rejected(self, MockSession) -> None:
        # A poisoned resume state from Redis must never be requested with the bearer token.
        session = MockSession.return_value
        _wire(session, [])

        manager = _make_manager(CapsuleCRMResumeConfig(next_url="https://evil.example.com/api/v2/parties"))
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _rows(_source(manager))
        session.send.assert_not_called()


class TestErrorHandling:
    @mock.patch("tenacity.nap.time.sleep")
    @mock.patch(SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, MockSession, mock_sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status_code=429),
                _response({"parties": [{"id": 1}]}),
            ],
        )

        assert _rows(_source(_make_manager())) == [{"id": 1}]
        assert session.send.call_count == 2

    @parameterized.expand([(401,), (403,), (404,)])
    @mock.patch(SESSION_PATCH)
    def test_client_errors_raise_for_status(self, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({}, status_code=status, url=f"{CAPSULE_CRM_BASE_URL}/parties")])

        # `get_non_retryable_errors` matches on this stable "NNN Client Error ... for url" text.
        with pytest.raises(requests.HTTPError, match=f"{status} Client Error"):
            _rows(_source(_make_manager()))


class TestValidatePaginationUrl:
    @parameterized.expand(
        [
            ("first_page", f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100"),
            ("next_page", f"{CAPSULE_CRM_BASE_URL}/parties?perPage=100&page=2"),
            ("other_endpoint", f"{CAPSULE_CRM_BASE_URL}/opportunities?page=3"),
        ]
    )
    def test_trusted_urls_pass_through(self, _name: str, url: str) -> None:
        assert _validate_pagination_url(url) == url

    @parameterized.expand(
        [
            ("foreign_host", "https://evil.example.com/api/v2/parties"),
            ("subdomain_lookalike", "https://api.capsulecrm.com.evil.example.com/api/v2/parties"),
            ("http_scheme", "http://api.capsulecrm.com/api/v2/parties"),
            ("wrong_path_prefix", "https://api.capsulecrm.com/internal/parties"),
            ("missing_path", "https://api.capsulecrm.com"),
            ("metadata_endpoint", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_untrusted_urls_raise(self, _name: str, url: str) -> None:
        with pytest.raises(CapsuleCRMUntrustedURLError):
            _validate_pagination_url(url)


class TestTokenRedaction:
    @mock.patch(SESSION_PATCH)
    def test_validate_credentials_redacts_token_and_disables_redirects(self, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)

        validate_credentials("secret-token")

        assert MockSession.call_args.kwargs["redact_values"] == ("secret-token",)
        assert MockSession.call_args.kwargs["allow_redirects"] is False

    @mock.patch(SESSION_PATCH)
    def test_source_session_redacts_token_and_disables_redirects(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"parties": []})])

        _rows(_source(_make_manager(), access_token="secret-token"))

        assert MockSession.call_args.kwargs["redact_values"] == ("secret-token",)
        assert MockSession.call_args.kwargs["allow_redirects"] is False


class TestValidateCredentials:
    @mock.patch(SESSION_PATCH)
    def test_ok(self, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("tok") is True

    @mock.patch(SESSION_PATCH)
    def test_unauthorized(self, MockSession) -> None:
        MockSession.return_value.get.return_value = mock.MagicMock(status_code=401)
        assert validate_credentials("tok") is False

    @mock.patch(SESSION_PATCH)
    def test_swallows_exceptions(self, MockSession) -> None:
        MockSession.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("tok") is False


class TestSourceResponse:
    @parameterized.expand(
        [
            ("parties", "createdAt"),
            ("opportunities", "createdAt"),
            ("kases", "createdAt"),
            ("tasks", "createdAt"),
        ]
    )
    def test_incremental_and_taskish_endpoints_partition_on_created_at(self, endpoint: str, partition_key: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.sort_mode == "asc"

    @parameterized.expand([("users",), ("milestones",), ("pipelines",), ("categories",), ("lost_reasons",)])
    def test_metadata_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        response = _source(_make_manager(), endpoint=endpoint)
        assert response.primary_keys == ["id"]
        assert response.partition_mode is None
        assert response.partition_keys is None
