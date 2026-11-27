from datetime import UTC, datetime, timedelta
from typing import Any, cast

from unittest.mock import Mock

from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.sleekplan._config import SleekplanSourceConfig
from products.warehouse_sources.sources.sleekplan.settings import (
    PLAN_UPGRADE_REQUIRED_MESSAGE,
    SLEEKPLAN_ENDPOINTS,
    SURVEY_LOOKBACK_DAYS,
)
from products.warehouse_sources.sources.sleekplan.sleekplan import (
    SleekplanPaginator,
    SleekplanResumeConfig,
    _format_survey_date,
    _resolve_incremental_field,
    _resource,
    validate_credentials,
)
from products.warehouse_sources.sources.sleekplan.source import SleekplanSource


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(SleekplanSource(), SleekplanSourceConfig(api_key=api_key))


def _posts_page(has_more: bool = False, *post_ids: int) -> ScriptedResponse:
    items = {str(post_id): {"feedback_id": post_id} for post_id in post_ids}
    return ScriptedResponse(json={"data": {"items": items, "has_more": has_more}})


def _v2_page(items: list[dict], has_more: bool = False) -> ScriptedResponse:
    return ScriptedResponse(json={"status": "success", "data": {"items": items, "has_more": has_more}})


_UPGRADE_REQUIRED = ScriptedResponse(
    json={
        "status": "error",
        "data": {"code": "upgrade_required", "message": "This feature is not on your plan.", "feature": "groups"},
    }
)


def _page_response(body: Any) -> Mock:
    response = Mock()
    response.json.return_value = body
    return response


class TestSleekplanPaginator:
    @parameterized.expand(
        [
            ("has_more_true_continues", {"data": {"items": {"1": {}}, "has_more": True}}, [{}], True),
            ("has_more_false_stops", {"data": {"items": {"1": {}}, "has_more": False}}, [{}], False),
            ("empty_page_stops", {"data": {"items": {}, "has_more": True}}, [], False),
            ("bare_array_envelope_continues", {"status": "success", "data": [{"promoter_id": 1}]}, [{}], True),
            ("missing_envelope_continues", {"status": "success"}, [{}], True),
        ]
    )
    def test_termination(self, _name: str, body: Any, data: list[dict], expected_has_next: bool) -> None:
        paginator = SleekplanPaginator()

        paginator.update_state(_page_response(body), data)

        assert paginator.has_next_page is expected_has_next

    def test_non_json_body_does_not_stop_pagination(self) -> None:
        paginator = SleekplanPaginator()
        response = Mock()
        response.json.side_effect = ValueError("not json")

        paginator.update_state(response, [{}])

        assert paginator.has_next_page is True


class TestSurveyDateFormatting:
    def test_applies_the_replacement_window_lookback(self) -> None:
        value = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)

        assert _format_survey_date(value) == (value - timedelta(days=SURVEY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    @parameterized.expand([("initial_seed", "1970-01-01"), ("unparseable", "not-a-date")])
    def test_passes_through_a_non_datetime_value(self, _name: str, value: str) -> None:
        assert _format_survey_date(value) == value


class TestResolveIncrementalField:
    @parameterized.expand(
        [
            ("advertised_choice_is_honoured", "updated", "updated"),
            ("unadvertised_choice_falls_back", "created", "updated"),
            ("no_choice_falls_back", None, "updated"),
        ]
    )
    def test_resolution(self, _name: str, chosen: str | None, expected: str) -> None:
        assert _resolve_incremental_field(SLEEKPLAN_ENDPOINTS["Promoter"], chosen) == expected


class TestResource:
    @parameterized.expand(
        [
            ("Users", "/users", "data.items.*", {"sort": "created", "sort_dir": "ASC"}),
            ("Posts", "/posts", "data.items.*", {"sort": "new"}),
            ("Updates", "/updates", "data.items.*", {}),
            ("Satisfaction", "/satisfaction", "data", {}),
            ("Promoter", "/promoter", "data", {}),
            ("Groups", "/groups", "data.items", {"sort": "created", "sort_dir": "asc"}),
            ("Documents", "/documents", "data.items", {}),
        ]
    )
    def test_endpoint_request_shape(self, name: str, path: str, selector: str, extra_params: dict) -> None:
        resource = _resource(SLEEKPLAN_ENDPOINTS[name], should_use_incremental_field=False, incremental_field=None)

        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["path"] == path
        assert endpoint["data_selector"] == selector
        assert endpoint["params"] == {"per_page": 100, **extra_params}
        assert isinstance(endpoint["paginator"], SleekplanPaginator)

    @parameterized.expand(["Users", "Posts", "Updates", "Groups", "Documents"])
    def test_endpoints_without_a_server_side_filter_never_go_incremental(self, name: str) -> None:
        resource = _resource(SLEEKPLAN_ENDPOINTS[name], should_use_incremental_field=True, incremental_field="updated")

        assert resource["write_disposition"] == "replace"
        assert "incremental" not in cast(dict[str, Any], resource["endpoint"])

    @parameterized.expand(["Satisfaction", "Promoter"])
    def test_survey_endpoints_window_on_date_start_when_incremental(self, name: str) -> None:
        resource = _resource(SLEEKPLAN_ENDPOINTS[name], should_use_incremental_field=True, incremental_field=None)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert cast(dict[str, Any], resource["endpoint"])["incremental"]["start_param"] == "date_start"

    @parameterized.expand(["Satisfaction", "Promoter"])
    def test_survey_endpoints_full_refresh_when_incremental_disabled(self, name: str) -> None:
        resource = _resource(SLEEKPLAN_ENDPOINTS[name], should_use_incremental_field=False, incremental_field=None)

        assert resource["write_disposition"] == "replace"
        assert "incremental" not in cast(dict[str, Any], resource["endpoint"])


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, (True, None)),
            ("unauthorized", 401, None, (False, "Invalid Sleekplan API key.")),
            # A key inherits its owner's permissions, so a 403 only blocks the schema being checked.
            ("forbidden_at_source_create", 403, None, (True, None)),
            (
                "forbidden_for_a_schema",
                403,
                "Posts",
                (False, "This Sleekplan API key does not have permission to read Posts."),
            ),
            ("server_error", 500, None, (False, "Sleekplan API returned an unexpected status (500).")),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, schema_name: str | None, expected: tuple) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))):
            assert validate_credentials("key", schema_name=schema_name) == expected

    def test_probe_session_redacts_the_key_and_disables_sample_capture(self) -> None:
        # Users/posts/comments carry emails and free-text feedback the generic scrubber can't
        # anonymize, so the probe -- like every other Sleekplan request -- must not be captured.
        with scripted_network(always(ScriptedResponse(status=200))) as network:
            validate_credentials("secret-key")

        assert network.session_options == [{"redact_values": ("secret-key",), "capture": False}]


class TestTopLevelSource:
    @parameterized.expand(
        [
            ("Users", ["user_id"], "created", "asc"),
            ("Posts", ["feedback_id"], "created", "desc"),
            ("Updates", ["changelog_id"], "created", "desc"),
            ("Promoter", ["promoter_id"], "created", "desc"),
            # `updated` is the only timestamp on a satisfaction response, and partitioning on it
            # would rewrite partitions whenever a response is replaced.
            ("Satisfaction", ["satisfaction_id"], None, "desc"),
        ]
    )
    def test_source_response_shape(
        self, name: str, primary_keys: list[str], partition_key: str | None, sort_mode: str
    ) -> None:
        response = (
            _driver().run(name, always(ScriptedResponse(json={"data": {"items": {}, "has_more": False}}))).response
        )

        assert response is not None
        assert response.name == name
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == ([partition_key] if partition_key else None)

    def test_session_redacts_the_key_and_disables_sample_capture(self) -> None:
        # Posts/comments/votes/survey responses carry emails and free-text feedback the generic
        # scrubber can't anonymize, so sample capture must stay off (still metered and logged).
        result = _driver("secret-key").run("Posts", [_posts_page(False, 1)])

        assert result.requests
        assert result.session_options == [{"redact_values": ("secret-key",), "capture": False}]
        assert result.requests[0].headers["authorization"] == "Bearer secret-key"

    def test_seeds_the_paginator_from_saved_state(self) -> None:
        result = _driver().run("Posts", [_posts_page(False, 1)], resume_state=SleekplanResumeConfig(page=4))

        assert result.params("page") == ["4"]

    @parameterized.expand(
        [
            ("saves_next_page", [True, False], [SleekplanResumeConfig(page=2)]),
            ("ignores_terminal_state", [False], []),
        ]
    )
    def test_resume_hook(self, _name: str, has_more_by_page: list[bool], expected: list[SleekplanResumeConfig]) -> None:
        result = _driver().run(
            "Posts", [_posts_page(has_more, page) for page, has_more in enumerate(has_more_by_page, start=1)]
        )

        assert result.saved_states == expected


class TestFanOutSource:
    @parameterized.expand(
        [
            ("identified_voter", {"user": {"user_id": 9}}, 9),
            ("missing_voter", {}, None),
        ]
    )
    def test_votes_lift_the_voter_id_to_the_row_root(self, _name: str, vote_row: dict, expected: int | None) -> None:
        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/posts":
                return _posts_page(False, 77) if request.param("page") == "1" else _posts_page(False)
            votes = [{"vote": 1, **vote_row}] if request.param("page") == "1" else []
            return ScriptedResponse(json={"data": {"votes": votes}})

        result = _driver().run("Votes", script)

        # The (post, user) pair is the only primary key a vote has.
        assert result.rows[0]["feedback_id"] == 77
        assert result.rows[0]["user_id"] == expected

    @parameterized.expand(["comments", "votes"])
    def test_fan_out_pages_with_per_page(self, kind: str) -> None:
        result = _driver().run(
            kind.capitalize(),
            [_posts_page(False, 1), ScriptedResponse(json={"data": {kind: [{"comment_id": 1}], "has_more": False}})],
        )

        # One page each: the Sleekplan paginator stops on `has_more`, where a plain page-number one would ask again.
        assert result.raised is None
        assert result.paths == ["/v1/posts", f"/v1/post/1/{kind}"]
        assert result.params("per_page") == ["100", "100"]

    def test_fan_out_resumes_from_its_own_checkpoint(self) -> None:
        fanout_state = {"completed": ["/post/1/comments"], "current": "/post/2/comments", "child_state": {"page": 3}}

        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v1/posts":
                return _posts_page(False, 1, 2)
            return ScriptedResponse(json={"data": {"comments": [{"comment_id": 1}], "has_more": False}})

        result = _driver().run("Comments", script, resume_state=SleekplanResumeConfig(fanout_state=fanout_state))

        assert result.paths == ["/v1/posts", "/v1/post/2/comments"]
        assert result.params("page")[1] == "3"
        saved = result.saved_states[-1]
        assert set(saved.fanout_state["completed"]) == {"/post/1/comments", "/post/2/comments"}


class TestV2Source:
    @parameterized.expand(
        [
            ("Groups", "/v2/groups", "group_id"),
            ("Documents", "/v2/documents", "document_id"),
        ]
    )
    def test_walks_zero_based_pages_until_has_more_is_false(self, name: str, path: str, key: str) -> None:
        result = _driver().run(
            name,
            [
                _v2_page([{key: 1}, {key: 2}], has_more=True),
                _v2_page([{key: 3}], has_more=False),
            ],
        )

        assert result.raised is None
        assert result.paths == [path, path]
        assert result.params("page") == ["0", "1"]
        assert [row[key] for row in result.rows] == [1, 2, 3]

    def test_resumes_a_v2_endpoint_from_the_saved_page(self) -> None:
        result = _driver().run(
            "Documents", [_v2_page([{"document_id": 1}])], resume_state=SleekplanResumeConfig(page=3)
        )

        assert result.params("page") == ["3"]

    @parameterized.expand(["Groups", "Documents", "GroupMembers"])
    def test_plan_gated_feature_fails_loudly_instead_of_syncing_no_rows(self, name: str) -> None:
        result = _driver().run(name, always(_UPGRADE_REQUIRED))

        assert result.rows == []
        assert isinstance(result.raised, ValueError)
        assert PLAN_UPGRADE_REQUIRED_MESSAGE in str(result.raised)

    def test_group_members_fan_out_over_groups_and_carry_the_group_id(self) -> None:
        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v2/groups":
                return _v2_page([{"group_id": 5}, {"group_id": 6}])
            if request.path == "/v2/groups/5/members":
                return _v2_page([{"user_id": 11}, {"user_id": 12}])
            # Group 6 was deleted after the parent listing.
            return ScriptedResponse(status=404, json={"status": "error", "data": {"key": "not_found"}})

        result = _driver().run("GroupMembers", script)

        assert result.raised is None
        assert result.paths == ["/v2/groups", "/v2/groups/5/members", "/v2/groups/6/members"]
        assert result.params("page") == ["0", "0", "0"]
        assert result.params("sort")[0] == "created"
        assert [(row["group_id"], row["user_id"]) for row in result.rows] == [(5, 11), (5, 12)]
        assert result.response is not None
        assert result.response.primary_keys == ["group_id", "user_id"]
