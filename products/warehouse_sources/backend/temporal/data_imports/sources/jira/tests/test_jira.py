from datetime import UTC, date, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jira import JiraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira import (
    SPRINT_ISSUES_JQL,
    JiraResumeConfig,
    _format_jql_datetime,
    _normalize_issue,
    is_valid_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.source import JiraSource


def _driver() -> SourceDriver:
    return SourceDriver(JiraSource(), JiraSourceConfig(subdomain="acme", email="e@x.com", api_token="token"))


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
        result = _driver().run(
            "issues",
            [
                ScriptedResponse(
                    json={
                        "issues": [{"id": "1", "fields": {"created": "c1", "updated": "u1"}}],
                        "nextPageToken": "tok2",
                    }
                ),
                ScriptedResponse(
                    json={"issues": [{"id": "2", "fields": {"created": "c2", "updated": "u2"}}], "isLast": True}
                ),
            ],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2"]
        # data_map lifts the nested timestamps to the row root (partition/cursor columns).
        assert result.rows[0]["created"] == "c1"
        assert result.rows[0]["updated"] == "u1"
        # State is saved with the token for the *next* page after the first batch is yielded.
        full_sync_jql = 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'
        assert result.saved_states == [JiraResumeConfig(next_page_token="tok2", jql=full_sync_jql)]

    @parameterized.expand(
        [
            ("matching_jql_reuses_token", 'updated >= "1970-01-01 00:00" ORDER BY updated ASC', True),
            ("stale_jql_discards_token", 'updated >= "2026-02-11 09:07" ORDER BY updated ASC', False),
            ("legacy_state_without_jql_discards_token", None, False),
        ]
    )
    def test_resume_honors_saved_jql(self, _name: str, saved_jql: str | None, expect_token_sent: bool) -> None:
        result = _driver().run(
            "issues",
            [
                ScriptedResponse(
                    json={"issues": [{"id": "2", "fields": {"created": "c2", "updated": "u2"}}], "isLast": True}
                )
            ],
            resume_state=JiraResumeConfig(next_page_token="tok2", jql=saved_jql),
            should_use_incremental_field=False,
        )
        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["2"]
        assert result.params("nextPageToken") == ["tok2" if expect_token_sent else None]


class TestOffsetPagination:
    def test_walks_pages_and_checkpoints(self) -> None:
        result = _driver().run(
            "projects",
            [
                ScriptedResponse(json={"values": [{"id": str(i)} for i in range(100)]}),
                ScriptedResponse(json={"values": [{"id": "100"}], "isLast": True}),
            ],
        )
        assert result.raised is None
        assert len(result.rows) == 101
        assert result.params("startAt") == ["0", "100"]
        assert result.params("maxResults") == ["100", "100"]
        assert result.saved_states == [JiraResumeConfig(start_at=100)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "projects",
            [ScriptedResponse(json={"values": [{"id": "201"}]})],
            resume_state=JiraResumeConfig(start_at=200),
        )
        assert result.raised is None
        assert result.params("startAt") == ["200"]


class TestJiraSourceResponse:
    @parameterized.expand([("projects", ["id"]), ("users", ["accountId"]), ("fields", ["id"])])
    def test_non_issue_endpoints_have_no_partitioning(self, endpoint: str, primary_key: list[str]) -> None:
        body: Any = [] if endpoint in ("users", "fields") else {"values": []}
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == primary_key
        assert result.response.partition_keys is None
        assert result.response.partition_mode is None


class TestValidateCredentials:
    def test_rejects_invalid_subdomain_without_request(self) -> None:
        with scripted_network([]) as network:
            ok, status = validate_credentials("acme.evil", "e@x.com", "token")
        assert ok is False
        assert status is None
        assert network.requests_log == []
        assert network.session_options == []

    @parameterized.expand([(403, False)])
    def test_status_mapping(self, status_code: int, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code, json={})]) as network:
            ok, status = validate_credentials("acme", "e@x.com", "token")
        assert ok is expected_ok
        assert status == status_code
        assert [request.path for request in network.requests_log] == ["/rest/api/3/myself"]


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


class TestIssueChangelogs:
    def test_bulk_fetches_each_issue_page_and_checkpoints_after_its_last_changelog_page(self) -> None:
        result = _driver().run(
            "issue_changelogs",
            route(
                {
                    "/rest/api/3/search/jql": [
                        ScriptedResponse(json={"issues": [{"id": "10"}, {"id": "11"}], "nextPageToken": "tok2"}),
                        ScriptedResponse(json={"issues": [{"id": "12"}], "isLast": True}),
                    ],
                    "/rest/api/3/changelog/bulkfetch": [
                        ScriptedResponse(
                            json={
                                "issueChangeLogs": [
                                    {"issueId": "10", "changeHistories": [{"id": "100", "created": "c1"}]},
                                    {"issueId": "11", "changeHistories": [{"id": "101", "created": "c2"}]},
                                ],
                                "nextPageToken": "cl2",
                            }
                        ),
                        ScriptedResponse(
                            json={"issueChangeLogs": [{"issueId": "10", "changeHistories": [{"id": "102"}]}]}
                        ),
                        ScriptedResponse(json={"issueChangeLogs": []}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.params("fields") == ["id", None, None, "id", None]
        assert [request.json() for request in result.requests if request.method == "POST"] == [
            {"issueIdsOrKeys": ["10", "11"], "maxResults": 1000},
            {"issueIdsOrKeys": ["10", "11"], "maxResults": 1000, "nextPageToken": "cl2"},
            {"issueIdsOrKeys": ["12"], "maxResults": 1000},
        ]
        assert [(row["issue_id"], row["id"]) for row in result.rows] == [("10", "100"), ("11", "101"), ("10", "102")]
        full_sync_jql = 'updated >= "1970-01-01 00:00" ORDER BY updated ASC'
        assert result.saved_states == [JiraResumeConfig(next_page_token="tok2", jql=full_sync_jql)]

    @parameterized.expand(
        [
            ("full_refresh", {}, 'updated >= "1970-01-01 00:00" ORDER BY updated ASC', ["old", "recent"]),
            # The JQL and the changelog filter both use the watermark less the one day lookback.
            (
                "incremental",
                {
                    "incremental_field": "created",
                    "db_incremental_field_last_value": datetime(2026, 3, 4, 2, 58, tzinfo=UTC),
                },
                'updated >= "2026-03-03 02:58" ORDER BY updated ASC',
                ["recent"],
            ),
        ]
    )
    def test_incremental_shapes_jql_and_drops_history_before_the_window(
        self, _name: str, run_kwargs: dict[str, Any], expected_jql: str, expected_ids: list[str]
    ) -> None:
        result = _driver().run(
            "issue_changelogs",
            route(
                {
                    "/rest/api/3/search/jql": [ScriptedResponse(json={"issues": [{"id": "10"}], "isLast": True})],
                    "/rest/api/3/changelog/bulkfetch": [
                        ScriptedResponse(
                            json={
                                "issueChangeLogs": [
                                    {
                                        "issueId": "10",
                                        "changeHistories": [
                                            {"id": "old", "created": "2026-03-03T02:57:00.000+0000"},
                                            {"id": "recent", "created": "2026-03-03T02:58:00.000+0000"},
                                        ],
                                    }
                                ]
                            }
                        )
                    ],
                }
            ),
            **run_kwargs,
        )

        assert result.raised is None
        assert result.params("jql")[0] == expected_jql
        assert [row["id"] for row in result.rows] == expected_ids


class TestIssueComments:
    def test_reads_embedded_comments_and_refetches_truncated_lists_of_existing_issues(self) -> None:
        result = _driver().run(
            "issue_comments",
            route(
                {
                    "/rest/api/3/search/jql": [
                        ScriptedResponse(
                            json={
                                "issues": [
                                    {
                                        "id": "1",
                                        "key": "P-1",
                                        "fields": {"comment": {"comments": [{"id": "a"}], "total": 1}},
                                    },
                                    {
                                        "id": "2",
                                        "key": "P-2",
                                        "fields": {"comment": {"comments": [{"id": "b"}], "total": 2}},
                                    },
                                    {"id": "3", "key": "P-3", "fields": {"comment": {"comments": [], "total": 0}}},
                                    {
                                        "id": "4",
                                        "key": "P-4",
                                        "fields": {"comment": {"comments": [{"id": "d"}], "total": 2}},
                                    },
                                ],
                                "nextPageToken": "tok2",
                            }
                        ),
                        ScriptedResponse(json={"issues": [], "isLast": True}),
                    ],
                    "/rest/api/3/issue/2/comment": [
                        ScriptedResponse(json={"comments": [{"id": "b"}, {"id": "c"}], "startAt": 0, "total": 2})
                    ],
                    # Deleted after the search returned it.
                    "/rest/api/3/issue/4/comment": [
                        ScriptedResponse(status=404, json={"errorMessages": ["Issue does not exist"]})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.paths == [
            "/rest/api/3/search/jql",
            "/rest/api/3/issue/2/comment",
            "/rest/api/3/issue/4/comment",
            "/rest/api/3/search/jql",
        ]
        assert result.params("fields") == ["comment", None, None, "comment"]
        assert [(row["issue_key"], row["id"]) for row in result.rows] == [("P-1", "a"), ("P-2", "b"), ("P-2", "c")]


class TestGroupMembers:
    def test_fans_out_over_groups_with_group_columns_and_skips_deleted_groups(self) -> None:
        result = _driver().run(
            "group_members",
            route(
                {
                    "/rest/api/3/group/bulk": [
                        ScriptedResponse(
                            json={
                                "values": [{"groupId": "g1", "name": "devs"}, {"groupId": "g2", "name": "gone"}],
                                "isLast": True,
                            }
                        )
                    ],
                    "/rest/api/3/group/member": [
                        ScriptedResponse(json={"values": [{"accountId": "u1"}], "isLast": True}),
                        ScriptedResponse(status=404, json={"errorMessages": ["Group not found"]}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.params("groupId") == [None, "g1", "g2"]
        assert result.params("includeInactiveUsers") == [None, "true", "true"]
        assert result.rows == [{"accountId": "u1", "group_id": "g1", "group_name": "devs"}]
