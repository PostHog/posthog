import json
from typing import Any, cast

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import STATUSPAGE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.statuspage import (
    StatuspageAuth,
    StatuspageResumeConfig,
    statuspage_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the statuspage module.
STATUSPAGE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.statuspage.make_tracked_session"
)


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: StatuspageResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's (url, params) AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting the final state.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        prepared = mock.MagicMock()
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return statuspage_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)


class TestAuth:
    def test_sends_static_oauth_prefixed_key(self):
        request = mock.MagicMock()
        request.headers = {}
        StatuspageAuth("abc123")(request)
        # Statuspage's static API key is sent with an "OAuth" prefix despite not being an OAuth token.
        assert request.headers["Authorization"] == "OAuth abc123"

    def test_key_is_declared_as_a_redactable_secret(self):
        # The key must reach the client's redaction set so it's scrubbed from errors and log samples.
        assert StatuspageAuth("abc123").secret_values() == ("abc123",)


class TestTopLevelPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_pages_until_empty(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [_response([{"id": "p1"}, {"id": "p2"}]), _response([{"id": "p3"}]), _response([])],
        )
        manager = _make_manager()

        rows = _rows(_source("pages", manager))

        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        assert snaps[0]["params"]["page"] == 1
        assert snaps[0]["params"]["per_page"] == 100
        assert snaps[1]["params"]["page"] == 2
        assert snaps[2]["params"]["page"] == 3
        # Checkpoint saved once per non-empty yielded page (each points at the NEXT page); the empty
        # third page ends the walk without a checkpoint.
        saved = [c.args[0].paginator_state for c in manager.save_state.call_args_list]
        assert saved == [{"page": 2}, {"page": 3}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_short_page_is_not_treated_as_last(self, MockSession):
        # A short-but-non-empty page must NOT stop pagination — only an empty page does.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "p1"}]), _response([])])
        manager = _make_manager()

        rows = _rows(_source("pages", manager))

        assert [r["id"] for r in rows] == ["p1"]
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(session, [_response([{"id": "p9"}]), _response([])])
        manager = _make_manager(StatuspageResumeConfig(paginator_state={"page": 3}))

        _rows(_source("pages", manager))

        assert snaps[0]["params"]["page"] == 3


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_fans_out_over_pages_and_injects_page_id(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": "p1"}, {"id": "p2"}]),  # /pages page 1
                _response([{"id": "c1"}]),  # p1 components page 1
                _response([]),  # p1 components page 2 (empty)
                _response([{"id": "c2"}]),  # p2 components page 1
                _response([]),  # p2 components page 2 (empty)
                _response([]),  # /pages page 2 (empty, ends parent walk)
            ],
        )
        manager = _make_manager()

        rows = _rows(_source("components", manager))

        # Each child row carries its parent page id under page_id — unique table-wide.
        assert rows == [{"id": "c1", "page_id": "p1"}, {"id": "c2", "page_id": "p2"}]
        child_urls = [s["url"] for s in snaps if "/components" in s["url"]]
        assert child_urls[0] == "https://api.statuspage.io/v1/pages/p1/components"
        assert child_urls[2] == "https://api.statuspage.io/v1/pages/p2/components"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_fan_out_skipping_completed_parent(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": "p1"}, {"id": "p2"}]),  # /pages relisted on resume
                _response([{"id": "c2b"}]),  # p2 components resumed at page 2
                _response([]),  # p2 components page 3 (empty)
                _response([]),  # /pages page 2 (empty)
            ],
        )
        manager = _make_manager(
            StatuspageResumeConfig(
                fanout_state={
                    "completed": ["/pages/p1/components"],
                    "current": "/pages/p2/components",
                    "child_state": {"page": 2},
                }
            )
        )

        rows = _rows(_source("components", manager))

        # p1 is skipped entirely (already completed); p2 resumes at page 2.
        assert rows == [{"id": "c2b", "page_id": "p2"}]
        child_snaps = [s for s in snaps if "/components" in s["url"]]
        assert all(s["url"] == "https://api.statuspage.io/v1/pages/p2/components" for s in child_snaps)
        assert child_snaps[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_subscribers_uses_limit_page_size_param(self, MockSession):
        session = MockSession.return_value
        snaps = _wire(
            session,
            [
                _response([{"id": "p1"}]),  # /pages page 1
                _response([{"id": "s1"}]),  # p1 subscribers page 1
                _response([]),  # p1 subscribers page 2 (empty)
                _response([]),  # /pages page 2 (empty)
            ],
        )
        manager = _make_manager()

        _rows(_source("subscribers", manager))

        child_snaps = [s for s in snaps if "/subscribers" in s["url"]]
        assert child_snaps
        assert all(s["params"].get("limit") == 100 and "per_page" not in s["params"] for s in child_snaps)


class TestRetry:
    @pytest.mark.parametrize("status_code", [420, 429, 500, 502, 503])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_exhaust_then_raise(self, MockSession, status_code, monkeypatch):
        # Skip tenacity's real exponential-backoff sleeps while still exercising the full retry count.
        monkeypatch.setattr("tenacity.nap.time.sleep", lambda _seconds: None)
        session = MockSession.return_value
        _wire(session, [_response([], status_code=status_code) for _ in range(8)])
        manager = _make_manager()

        with pytest.raises(RESTClientRetryableError):
            _rows(_source("pages", manager))
        # 8 attempts total (the configured cap) before reraise.
        assert session.send.call_count == 8

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_error_raises_and_is_not_retried(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_response({"error": "Could not authenticate"}, status_code=401)])
        manager = _make_manager()

        with pytest.raises(requests.HTTPError):
            _rows(_source("pages", manager))
        # A 401 is permanent — issued exactly once, no retry.
        assert session.send.call_count == 1


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_ok",
        [(200, True), (401, False), (403, False), (500, False)],
    )
    @mock.patch(STATUSPAGE_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_ok):
        body = [] if status_code == 200 else {"error": "nope"}
        mock_session.return_value.get.return_value = _response(body, status_code=status_code)
        ok, error = validate_credentials("key")
        assert ok is expected_ok
        if not ok:
            assert error

    @mock.patch(STATUSPAGE_SESSION_PATCH)
    def test_request_exception_is_failure(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, error = validate_credentials("key")
        assert ok is False
        assert "boom" in (error or "")

    @mock.patch(STATUSPAGE_SESSION_PATCH)
    def test_probe_hits_pages_listing(self, mock_session):
        mock_session.return_value.get.return_value = _response([], status_code=200)
        validate_credentials("key")
        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.statuspage.io/v1/pages?per_page=1&page=1"


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(STATUSPAGE_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = STATUSPAGE_ENDPOINTS[endpoint]
        response = statuspage_source("key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("pages", ["id"]),
            ("components", ["page_id", "id"]),
            ("subscribers", ["page_id", "id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # Fan-out children carry the parent page id in their key so rows from different pages never
        # collide on a bare resource id.
        assert STATUSPAGE_ENDPOINTS[endpoint].primary_key == expected_keys


class TestResumeConfigCompatibility:
    def test_legacy_saved_state_still_parses(self):
        # A checkpoint written by the pre-framework code must still deserialize via dataclass(**saved).
        cfg = StatuspageResumeConfig(**cast("dict[str, Any]", {"page": 3, "parent_page_id": "p2"}))
        assert cfg.page == 3
        assert cfg.parent_page_id == "p2"
        assert cfg.paginator_state is None
        assert cfg.fanout_state is None
