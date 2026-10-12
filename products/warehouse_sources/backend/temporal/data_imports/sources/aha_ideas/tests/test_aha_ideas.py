import json
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.aha_ideas import (
    AhaIdeasResumeConfig,
    _build_initial_params,
    _format_updated_since,
    aha_ideas_source,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.settings import (
    AHA_IDEAS_ENDPOINTS,
    PER_PAGE,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the aha_ideas module.
AHA_IDEAS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.aha_ideas.aha_ideas.make_tracked_session"
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("full_host", "acme.aha.io", "acme"),
            ("https_url", "https://acme.aha.io", "acme"),
            ("trailing_slash", "acme.aha.io/", "acme"),
            ("with_hyphen", "acme-corp", "acme-corp"),
            ("whitespace", "  acme  ", "acme"),
        ]
    )
    def test_valid_subdomains(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("path_injection", "acme/../evil"),
            ("host_injection", "acme.evil.com"),
            ("userinfo_injection", "acme@evil.com"),
            ("empty", ""),
            ("space_inside", "ac me"),
            ("trailing_hyphen", "acme-"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(value)


class TestFormatUpdatedSince:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        result = _format_updated_since(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildInitialParams:
    def test_full_refresh_endpoint_never_filters(self) -> None:
        # idea_portals has no server-side `updated_since`; a cursor must not leak into the request.
        params = _build_initial_params(
            AHA_IDEAS_ENDPOINTS["idea_portals"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {"per_page": PER_PAGE}


def _response(
    response_key: str,
    items: list[dict[str, Any]] | None,
    *,
    current_page: int | None = None,
    total_pages: int | None = None,
    drop_key: bool = False,
) -> Response:
    body: dict[str, Any] = {}
    if not drop_key:
        body[response_key] = items or []
    if total_pages is not None:
        body["pagination"] = {"current_page": current_page or 1, "total_pages": total_pages}
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: AhaIdeasResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and return a list that captures each request AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, **kwargs: Any):
    return aha_ideas_source(
        subdomain="acme",
        api_key="key",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        **kwargs,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestAhaIdeasSourceNonFanout:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("ideas", [{"id": "2"}], current_page=2, total_pages=2)])

        rows = _rows(_source("ideas", _make_manager(AhaIdeasResumeConfig(next_page=2))))

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_cursor_added_to_request(self, MockSession) -> None:
        session = MockSession.return_value
        snapshots = _wire(session, [_response("ideas", [{"id": "1"}], total_pages=1)])

        _rows(
            _source(
                "ideas",
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["updated_since"] == "2026-03-04T02:58:14Z"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_response_key_for_idea_endorsements(self, MockSession) -> None:
        # Votes live at /ideas/endorsements with an `idea_endorsements` root key.
        session = MockSession.return_value
        snapshots = _wire(session, [_response("idea_endorsements", [{"id": "v1"}], total_pages=1)])

        rows = _rows(_source("idea_endorsements", _make_manager()))

        assert [r["id"] for r in rows] == ["v1"]
        assert snapshots[0]["url"] == "https://acme.aha.io/api/v1/ideas/endorsements"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_metadata_full_page_continues(self, MockSession) -> None:
        # No pagination metadata + a full page -> there may be more pages.
        session = MockSession.return_value
        full_page = [{"id": str(i)} for i in range(PER_PAGE)]
        _wire(session, [_response("ideas", full_page), _response("ideas", [{"id": "last"}])])

        rows = _rows(_source("ideas", _make_manager()))

        assert len(rows) == PER_PAGE + 1
        assert session.send.call_count == 2


class TestAhaIdeasSourceFanout:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_idea_comments_fanout_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("ideas", [{"id": "idea_1"}]),
            _FakeDltResource("idea_comments", [{"id": "comment_1", "idea_id": "idea_1"}]),
        ]

        response = aha_ideas_source(
            subdomain="acme",
            api_key="key",
            endpoint="idea_comments",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"id": "comment_1", "idea_id": "idea_1"}]
        assert response.primary_keys == ["id", "idea_id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]


class TestValidateCredentials:
    @mock.patch(AHA_IDEAS_SESSION_PATCH)
    def test_ok(self, mock_session) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("acme", "key") == (True, 200)

    @mock.patch(AHA_IDEAS_SESSION_PATCH)
    def test_bad_subdomain_raises_before_probe(self, mock_session) -> None:
        with pytest.raises(ValueError, match="Invalid Aha! account domain"):
            validate_credentials("acme/../evil", "key")
        mock_session.assert_not_called()
