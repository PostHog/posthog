import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jira import JiraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira import (
    SPRINT_ISSUES_JQL,
    JiraResumeConfig,
    _format_jql_datetime,
    _normalize_issue,
    is_valid_subdomain,
    jira_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.source import JiraSource

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


class TestNormalizeIssue:
    def test_missing_fields_surfaces_error(self) -> None:
        # `fields` is always present with `fields=*all`; a malformed response should fail loudly
        # rather than silently null the `created` partition key.
        with pytest.raises(KeyError):
            _normalize_issue({"id": "1"})


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


def _driver() -> SourceDriver:
    return SourceDriver(JiraSource(), JiraSourceConfig(subdomain="acme", email="e@x.com", api_token="token"))


def _worklog(worklog_id: int, updated: str) -> dict[str, Any]:
    return {"id": str(worklog_id), "issueId": "10", "created": "2026-01-01T00:00:00.000+0000", "updated": updated}


class TestWorklogs:
    def test_walks_updated_feed_and_hydrates_each_page_in_feed_order(self) -> None:
        result = _driver().run(
            "worklogs",
            route(
                {
                    "/rest/api/3/worklog/updated": [
                        ScriptedResponse(
                            json={
                                "values": [{"worklogId": 1, "updatedTime": 100}, {"worklogId": 2, "updatedTime": 200}],
                                "since": 0,
                                "until": 200,
                                "lastPage": False,
                            }
                        ),
                        # An exact multiple of the page size ends on an empty page that repeats `until`.
                        ScriptedResponse(json={"values": [], "since": 200, "until": 200, "lastPage": True}),
                    ],
                    "/rest/api/3/worklog/list": [
                        ScriptedResponse(
                            json=[
                                _worklog(2, "2026-01-01T00:00:00.200+0000"),
                                _worklog(1, "2026-01-01T00:00:00.100+0000"),
                            ]
                        )
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/rest/api/3/worklog/updated",
            "/rest/api/3/worklog/list",
            "/rest/api/3/worklog/updated",
        ]
        assert result.params("since") == ["0", None, "200"]
        assert result.requests[1].method == "POST"
        assert result.requests[1].json() == {"ids": [1, 2]}
        assert [row["id"] for row in result.rows] == ["1", "2"]
        assert result.committed_states == [JiraResumeConfig(worklog_since=200)]

    @parameterized.expand(
        [
            ("full_refresh", {}, "0"),
            # The watermark minus a one minute overlap, in epoch milliseconds.
            (
                "incremental",
                {
                    "incremental_field": "updated",
                    "db_incremental_field_last_value": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
                },
                "1767225600000",
            ),
            ("resume", {"resume_state": JiraResumeConfig(worklog_since=1234)}, "1234"),
        ]
    )
    def test_first_request_since(self, _name: str, run_kwargs: dict[str, Any], expected_since: str) -> None:
        result = _driver().run(
            "worklogs",
            [ScriptedResponse(json={"values": [], "since": 0, "until": 0, "lastPage": True})],
            **run_kwargs,
        )

        assert result.raised is None
        assert result.params("since") == [expected_since]


class TestSprints:
    def test_skips_boards_without_sprints_and_dedupes_sprints_shared_by_boards(self) -> None:
        result = _driver().run(
            "sprints",
            route(
                {
                    "/rest/agile/1.0/board": [
                        ScriptedResponse(
                            json={"values": [{"id": 1}, {"id": 2}, {"id": 3}], "isLast": True, "startAt": 0}
                        )
                    ],
                    "/rest/agile/1.0/board/1/sprint": [
                        ScriptedResponse(json={"values": [{"id": 10}, {"id": 11}], "isLast": True})
                    ],
                    "/rest/agile/1.0/board/2/sprint": [
                        ScriptedResponse(
                            status=400, json={"errorMessages": ["The board does not support sprints"], "errors": {}}
                        )
                    ],
                    "/rest/agile/1.0/board/3/sprint": [
                        ScriptedResponse(json={"values": [{"id": 11}, {"id": 12}], "isLast": True})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [10, 11, 12]
        assert result.params("maxResults") == ["50", "50", "50", "50"]


SPRINT_FIELDS_RESPONSE = ScriptedResponse(
    json=[
        {"id": "summary", "schema": {"type": "string", "system": "summary"}},
        {"id": "customfield_10020", "schema": {"type": "array", "custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
    ]
)


class TestSprintIssues:
    def test_explodes_sprint_field_into_membership_rows(self) -> None:
        result = _driver().run(
            "sprint_issues",
            route(
                {
                    "/rest/api/3/field": [SPRINT_FIELDS_RESPONSE],
                    "/rest/api/3/search/jql": [
                        ScriptedResponse(
                            json={
                                "issues": [
                                    {
                                        "id": "100",
                                        "key": "P-1",
                                        "fields": {"customfield_10020": [{"id": 10}, {"id": 11}]},
                                    }
                                ],
                                "nextPageToken": "tok2",
                            }
                        ),
                        ScriptedResponse(
                            json={
                                "issues": [
                                    {"id": "101", "key": "P-2", "fields": {"customfield_10020": None}},
                                    {"id": "102", "key": "P-3", "fields": {"customfield_10020": [{"id": 11}]}},
                                ],
                                "isLast": True,
                            }
                        ),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.params("fields") == [None, "customfield_10020", "customfield_10020"]
        assert result.params("nextPageToken") == [None, None, "tok2"]
        assert result.rows == [
            {"sprint_id": 10, "issue_id": "100", "issue_key": "P-1"},
            {"sprint_id": 11, "issue_id": "100", "issue_key": "P-1"},
            {"sprint_id": 11, "issue_id": "102", "issue_key": "P-3"},
        ]
        assert result.committed_states == [JiraResumeConfig(next_page_token="tok2", jql=SPRINT_ISSUES_JQL)]

    def test_site_without_sprint_field_syncs_nothing(self) -> None:
        result = _driver().run(
            "sprint_issues", [ScriptedResponse(json=[{"id": "summary", "schema": {"type": "string"}}])]
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/rest/api/3/field"]
