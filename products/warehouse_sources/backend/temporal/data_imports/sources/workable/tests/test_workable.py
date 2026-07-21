import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import (
    PAGE_SIZE,
    WORKABLE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.workable import (
    WorkableResumeConfig,
    _format_datetime,
    _sort_mode_for,
    _validate_subdomain,
    validate_credentials,
    workable_source,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the workable module.
WORKABLE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.workable.workable.make_tracked_session"
)


def _response(
    body: dict[str, Any] | None,
    *,
    status: int = 200,
    url: str = "https://acme.workable.com/spi/v3/candidates",
    reason: str = "",
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    resp.reason = reason
    resp._content = json.dumps(body).encode() if body is not None else b""
    return resp


def _page(items: list[dict[str, Any]], data_key: str = "candidates", next_url: str | None = None) -> dict[str, Any]:
    return {data_key: items, "paging": ({"next": next_url} if next_url else {})}


def _make_manager(resume_state: WorkableResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's params and url AT SEND TIME.

    ``request.params`` / ``request.url`` are mutated in place across pages, so snapshot a copy when
    each request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestValidateSubdomain:
    @parameterized.expand(
        [
            ("simple", "groove-tech", "groove-tech"),
            ("alnum", "company123", "company123"),
            ("single_char", "a", "a"),
            ("trims_whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert _validate_subdomain(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("dot_injection", "evil.com/"),
            ("slash", "acme/foo"),
            ("at_sign", "user@host"),
            ("dotted", "a.b"),
            ("trailing_hyphen", "acme-"),
            ("leading_hyphen", "-acme"),
            ("space_inside", "ac me"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            _validate_subdomain(value)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_only", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "already-a-cursor", "already-a-cursor"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestSortMode:
    @parameterized.expand(
        [
            ("created_at_is_asc", "candidates", True, "created_at", "asc"),
            ("updated_at_is_desc", "candidates", True, "updated_at", "desc"),
            ("default_field_is_desc", "candidates", True, None, "desc"),
            ("non_incremental_run_is_asc", "candidates", False, "updated_at", "asc"),
            ("full_refresh_endpoint_is_asc", "members", True, "updated_at", "asc"),
        ]
    )
    def test_sort_mode(
        self, _name: str, endpoint: str, use_incremental: bool, field: str | None, expected: str
    ) -> None:
        assert _sort_mode_for(endpoint, use_incremental, field) == expected


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_items_and_follows_paging_next(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=2"
        _wire(
            session,
            [
                _response(_page([{"id": "1"}], next_url=second)),
                _response(_page([{"id": "2"}])),
            ],
        )

        rows = _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert [r["id"] for r in rows] == ["1", "2"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_first_request_carries_limit(self, MockSession) -> None:
        session = MockSession.return_value
        params, urls = _wire(session, [_response(_page([{"id": "1"}]))])

        _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert params[0]["limit"] == PAGE_SIZE
        assert urls[0] == "https://acme.workable.com/spi/v3/candidates"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_each_page_with_more_pages(self, MockSession) -> None:
        session = MockSession.return_value
        second = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=2"
        _wire(
            session,
            [
                _response(_page([{"id": "1"}], next_url=second)),
                _response(_page([{"id": "2"}])),
            ],
        )

        manager = _make_manager()
        _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
        )
        # State saved once (after page 1, which had a next); not after the final page.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WorkableResumeConfig(next_url=second)]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_next_url(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://www.workable.com/spi/v3/accounts/acme/candidates?limit=100&since_id=99"
        _, urls = _wire(session, [_response(_page([{"id": "99"}]))])

        manager = _make_manager(WorkableResumeConfig(next_url=resume_url))
        rows = _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=manager,
            )
        )
        # The initial URL is never fetched — we pick up from the saved cursor.
        assert [r["id"] for r in rows] == ["99"]
        assert urls[0] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_page_terminates(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response(_page([], data_key="stages"))])

        rows = _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="stages",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert rows == []
        assert session.send.call_count == 1


class TestIncrementalFilter:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_default_field_injects_updated_after(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_page([{"id": "1"}]))])

        _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field=None,
            )
        )
        assert params[0]["updated_after"] == "2026-01-02T03:04:05Z"
        assert "created_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_created_at_field_injects_created_after(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_page([{"id": "1"}]))])

        _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="created_at",
            )
        )
        assert params[0]["created_after"] == "2026-01-02T03:04:05Z"
        assert "updated_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_ignores_incremental_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_page([{"id": "1"}], data_key="members"))])

        _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="members",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )
        assert not any(key.endswith("_after") for key in params[0])

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_incremental_run_has_no_filter(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_response(_page([{"id": "1"}]))])

        _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )
        assert not any(key.endswith("_after") for key in params[0])


class TestRetryBehavior:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_status_is_retried_then_succeeds(self, _name: str, status: int, MockSession, _sleep) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({}, status=status),
                _response(_page([{"id": "1"}])),
            ],
        )

        rows = _rows(
            workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint="candidates",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert [r["id"] for r in rows] == ["1"]
        assert session.send.call_count == 2

    @parameterized.expand(
        [
            ("unauthorized", 401, "Unauthorized"),
            ("forbidden", 403, "Forbidden"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_retryable_status_raises_http_error(self, _name: str, status: int, reason: str, MockSession) -> None:
        session = MockSession.return_value
        url = "https://acme.workable.com/spi/v3/candidates"
        _wire(session, [_response({}, status=status, url=url, reason=reason)])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(
                workable_source(
                    subdomain="acme",
                    api_token="tok",
                    endpoint="candidates",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )
        # The message shape feeds source.get_non_retryable_errors matching.
        assert f"{status} Client Error: {reason} for url: https://" in str(exc.value)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_is_redacted_from_errors(self, MockSession) -> None:
        session = MockSession.return_value
        # Carry the token in the URL to prove it's scrubbed from the raised error.
        url = "https://acme.workable.com/spi/v3/candidates?t=secret-tok"
        _wire(session, [_response({}, status=401, url=url, reason="Unauthorized")])

        with pytest.raises(requests.HTTPError) as exc:
            _rows(
                workable_source(
                    subdomain="acme",
                    api_token="secret-tok",
                    endpoint="candidates",
                    team_id=1,
                    job_id="j",
                    resumable_source_manager=_make_manager(),
                )
            )
        assert "secret-tok" not in str(exc.value)


class TestWorkableSourceResponse:
    @parameterized.expand(list(WORKABLE_ENDPOINTS.keys()))
    def test_source_response_primary_keys_and_partitioning(self, endpoint: str) -> None:
        config = WORKABLE_ENDPOINTS[endpoint]
        with mock.patch(CLIENT_SESSION_PATCH):
            response = workable_source(
                subdomain="acme",
                api_token="tok",
                endpoint=endpoint,
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_partition_keys_are_stable_creation_fields(self) -> None:
        # Never partition on a mutable field like updated_at.
        for config in WORKABLE_ENDPOINTS.values():
            assert config.partition_key in (None, "created_at")


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (200, True)),
            ("unauthorized", 401, (401, False)),
            ("forbidden", 403, (403, False)),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: tuple[int, bool]) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(WORKABLE_SESSION_PATCH, lambda **_kwargs: session):
            assert validate_credentials("acme", "tok") == expected

    def test_transport_error_returns_zero(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(WORKABLE_SESSION_PATCH, lambda **_kwargs: session):
            assert validate_credentials("acme", "tok") == (0, False)

    def test_invalid_subdomain_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_credentials("evil.com/", "tok")
