import json
from typing import Any

from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant import firehydrant
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.firehydrant import (
    PAGE_SIZE,
    FireHydrantResumeConfig,
    base_url_for_region,
    firehydrant_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.firehydrant.settings import (
    ENDPOINTS,
    FIREHYDRANT_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(
    items: list[dict[str, Any]] | None, *, next_page: int | None = None, drop_pagination: bool = False
) -> Response:
    body: dict[str, Any] = {"data": items or []}
    if not drop_pagination:
        body["pagination"] = {"next": next_page}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: FireHydrantResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Wire a mock session; capture each request's params AND url AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
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


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_page_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(
            session,
            [
                _response([{"id": "i1"}, {"id": "i2"}], next_page=2),
                _response([{"id": "i3"}], next_page=None),
            ],
        )

        manager = _make_manager()
        rows = _rows(
            firehydrant_source("fhb_test", "incidents", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert [r["id"] for r in rows] == ["i1", "i2", "i3"]
        # First request carries per_page but no explicit page (FireHydrant defaults to page 1);
        # the second request injects the `page` cursor from `pagination.next`.
        assert params[0]["per_page"] == PAGE_SIZE
        assert "page" not in params[0]
        assert params[1]["page"] == 2
        assert params[1]["per_page"] == PAGE_SIZE
        # Checkpoint saved once, pointing at the next page; the final (next=None) page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == FireHydrantResumeConfig(next_page=2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_unpaginated_response_terminates(self, MockSession) -> None:
        # signals_on_call and similar endpoints may return a single page with no `pagination` object.
        session = MockSession.return_value
        _wire(session, [_response([{"id": "s1"}], drop_pagination=True)])

        manager = _make_manager()
        rows = _rows(
            firehydrant_source("fhb_test", "signals_on_call", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        assert [r["id"] for r in rows] == ["s1"]
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_state_saved_after_each_page_with_next(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response([{"id": "a"}], next_page=2),
                _response([{"id": "b"}], next_page=3),
                _response([{"id": "c"}], next_page=None),
            ],
        )

        manager = _make_manager()
        _rows(firehydrant_source("fhb_test", "services", team_id=1, job_id="j", resumable_source_manager=manager))

        # State saved only when a next page exists — not after the final page.
        assert [c.args[0].next_page for c in manager.save_state.call_args_list] == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_region_routes_requests_to_eu_host(self, MockSession) -> None:
        # EU accounts only answer on the data-residency host; if the source ignored region it would hit
        # the US host and every EU sync would fail.
        session = MockSession.return_value
        _params, urls = _wire(session, [_response([{"id": "eu1"}], next_page=None)])

        manager = _make_manager()
        rows = _rows(
            firehydrant_source(
                "fhb_test", "incidents", team_id=1, job_id="j", resumable_source_manager=manager, region="eu"
            )
        )

        assert [r["id"] for r in rows] == ["eu1"]
        assert urls[0].startswith("https://api.eu.firehydrant.io/v1/incidents")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        params, _urls = _wire(session, [_response([{"id": "b"}], next_page=None)])

        manager = _make_manager(FireHydrantResumeConfig(next_page=2))
        rows = _rows(
            firehydrant_source("fhb_test", "services", team_id=1, job_id="j", resumable_source_manager=manager)
        )

        # Resumes at page 2 (page 1 is never requested), proving the saved cursor is honored.
        assert [r["id"] for r in rows] == ["b"]
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rate_limit_then_success_is_retried(self, MockSession, monkeypatch: Any) -> None:
        # 429 must be classified retryable (not fatal): a 429 followed by a 200 recovers and yields rows.
        import tenacity.nap

        monkeypatch.setattr(tenacity.nap.time, "sleep", lambda _s: None)

        session = MockSession.return_value
        throttled = Response()
        throttled.status_code = 429
        throttled.headers["Retry-After"] = "1"
        _wire(session, [throttled, _response([{"id": "ok"}], next_page=None)])

        manager = _make_manager()
        rows = _rows(
            firehydrant_source("fhb_test", "incidents", team_id=1, job_id="j", resumable_source_manager=manager)
        )
        assert [r["id"] for r in rows] == ["ok"]


class TestSourceResponse:
    @parameterized.expand(list(ENDPOINTS))
    def test_source_response_matches_endpoint_config(self, endpoint: str) -> None:
        config = FIREHYDRANT_ENDPOINTS[endpoint]
        response = firehydrant_source(
            api_key="fhb_test",
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
        # A partition key that changes (updated_at/lastSeen) rewrites partitions every sync.
        for config in FIREHYDRANT_ENDPOINTS.values():
            if config.partition_key:
                assert config.partition_key == "created_at"

    @parameterized.expand(
        [
            ("priorities", ["slug"]),
            ("severities", ["slug"]),
            ("incident_tags", ["name"]),
            ("custom_field_definitions", ["field_id"]),
            ("incidents", ["id"]),
        ]
    )
    def test_endpoint_specific_primary_keys(self, endpoint: str, expected_keys: list[str]) -> None:
        assert FIREHYDRANT_ENDPOINTS[endpoint].primary_keys == expected_keys


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            # Only a 200 proves the key is real and usable — a 403 means it reached FireHydrant but
            # lacks permissions, so we reject it rather than register an unverified credential.
            ("forbidden_rejected", 403, False),
            ("unauthorized", 401, False),
            ("unexpected", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_valid: bool) -> None:
        response = requests.Response()
        response.status_code = status_code
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(firehydrant, "make_tracked_session", lambda *a, **k: session):
            valid, _error = validate_credentials("fhb_test")
        assert valid is expected_valid

    def test_network_error_is_invalid(self, monkeypatch: Any) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        monkeypatch.setattr(firehydrant, "make_tracked_session", lambda *a, **k: session)

        valid, error = validate_credentials("fhb_test")
        assert valid is False
        assert error is not None

    @parameterized.expand(
        [
            ("default_us", None, "https://api.firehydrant.io/v1/ping"),
            ("eu", "eu", "https://api.eu.firehydrant.io/v1/ping"),
        ]
    )
    def test_probes_region_host(self, _name: str, region: str | None, expected_url: str) -> None:
        # The key is only valid against its own region's host, so validation must probe there.
        response = requests.Response()
        response.status_code = 200
        session = mock.MagicMock()
        session.get.return_value = response

        with mock.patch.object(firehydrant, "make_tracked_session", lambda *a, **k: session):
            validate_credentials("fhb_test", region=region)
        assert session.get.call_args.args[0] == expected_url

    @parameterized.expand(
        [
            ("default_us", None, "https://api.firehydrant.io"),
            ("us", "us", "https://api.firehydrant.io"),
            ("eu", "eu", "https://api.eu.firehydrant.io"),
            ("unknown_falls_back", "apac", "https://api.firehydrant.io"),
        ]
    )
    def test_base_url_for_region(self, _name: str, region: str | None, expected_host: str) -> None:
        # EU accounts are pinned to the data-residency host; an unknown or missing region must fall
        # back to the US default rather than a wrong host.
        assert base_url_for_region(region) == expected_host


class TestCredentialRedaction:
    """The token must be registered for redaction so it can't leak into logged URLs or HTTP samples."""

    def test_validate_credentials_redacts_api_key(self, monkeypatch: Any) -> None:
        captured: dict[str, Any] = {}

        def fake_session(*args: Any, **kwargs: Any) -> mock.MagicMock:
            captured.update(kwargs)
            response = requests.Response()
            response.status_code = 200
            session = mock.MagicMock()
            session.get.return_value = response
            return session

        monkeypatch.setattr(firehydrant, "make_tracked_session", fake_session)
        validate_credentials("fhb_secret")
        assert captured.get("redact_values") == ("fhb_secret",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_transport_redacts_api_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], next_page=None)])

        _rows(
            firehydrant_source(
                "fhb_secret", "incidents", team_id=1, job_id="j", resumable_source_manager=_make_manager()
            )
        )
        # The bearer token is registered for value-based redaction when the tracked session is built.
        assert "fhb_secret" in MockSession.call_args.kwargs.get("redact_values", ())
