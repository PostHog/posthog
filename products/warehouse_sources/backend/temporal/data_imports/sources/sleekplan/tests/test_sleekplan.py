from datetime import UTC, datetime, timedelta
from typing import Any, cast

from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.settings import (
    SLEEKPLAN_ENDPOINTS,
    SURVEY_LOOKBACK_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.sleekplan import (
    SleekplanPaginator,
    SleekplanResumeConfig,
    _format_survey_date,
    _incremental_window,
    _resolve_incremental_field,
    _resource,
    sleekplan_source,
    validate_credentials,
)

TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.sleekplan.sleekplan"


class _FakeResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _page_response(body: Any) -> Mock:
    response = Mock()
    response.json.return_value = body
    return response


def _manager(*, can_resume: bool = False, state: SleekplanResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


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

    def test_first_request_starts_at_page_one(self) -> None:
        request = Request()

        SleekplanPaginator().init_request(request)

        assert request.params == {"page": 1}

    def test_resume_state_round_trips_into_the_request(self) -> None:
        paginator = SleekplanPaginator()
        paginator.update_state(_page_response({"data": {"items": {"1": {}}, "has_more": True}}), [{}])
        state = paginator.get_resume_state()

        resumed = SleekplanPaginator()
        resumed.set_resume_state(cast(dict, state))
        request = Request()
        resumed.init_request(request)

        assert request.params == {"page": 2}

    def test_resume_state_is_none_once_pagination_is_done(self) -> None:
        paginator = SleekplanPaginator()

        paginator.update_state(_page_response({"data": {"items": {"1": {}}, "has_more": False}}), [{}])

        assert paginator.get_resume_state() is None


class TestSurveyDateFormatting:
    def test_applies_the_replacement_window_lookback(self) -> None:
        value = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)

        assert _format_survey_date(value) == (value - timedelta(days=SURVEY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    def test_caps_a_future_cursor_at_today(self) -> None:
        formatted = _format_survey_date(datetime(2999, 1, 1, tzinfo=UTC))

        assert formatted <= datetime.now(UTC).strftime("%Y-%m-%d")

    def test_clamps_to_the_epoch(self) -> None:
        # Subtracting the lookback from an early cursor would otherwise produce a pre-1970 date.
        assert _format_survey_date(datetime(1970, 1, 5, tzinfo=UTC)) == "1970-01-01"

    @parameterized.expand([("initial_seed", "1970-01-01"), ("unparseable", "not-a-date")])
    def test_passes_through_a_non_datetime_value(self, _name: str, value: str) -> None:
        assert _format_survey_date(value) == value

    def test_incremental_window_targets_the_date_start_filter(self) -> None:
        window = _incremental_window("updated")

        assert window["cursor_path"] == "updated"
        assert window["start_param"] == "date_start"
        assert window["convert"] is _format_survey_date


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
        ]
    )
    def test_endpoint_request_shape(self, name: str, path: str, selector: str, extra_params: dict) -> None:
        resource = _resource(SLEEKPLAN_ENDPOINTS[name], should_use_incremental_field=False, incremental_field=None)

        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["path"] == path
        assert endpoint["data_selector"] == selector
        assert endpoint["params"] == {"per_page": 100, **extra_params}
        assert isinstance(endpoint["paginator"], SleekplanPaginator)

    @parameterized.expand(["Users", "Posts", "Updates"])
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
        with patch(f"{TRANSPORT}.validate_via_probe", return_value=(status_code == 200, status_code)):
            assert validate_credentials("key", schema_name=schema_name) == expected

    def test_unreachable_api_is_reported(self) -> None:
        with patch(f"{TRANSPORT}.validate_via_probe", return_value=(False, None)):
            assert validate_credentials("key") == (False, "Could not reach the Sleekplan API.")

    def test_probe_sends_the_key_as_a_bearer_token(self) -> None:
        with patch(f"{TRANSPORT}.validate_via_probe", return_value=(True, 200)) as mock_probe:
            validate_credentials("secret-key")

        _, kwargs = mock_probe.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer secret-key"

    def test_probe_session_redacts_the_key_and_disables_sample_capture(self) -> None:
        # Users/posts/comments carry emails and free-text feedback the generic scrubber can't
        # anonymize, so the probe -- like every other Sleekplan request -- must not be captured.
        with (
            patch(f"{TRANSPORT}.validate_via_probe", return_value=(True, 200)) as mock_probe,
            patch(f"{TRANSPORT}.make_tracked_session") as mock_make_session,
        ):
            validate_credentials("secret-key")
            mock_probe.call_args.args[0]()

        mock_make_session.assert_called_once_with(redact_values=("secret-key",), capture=False)


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
        with patch(f"{TRANSPORT}.rest_api_resource", return_value=Mock()):
            response = sleekplan_source(
                api_key="key", endpoint=name, team_id=1, job_id="job-1", resumable_source_manager=_manager()
            )

        assert response.name == name
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        assert response.partition_keys == ([partition_key] if partition_key else None)

    def test_uses_framework_bearer_auth(self) -> None:
        with patch(f"{TRANSPORT}.rest_api_resource", return_value=Mock()) as mock_resource:
            sleekplan_source(
                api_key="secret-key", endpoint="Posts", team_id=1, job_id="job-1", resumable_source_manager=_manager()
            )

        (rest_config, *_), _ = mock_resource.call_args
        assert rest_config["client"]["auth"] == {"type": "bearer", "token": "secret-key"}
        assert rest_config["client"]["base_url"] == "https://api.sleekplan.com/v1"

    def test_session_redacts_the_key_and_disables_sample_capture(self) -> None:
        # Posts/comments/votes/survey responses carry emails and free-text feedback the generic
        # scrubber can't anonymize, so sample capture must stay off (still metered and logged).
        with (
            patch(f"{TRANSPORT}.rest_api_resource", return_value=Mock()) as mock_resource,
            patch(f"{TRANSPORT}.make_tracked_session") as mock_make_session,
        ):
            sleekplan_source(
                api_key="secret-key", endpoint="Posts", team_id=1, job_id="job-1", resumable_source_manager=_manager()
            )

        (rest_config, *_), _ = mock_resource.call_args
        mock_make_session.assert_called_once_with(redact_values=("secret-key",), capture=False)
        assert rest_config["client"]["session"] is mock_make_session.return_value

    def test_seeds_the_paginator_from_saved_state(self) -> None:
        manager = _manager(can_resume=True, state=SleekplanResumeConfig(page=4))

        with patch(f"{TRANSPORT}.rest_api_resource", return_value=Mock()) as mock_resource:
            sleekplan_source(
                api_key="key", endpoint="Posts", team_id=1, job_id="job-1", resumable_source_manager=manager
            )

        assert mock_resource.call_args.kwargs["initial_paginator_state"] == {"page": 4}

    def test_ignores_a_fan_out_checkpoint_left_by_another_schema(self) -> None:
        manager = _manager(can_resume=True, state=SleekplanResumeConfig(fanout_state={"completed": []}))

        with patch(f"{TRANSPORT}.rest_api_resource", return_value=Mock()) as mock_resource:
            sleekplan_source(
                api_key="key", endpoint="Posts", team_id=1, job_id="job-1", resumable_source_manager=manager
            )

        assert mock_resource.call_args.kwargs["initial_paginator_state"] is None

    @parameterized.expand(
        [
            ("saves_next_page", {"page": 5}, SleekplanResumeConfig(page=5)),
            ("ignores_terminal_state", None, None),
        ]
    )
    def test_resume_hook(self, _name: str, state: dict | None, expected: SleekplanResumeConfig | None) -> None:
        manager = _manager()

        with patch(f"{TRANSPORT}.rest_api_resource", return_value=Mock()) as mock_resource:
            sleekplan_source(
                api_key="key", endpoint="Posts", team_id=1, job_id="job-1", resumable_source_manager=manager
            )

        mock_resource.call_args.kwargs["resume_hook"](state)

        if expected is None:
            manager.save_state.assert_not_called()
        else:
            manager.save_state.assert_called_once_with(expected)


class TestFanOutSource:
    def test_comments_carry_their_parent_post_id(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources",
            return_value=[
                _FakeResource("Posts", [{"feedback_id": 77}]),
                _FakeResource("Comments", [{"comment_id": 5, "_Posts_feedback_id": 77}]),
            ],
        ):
            response = sleekplan_source(
                api_key="key", endpoint="Comments", team_id=1, job_id="job-1", resumable_source_manager=_manager()
            )
            rows = list(cast(Any, response.items()))

        assert rows == [{"comment_id": 5, "feedback_id": 77}]

    @parameterized.expand(
        [
            ("identified_voter", {"user": {"user_id": 9}}, 9),
            ("missing_voter", {}, None),
        ]
    )
    def test_votes_lift_the_voter_id_to_the_row_root(self, _name: str, vote_row: dict, expected: int | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources",
            return_value=[
                _FakeResource("Posts", [{"feedback_id": 77}]),
                _FakeResource("Votes", [{"vote": 1, "_Posts_feedback_id": 77, **vote_row}]),
            ],
        ):
            response = sleekplan_source(
                api_key="key", endpoint="Votes", team_id=1, job_id="job-1", resumable_source_manager=_manager()
            )
            rows = list(cast(Any, response.items()))

        # The (post, user) pair is the only primary key a vote has.
        assert rows[0]["feedback_id"] == 77
        assert rows[0]["user_id"] == expected

    @parameterized.expand(["Comments", "Votes"])
    def test_fan_out_pages_with_per_page(self, name: str) -> None:
        with patch(f"{TRANSPORT}.build_dependent_resource", return_value=_FakeResource(name, [])) as mock_build:
            sleekplan_source(
                api_key="key", endpoint=name, team_id=1, job_id="job-1", resumable_source_manager=_manager()
            )

        kwargs = mock_build.call_args.kwargs
        assert kwargs["page_size_param"] == "per_page"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], SleekplanPaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], SleekplanPaginator)
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "data.items.*"

    def test_fan_out_resumes_from_its_own_checkpoint(self) -> None:
        fanout_state = {"completed": ["/post/1/comments"], "current": "/post/2/comments", "child_state": {"page": 3}}
        manager = _manager(can_resume=True, state=SleekplanResumeConfig(fanout_state=fanout_state))

        with patch(f"{TRANSPORT}.build_dependent_resource", return_value=_FakeResource("Comments", [])) as mock_build:
            sleekplan_source(
                api_key="key", endpoint="Comments", team_id=1, job_id="job-1", resumable_source_manager=manager
            )

        assert mock_build.call_args.kwargs["initial_paginator_state"] == fanout_state

        mock_build.call_args.kwargs["resume_hook"](fanout_state)
        manager.save_state.assert_called_once_with(SleekplanResumeConfig(fanout_state=fanout_state))

    def test_fan_out_ignores_a_page_checkpoint_left_by_another_schema(self) -> None:
        manager = _manager(can_resume=True, state=SleekplanResumeConfig(page=9))

        with patch(f"{TRANSPORT}.build_dependent_resource", return_value=_FakeResource("Comments", [])) as mock_build:
            sleekplan_source(
                api_key="key", endpoint="Comments", team_id=1, job_id="job-1", resumable_source_manager=manager
            )

        assert mock_build.call_args.kwargs["initial_paginator_state"] is None
