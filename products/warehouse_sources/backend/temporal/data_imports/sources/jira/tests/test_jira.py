import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira import (
    JiraResumeConfig,
    _build_issues_jql,
    _format_jql_datetime,
    _normalize_issue,
    base_url,
    is_valid_subdomain,
    jira_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the jira module.
JIRA_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira.make_tracked_session"


def _response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _manager(resume: JiraResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _run(endpoint: str, responses: list[Response], manager: mock.MagicMock, **kwargs: Any) -> list[dict[str, Any]]:
    with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
        _wire(MockSession.return_value, responses)
        source = jira_source(
            subdomain="acme",
            email="e@x.com",
            api_token="token",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
            **kwargs,
        )
        return [row for page in cast("Iterable[Any]", source.items()) for row in page]


class TestSubdomain:
    @parameterized.expand(
        [
            ("simple", "acme", True),
            ("with_dash", "acme-corp", True),
            ("alphanumeric", "acme123", True),
            ("empty", "", False),
            ("with_dot", "acme.evil", False),
            ("with_at", "acme@evil.com", False),
            ("with_slash", "acme/path", False),
            ("leading_dash", "-acme", False),
        ]
    )
    def test_is_valid_subdomain(self, _name: str, subdomain: str, expected: bool) -> None:
        assert is_valid_subdomain(subdomain) is expected

    def test_base_url(self) -> None:
        assert base_url("acme") == "https://acme.atlassian.net"


class TestFormatJqlDatetime:
    @parameterized.expand(
        [
            # A one day lookback is subtracted to absorb timezone skew between our UTC watermark and the instance TZ.
            ("datetime", datetime(2026, 3, 4, 2, 58), "2026-03-03 02:58"),
            ("date", date(2026, 3, 4), "2026-03-03 00:00"),
            ("iso_string", "2026-03-04T02:58:14+00:00", "2026-03-03 02:58"),
            ("iso_string_z", "2026-03-04T02:58:14Z", "2026-03-03 02:58"),
        ]
    )
    def test_format_jql_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_jql_datetime(value) == expected


class TestBuildIssuesJql:
    def test_no_last_value_bounds_with_epoch_floor(self) -> None:
        # ``/search/jql`` 400s on unbounded queries, so a full sync must still carry a lower bound.
        assert _build_issues_jql("updated", None) == 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'

    def test_with_last_value_filters_and_orders(self) -> None:
        jql = _build_issues_jql("updated", datetime(2026, 3, 4, 2, 58))
        assert jql == 'updated >= "2026-03-03 02:58" ORDER BY updated ASC'

    def test_custom_incremental_field(self) -> None:
        jql = _build_issues_jql("created", datetime(2026, 3, 4, 2, 58))
        assert jql == 'created >= "2026-03-03 02:58" ORDER BY created ASC'

    def test_none_field_defaults_to_updated(self) -> None:
        assert _build_issues_jql(None, None) == 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'


class TestNormalizeIssue:
    def test_lifts_timestamps_to_top_level(self) -> None:
        issue = {
            "id": "1",
            "fields": {"created": "2026-01-01T00:00:00.000+0000", "updated": "2026-02-01T00:00:00.000+0000"},
        }
        normalized = _normalize_issue(issue)
        assert normalized["created"] == "2026-01-01T00:00:00.000+0000"
        assert normalized["updated"] == "2026-02-01T00:00:00.000+0000"
        # Original nested object is preserved.
        assert normalized["fields"]["created"] == "2026-01-01T00:00:00.000+0000"

    def test_missing_fields_surfaces_error(self) -> None:
        # `fields` is always present with `fields=*all`; a malformed response should fail loudly
        # rather than silently null the `created` partition key.
        with pytest.raises(KeyError):
            _normalize_issue({"id": "1"})


class TestNonePagination:
    def test_single_request_bare_array(self) -> None:
        manager = _manager()
        rows = _run("fields", [_response([{"id": "f1"}, {"id": "f2"}])], manager)
        assert rows == [{"id": "f1"}, {"id": "f2"}]
        manager.save_state.assert_not_called()


class TestTokenPagination:
    def test_walks_pages_and_lifts_timestamps(self) -> None:
        manager = _manager()
        responses = [
            _response({"issues": [{"id": "1", "fields": {"created": "c1", "updated": "u1"}}], "nextPageToken": "tok2"}),
            _response({"issues": [{"id": "2", "fields": {"created": "c2", "updated": "u2"}}], "isLast": True}),
        ]
        rows = _run(
            "issues", responses, manager, should_use_incremental_field=False, db_incremental_field_last_value=None
        )
        assert [row["id"] for row in rows] == ["1", "2"]
        # data_map lifts the nested timestamps to the row root (partition/cursor columns).
        assert rows[0]["created"] == "c1"
        assert rows[0]["updated"] == "u1"
        # State is saved with the token for the *next* page after the first batch is yielded.
        full_sync_jql = 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'
        manager.save_state.assert_called_once_with(JiraResumeConfig(next_page_token="tok2", jql=full_sync_jql))

    def test_stops_on_is_last_even_with_token(self) -> None:
        # Jira signals the final page with isLast; the walk must end even if a token is echoed back.
        manager = _manager()
        responses = [_response({"issues": [{"id": "1", "fields": {"created": "c1", "updated": "u1"}}], "isLast": True})]
        rows = _run("issues", responses, manager, should_use_incremental_field=False)
        assert [row["id"] for row in rows] == ["1"]
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("matching_jql_reuses_token", 'updated >= "1970-01-01 00:00" ORDER BY updated ASC', True),
            ("stale_jql_discards_token", 'updated >= "2026-02-11 09:07" ORDER BY updated ASC', False),
            ("legacy_state_without_jql_discards_token", None, False),
        ]
    )
    def test_resume_honors_saved_jql(self, _name: str, saved_jql: str | None, expect_token_sent: bool) -> None:
        manager = _manager(JiraResumeConfig(next_page_token="tok2", jql=saved_jql))
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            params = _wire(
                MockSession.return_value,
                [_response({"issues": [{"id": "2", "fields": {"created": "c2", "updated": "u2"}}], "isLast": True})],
            )
            source = jira_source(
                subdomain="acme",
                email="e@x.com",
                api_token="token",
                endpoint="issues",
                team_id=1,
                job_id="j",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            rows = [row for page in cast("Iterable[Any]", source.items()) for row in page]
        assert [row["id"] for row in rows] == ["2"]
        assert params[0].get("nextPageToken") == ("tok2" if expect_token_sent else None)

    def test_applies_incremental_jql_and_requests_all_fields(self) -> None:
        manager = _manager()
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            params = _wire(MockSession.return_value, [_response({"issues": [], "isLast": True})])
            source = jira_source(
                subdomain="acme",
                email="e@x.com",
                api_token="token",
                endpoint="issues",
                team_id=1,
                job_id="j",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58),
                incremental_field="updated",
            )
            list(cast("Iterable[Any]", source.items()))
        assert params[0]["jql"] == 'updated >= "2026-03-03 02:58" ORDER BY updated ASC'
        assert params[0]["fields"] == "*all"


class TestOffsetPagination:
    def test_walks_pages_and_checkpoints(self) -> None:
        manager = _manager()
        responses = [
            _response({"values": [{"id": str(i)} for i in range(100)]}),
            _response({"values": [{"id": "100"}], "isLast": True}),
        ]
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            params = _wire(MockSession.return_value, responses)
            source = jira_source(
                subdomain="acme",
                email="e@x.com",
                api_token="token",
                endpoint="projects",
                team_id=1,
                job_id="j",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
            )
            rows = [row for page in cast("Iterable[Any]", source.items()) for row in page]
        assert len(rows) == 101
        assert params[0]["startAt"] == 0
        assert params[0]["maxResults"] == 100
        assert params[1]["startAt"] == 100
        manager.save_state.assert_called_once_with(JiraResumeConfig(start_at=100))

    def test_stops_on_short_page(self) -> None:
        manager = _manager()
        rows = _run("projects", [_response({"values": [{"id": "1"}]})], manager)
        assert rows == [{"id": "1"}]
        manager.save_state.assert_not_called()

    def test_handles_bare_array(self) -> None:
        manager = _manager()
        rows = _run("users", [_response([{"accountId": "a1"}])], manager)
        assert rows == [{"accountId": "a1"}]

    def test_missing_data_key_yields_no_rows(self) -> None:
        # A body without the expected wrapper key is a legit zero-row page (tolerant extraction),
        # not a fail-loud — the paginator stops on the empty page.
        manager = _manager()
        rows = _run("projects", [_response({"other": []})], manager)
        assert rows == []
        manager.save_state.assert_not_called()

    def test_resumes_from_saved_offset(self) -> None:
        manager = _manager(JiraResumeConfig(start_at=200))
        with mock.patch(CLIENT_SESSION_PATCH) as MockSession:
            params = _wire(MockSession.return_value, [_response({"values": [{"id": "201"}]})])
            source = jira_source(
                subdomain="acme",
                email="e@x.com",
                api_token="token",
                endpoint="projects",
                team_id=1,
                job_id="j",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
            )
            list(cast("Iterable[Any]", source.items()))
        assert params[0]["startAt"] == 200


class TestJiraSourceResponse:
    def test_issues_response_has_partitioning_and_primary_key(self) -> None:
        response = jira_source(
            subdomain="acme",
            email="e@x.com",
            api_token="token",
            endpoint="issues",
            team_id=1,
            job_id="j",
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.name == "issues"
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"

    @parameterized.expand([("projects", ["id"]), ("users", ["accountId"]), ("fields", ["id"])])
    def test_non_issue_endpoints_have_no_partitioning(self, endpoint: str, primary_key: list[str]) -> None:
        response = jira_source(
            subdomain="acme",
            email="e@x.com",
            api_token="token",
            endpoint=endpoint,
            team_id=1,
            job_id="j",
            logger=mock.MagicMock(),
            resumable_source_manager=_manager(),
        )
        assert response.primary_keys == primary_key
        assert response.partition_keys is None
        assert response.partition_mode is None

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            jira_source(
                subdomain="acme",
                email="e@x.com",
                api_token="token",
                endpoint="nope",
                team_id=1,
                job_id="j",
                logger=mock.MagicMock(),
                resumable_source_manager=_manager(),
            )


class TestValidateCredentials:
    def test_rejects_invalid_subdomain_without_request(self) -> None:
        with mock.patch(JIRA_SESSION_PATCH) as session:
            ok, status = validate_credentials("acme.evil", "e@x.com", "token")
            assert ok is False
            assert status is None
            session.assert_not_called()

    @parameterized.expand([(200, True), (401, False), (403, False)])
    def test_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        with mock.patch(JIRA_SESSION_PATCH) as session:
            session.return_value.get.return_value = _response({}, status_code=status_code)
            ok, status = validate_credentials("acme", "e@x.com", "token")
            assert ok is expected_ok
            assert status == status_code

    def test_request_exception_returns_false(self) -> None:
        with mock.patch(JIRA_SESSION_PATCH) as session:
            session.return_value.get.side_effect = Exception("boom")
            ok, status = validate_credentials("acme", "e@x.com", "token")
            assert ok is False
            assert status is None
