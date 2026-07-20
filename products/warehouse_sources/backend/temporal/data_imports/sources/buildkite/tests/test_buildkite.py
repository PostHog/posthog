import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite import (
    BuildkiteResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    buildkite_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import BUILDKITE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the buildkite module.
BUILDKITE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite.make_tracked_session"
)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_builds_incremental_maps_to_created_from(self) -> None:
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS["builds"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["per_page"] == 100
        assert params["created_from"] == "2026-03-04T02:58:14+00:00"

    def test_builds_full_refresh_has_no_filter(self) -> None:
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS["builds"],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params == {"per_page": 100}

    @parameterized.expand([("organizations",), ("pipelines",), ("agents",)])
    def test_full_refresh_endpoints_never_get_a_time_filter(self, endpoint: str) -> None:
        # These endpoints expose no server-side timestamp filter, so an incremental request must
        # not silently add one (it would be ignored by the API and misrepresent the sync).
        params = _build_initial_params(
            BUILDKITE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params == {"per_page": 100}


def _response(body: Any, link: str | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    if link:
        # Buildkite paginates via an RFC 5988 Link header with rel="next".
        resp.headers["Link"] = f'<{link}>; rel="next"'
    return resp


def _make_manager(resume_state: BuildkiteResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url/params/auth AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(
    endpoint: str,
    manager: MagicMock,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    return buildkite_source(
        api_access_token="bkua",
        organization="my-org",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
        incremental_field=incremental_field,
    )


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_follows_link_header_pagination(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=2&per_page=100"
        snapshots = _wire(
            session,
            [
                _response([{"id": "p1"}, {"id": "p2"}], link=page2),
                _response([{"id": "p3"}]),
            ],
        )

        rows = _rows(_source("pipelines", _make_manager()))

        assert [r["id"] for r in rows] == ["p1", "p2", "p3"]
        assert snapshots[0]["url"] == "https://api.buildkite.com/v2/organizations/my-org/pipelines"
        assert snapshots[0]["params"] == {"per_page": 100}
        # The next-page URL is self-contained; the original params must not be re-appended.
        assert snapshots[1]["url"] == page2
        assert snapshots[1]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_org_scoped_path_ignores_placeholder(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "o1"}])])

        _rows(_source("organizations", _make_manager()))

        assert snapshots[0]["url"] == "https://api.buildkite.com/v2/organizations"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_page_without_checkpoint(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        manager = _make_manager()
        rows = _rows(_source("agents", manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        session = MockSession.return_value
        resume_url = "https://api.buildkite.com/v2/organizations/my-org/pipelines?page=3&per_page=100"
        snapshots = _wire(session, [_response([{"id": "p9"}])])

        manager = _make_manager(BuildkiteResumeConfig(next_url=resume_url))
        rows = _rows(_source("pipelines", manager))

        # Resume must start at the saved URL, not the freshly-built first-page URL.
        assert snapshots[0]["url"] == resume_url
        assert [r["id"] for r in rows] == ["p9"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_state_after_yielding_a_page(self, MockSession) -> None:
        session = MockSession.return_value
        page2 = "https://api.buildkite.com/v2/organizations/my-org/builds?page=2&per_page=100"
        _wire(
            session,
            [
                _response([{"id": "b1"}], link=page2),
                _response([{"id": "b2"}]),
            ],
        )

        manager = _make_manager()
        _rows(_source("builds", manager))

        # State is saved AFTER a page is yielded and points at the NEXT page, so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it. The final page
        # has no next link, so no checkpoint is written for it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BuildkiteResumeConfig(next_url=page2)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sync_sends_created_from(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "b1"}])])

        _rows(
            _source(
                "builds",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert snapshots[0]["params"] == {"per_page": 100, "created_from": "2026-03-04T02:58:14+00:00"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_is_framework_bearer(self, MockSession) -> None:
        # The token must flow through the framework auth config (so it's redacted from logs),
        # not a hand-built Authorization header.
        session = MockSession.return_value
        snapshots = _wire(session, [_response([{"id": "p1"}])])

        _rows(_source("pipelines", _make_manager()))

        auth = snapshots[0]["auth"]
        assert isinstance(auth, BearerTokenAuth)
        assert auth.token == "bkua"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loudly(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"message": "something unexpected"})])

        # Buildkite list endpoints return a top-level JSON array; a 200 with a non-list body means
        # the response shape changed — fail loud instead of syncing garbage.
        with pytest.raises(ValueError, match="list response body"):
            _rows(_source("pipelines", _make_manager()))


class TestBuildkiteSourceResponse:
    @parameterized.expand(
        [
            ("organizations", ["id"], "asc", "created_at"),
            ("pipelines", ["id"], "asc", "created_at"),
            ("builds", ["id"], "desc", "created_at"),
            ("agents", ["id"], "asc", "created_at"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(
        self, endpoint: str, primary_keys: list[str], sort_mode: str, partition_key: str, MockSession
    ) -> None:
        MockSession.return_value.headers = {}
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_mode == "datetime"
        assert response.partition_format == "week"
        assert response.partition_keys == [partition_key]


class TestValidateCredentials:
    @staticmethod
    def _patch_get(mock_session: MagicMock, status_code: int) -> dict[str, str]:
        captured: dict[str, str] = {}

        def fake_get(url: str, **kwargs: Any) -> MagicMock:
            captured["url"] = url
            return MagicMock(status_code=status_code)

        mock_session.return_value.get.side_effect = fake_get
        return captured

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_success(self, mock_session) -> None:
        self._patch_get(mock_session, 200)
        assert validate_credentials("bkua", "my-org") == (True, None)

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_invalid_token(self, mock_session) -> None:
        self._patch_get(mock_session, 401)
        ok, error = validate_credentials("bkua", "my-org")
        assert ok is False
        assert error is not None and "invalid" in error.lower()

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_forbidden_accepted_at_source_create(self, mock_session) -> None:
        # A valid token may lack read_organizations while still holding the per-endpoint scopes the
        # user wants — so a 403 at source-create (schema_name=None) must not block connecting.
        self._patch_get(mock_session, 403)
        assert validate_credentials("bkua", "my-org") == (True, None)

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_forbidden_rejected_for_specific_schema(self, mock_session) -> None:
        self._patch_get(mock_session, 403)
        ok, error = validate_credentials("bkua", "my-org", schema_name="builds")
        assert ok is False
        assert error is not None and "builds" in error

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_org_not_found(self, mock_session) -> None:
        self._patch_get(mock_session, 404)
        ok, error = validate_credentials("bkua", "missing-org")
        assert ok is False
        assert error is not None and "missing-org" in error

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_schema_probe_targets_endpoint_path(self, mock_session) -> None:
        captured = self._patch_get(mock_session, 200)
        validate_credentials("bkua", "my-org", schema_name="agents")
        assert captured["url"] == "https://api.buildkite.com/v2/organizations/my-org/agents?per_page=1"

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_source_create_probe_targets_org(self, mock_session) -> None:
        captured = self._patch_get(mock_session, 200)
        validate_credentials("bkua", "my-org")
        assert captured["url"] == "https://api.buildkite.com/v2/organizations/my-org"

    @mock.patch(BUILDKITE_SESSION_PATCH)
    def test_swallows_transport_errors(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        ok, error = validate_credentials("bkua", "my-org")
        assert ok is False
        assert error is not None
