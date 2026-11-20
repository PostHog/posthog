import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock
from unittest.mock import MagicMock

import requests
from tenacity import wait_none

from products.warehouse_sources.sources.honeybadger._config import HoneybadgerSourceConfig
from products.warehouse_sources.sources.honeybadger.honeybadger import (
    HONEYBADGER_BASE_URL,
    MAX_RATE_LIMIT_SLEEP_SECONDS,
    HoneybadgerResumeConfig,
    HoneybadgerRetryableError,
    _build_params,
    _fetch_page,
    _to_unix_timestamp,
    validate_credentials,
)
from products.warehouse_sources.sources.honeybadger.settings import HONEYBADGER_ENDPOINTS
from products.warehouse_sources.sources.honeybadger.source import HoneybadgerSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)

# 2023-11-14T22:13:20Z
WATERMARK_TS = 1_700_000_000
WATERMARK = datetime.fromtimestamp(WATERMARK_TS, tz=UTC)

# tenacity exposes the undecorated function via `__wrapped__`, so status classification can be
# tested without paying the retry waits; it's not part of the wrapped callable's type.
_fetch_page_once = _fetch_page.__wrapped__  # type: ignore[attr-defined]


def _response(payload: Any = None, status: int = 200, headers: dict[str, str] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.headers = headers or {}
    response.json.return_value = payload if payload is not None else {}
    response.text = json.dumps(payload) if payload is not None else ""
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error: error for url: {HONEYBADGER_BASE_URL}", response=response
        )
    else:
        response.raise_for_status.side_effect = None
    return response


class TestHoneybadger:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(HoneybadgerSource(), HoneybadgerSourceConfig(api_key="token"))

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (WATERMARK, WATERMARK_TS),
            (datetime(2023, 11, 14, 22, 13, 20), WATERMARK_TS),  # naive datetimes are treated as UTC
            (date(2023, 11, 14), 1_699_920_000),
            (WATERMARK_TS, WATERMARK_TS),
            (float(WATERMARK_TS), WATERMARK_TS),
            ("2023-11-14T22:13:20Z", WATERMARK_TS),
            ("2023-11-14T22:13:20+00:00", WATERMARK_TS),
        ],
    )
    def test_to_unix_timestamp(self, value: Any, expected: int) -> None:
        assert _to_unix_timestamp(value) == expected

    def test_build_params_defaults_to_endpoint_default_field(self) -> None:
        params = _build_params(HONEYBADGER_ENDPOINTS["faults"], MagicMock(), True, WATERMARK, None)
        assert params == {"limit": 25, "occurred_after": WATERMARK_TS}

    def test_build_params_unknown_field_falls_back_to_full_walk(self) -> None:
        logger = MagicMock()
        params = _build_params(HONEYBADGER_ENDPOINTS["faults"], logger, True, WATERMARK, "not_a_field")
        assert params == {"limit": 25}
        logger.warning.assert_called_once()

    @pytest.mark.parametrize("status", [429, 500, 502])
    def test_fetch_page_raises_retryable_on_transient_statuses(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(None, status=status)
        with pytest.raises(HoneybadgerRetryableError):
            _fetch_page_once(session, f"{HONEYBADGER_BASE_URL}/projects", MagicMock())

    @pytest.mark.parametrize("status", [401, 403, 404])
    def test_fetch_page_raises_http_error_on_permanent_statuses(self, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _response(None, status=status)
        with pytest.raises(requests.HTTPError):
            _fetch_page_once(session, f"{HONEYBADGER_BASE_URL}/projects", MagicMock())

    @pytest.mark.parametrize(
        ("reset_offset", "expected_sleep"),
        [
            (30, 30.0),
            (100_000, MAX_RATE_LIMIT_SLEEP_SECONDS),  # capped
            (-10, 1.0),  # already reset — minimal sleep
        ],
    )
    def test_fetch_page_rate_limit_sleeps_toward_reset_and_retries(
        self, reset_offset: int, expected_sleep: float
    ) -> None:
        session = MagicMock()
        session.get.return_value = _response(
            None, status=403, headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(1_000 + reset_offset)}
        )
        with (
            mock.patch(
                "products.warehouse_sources.sources.honeybadger.honeybadger.time.time",
                return_value=1_000.0,
            ),
            mock.patch("products.warehouse_sources.sources.honeybadger.honeybadger.time.sleep") as mock_sleep,
        ):
            with pytest.raises(HoneybadgerRetryableError):
                _fetch_page_once(session, f"{HONEYBADGER_BASE_URL}/projects", MagicMock())
        mock_sleep.assert_called_once_with(expected_sleep)

    def test_fetch_page_does_not_retry_auth_403(self) -> None:
        # A 403 without an exhausted quota header is a credential problem, not a rate limit.
        session = MagicMock()
        session.get.return_value = _response(None, status=403)
        with pytest.raises(requests.HTTPError):
            _fetch_page.retry_with(wait=wait_none())(session, f"{HONEYBADGER_BASE_URL}/projects", MagicMock())  # type: ignore[attr-defined]
        assert session.get.call_count == 1

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.com/v2/projects",
            "http://app.honeybadger.io/v2/projects",  # https only — Basic auth in cleartext otherwise
            "https://app.honeybadger.io.evil.com/v2/projects",
            "https://app.honeybadger.io@evil.com/v2/projects",
        ],
    )
    def test_fetch_page_refuses_off_origin_urls(self, url: str) -> None:
        # A poisoned `links.next` or tampered resume URL must never receive the credentialed
        # session — the request is refused before it is sent.
        session = MagicMock()
        with pytest.raises(ValueError, match="Refusing to fetch"):
            _fetch_page_once(session, url, MagicMock())
        session.get.assert_not_called()

    @pytest.mark.parametrize(("status", "expected"), [(200, True), (403, False)])
    def test_validate_credentials(self, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status, json={})]) as network:
            assert validate_credentials("token") is expected
        assert [request.path for request in network.requests_log] == ["/v2/projects"]
        assert network.session_options == [{"headers": {"Accept": "application/json"}, "capture": False}]

    def test_validate_credentials_swallows_connection_errors(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            assert validate_credentials("token") is False
        assert {request.path for request in network.requests_log} == {"/v2/projects"}

    @pytest.mark.parametrize(
        ("endpoint", "expected_path", "expected_limit"),
        [
            ("projects", "/v2/projects", "25"),
            ("accounts", "/v2/accounts", None),
        ],
    )
    def test_top_level_list_paginates_and_checkpoints(
        self, endpoint: str, expected_path: str, expected_limit: str | None
    ) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}{expected_path.removeprefix('/v2')}?page=2"
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(json={"results": [{"id": 1}, {"id": 2}], "links": {"next": next_url}}),
                ScriptedResponse(json={"results": [{"id": 3}], "links": {}}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        assert result.paths == [expected_path, expected_path]
        assert result.params("limit")[0] == expected_limit
        assert result.params("page") == [None, "2"]
        assert result.saved_states == [HoneybadgerResumeConfig(next_url=next_url)]

    def test_projects_skips_empty_page_with_next_link(self) -> None:
        # The docs allow a `next` link that resolves to an empty page; the walk must follow
        # `next` links and not yield empty batches.
        next_url = f"{HONEYBADGER_BASE_URL}/projects?limit=25&page=2"
        result = self._driver().run(
            "projects",
            [
                ScriptedResponse(json={"results": [], "links": {"next": next_url}}),
                ScriptedResponse(json={"results": [{"id": 1}], "links": {}}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": 1}]]
        assert result.params("page") == [None, "2"]

    def test_fan_out_resumes_from_project_bookmark(self) -> None:
        resume_url = f"{HONEYBADGER_BASE_URL}/projects/2/faults?limit=25&page=5"
        result = self._driver().run(
            "faults",
            [
                ScriptedResponse(json={"results": [{"id": 1}, {"id": 2}, {"id": 3}], "links": {}}),
                ScriptedResponse(json={"results": [{"id": 20, "project_id": 2}], "links": {}}),
                ScriptedResponse(json={"results": [{"id": 30, "project_id": 3}], "links": {}}),
            ],
            resume_state=HoneybadgerResumeConfig(next_url=resume_url, project_id=2),
        )

        # Project 1 is skipped, project 2 resumes at its saved page, project 3 starts fresh.
        assert result.raised is None
        assert result.urls[1] == resume_url
        assert result.paths == ["/v2/projects", "/v2/projects/2/faults", "/v2/projects/3/faults"]
        assert result.items == [[{"id": 20, "project_id": 2}], [{"id": 30, "project_id": 3}]]

    def test_affected_users_fan_out_injects_fault_columns_and_bounds_faults(self) -> None:
        result = self._driver().run(
            "affected_users",
            [
                ScriptedResponse(json={"results": [{"id": 1}], "links": {}}),
                ScriptedResponse(
                    json={
                        "results": [
                            {"id": 10, "last_notice_at": "2023-11-15T00:00:00Z"},
                            {"id": 11, "last_notice_at": "2023-11-16T00:00:00Z"},
                        ],
                        "links": {},
                    }
                ),
                # Bare arrays with no paging, and the endpoint takes no time filter.
                ScriptedResponse(
                    json=[
                        {
                            "project_id": 999,
                            "fault_id": 999,
                            "fault_last_notice_at": "2020-01-01T00:00:00Z",
                            "user": "bob@example.com",
                            "count": 4,
                        }
                    ]
                ),
                ScriptedResponse(json=[]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value=WATERMARK,
            incremental_field="fault_last_notice_at",
        )

        assert result.raised is None
        assert result.items == [
            [
                {
                    "project_id": 1,
                    "fault_id": 10,
                    "fault_last_notice_at": "2023-11-15T00:00:00Z",
                    "user": "bob@example.com",
                    "count": 4,
                }
            ]
        ]
        assert result.paths == [
            "/v2/projects",
            "/v2/projects/1/faults",
            "/v2/projects/1/faults/10/affected_users",
            "/v2/projects/1/faults/11/affected_users",
        ]
        assert result.params("occurred_after") == [None, str(WATERMARK_TS), None, None]
        assert result.saved_states == [HoneybadgerResumeConfig(project_id=1, fault_id=11)]

    def test_alarm_history_reads_triggers_and_resumes_from_alarm_bookmark(self) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}/projects/1/alarms/alarm-b/history?limit=25&page=2"
        result = self._driver().run(
            "alarm_history",
            [
                ScriptedResponse(json={"results": [{"id": 1}], "links": {}}),
                ScriptedResponse(json={"results": [{"id": "alarm-a"}, {"id": "alarm-b"}], "links": {}}),
                # History pages wrap their rows in `triggers`, not `results`.
                ScriptedResponse(
                    json={"triggers": [{"id": "trigger-2", "state": "alarm"}], "links": {"next": next_url}}
                ),
                ScriptedResponse(json={"triggers": [{"id": "trigger-1", "state": "ok"}], "links": {}}),
            ],
            resume_state=HoneybadgerResumeConfig(project_id=1, alarm_id="alarm-b"),
        )

        assert result.raised is None
        assert result.paths == [
            "/v2/projects",
            "/v2/projects/1/alarms",
            "/v2/projects/1/alarms/alarm-b/history",
            "/v2/projects/1/alarms/alarm-b/history",
        ]
        assert result.params("page") == [None, None, None, "2"]
        assert result.items == [
            [{"project_id": 1, "alarm_id": "alarm-b", "id": "trigger-2", "state": "alarm"}],
            [{"project_id": 1, "alarm_id": "alarm-b", "id": "trigger-1", "state": "ok"}],
        ]
        assert result.saved_states == [HoneybadgerResumeConfig(next_url=next_url, project_id=1, alarm_id="alarm-b")]

    def test_occurrences_maps_time_series_pairs_to_rows(self) -> None:
        result = self._driver().run(
            "occurrences",
            [
                ScriptedResponse(json={"results": [{"id": 1}], "links": {}}),
                ScriptedResponse(json=[[1510963200, 3], [1511049600, 0]]),
            ],
        )

        assert result.raised is None
        assert result.params("period") == [None, "month"]
        assert result.items == [
            [
                {"project_id": 1, "bucket_start": datetime(2017, 11, 18, tzinfo=UTC), "count": 3},
                {"project_id": 1, "bucket_start": datetime(2017, 11, 19, tzinfo=UTC), "count": 0},
            ]
        ]

    @pytest.mark.parametrize(
        ("endpoint", "pairs", "expected_rows"),
        [
            (
                "notices_per_day",
                [["2023-11-13T00:00:00.000000+00:00", 7], ["2023-11-14T00:00:00Z", 0]],
                [
                    {"project_id": 1, "day": datetime(2023, 11, 13, tzinfo=UTC), "count": 7},
                    {"project_id": 1, "day": datetime(2023, 11, 14, tzinfo=UTC), "count": 0},
                ],
            ),
            (
                "notices_by_class",
                [["RuntimeError", 12], ["SocketError", 3]],
                [
                    {"project_id": 1, "klass": "RuntimeError", "count": 12},
                    {"project_id": 1, "klass": "SocketError", "count": 3},
                ],
            ),
        ],
    )
    def test_reports_send_explicit_window_and_map_pairs_to_rows(
        self, endpoint: str, pairs: list[Any], expected_rows: list[dict]
    ) -> None:
        with time_machine.travel(datetime(2023, 12, 1, 12, 30, 15, 123456, tzinfo=UTC), tick=False):
            result = self._driver().run(
                endpoint,
                [
                    ScriptedResponse(json={"results": [{"id": 1}], "links": {}}),
                    ScriptedResponse(json=pairs),
                ],
            )

        assert result.raised is None
        assert result.paths == ["/v2/projects", f"/v2/projects/1/reports/{endpoint}"]
        assert result.params("start") == [None, "2023-11-01T12:30:15+00:00"]
        assert result.params("limit") == ["25", None]
        assert result.items == [expected_rows]

    @pytest.mark.parametrize(
        ("watermark", "expected_start"),
        [
            (WATERMARK, "2023-11-14T22:13:20+00:00"),
            (date(2023, 11, 14), "2023-11-14T00:00:00+00:00"),
            ("2023-11-14T00:00:00Z", "2023-11-14T00:00:00+00:00"),
        ],
    )
    def test_notices_per_day_incremental_starts_at_watermark(self, watermark: Any, expected_start: str) -> None:
        with time_machine.travel(datetime(2023, 12, 1, tzinfo=UTC), tick=False):
            result = self._driver().run(
                "notices_per_day",
                [
                    ScriptedResponse(json={"results": [{"id": 1}], "links": {}}),
                    ScriptedResponse(json=[]),
                ],
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
                incremental_field="day",
            )

        assert result.raised is None
        assert result.params("start") == [None, expected_start]
        assert result.items == []

    @pytest.mark.parametrize(
        ("endpoint", "parent_path", "parent_key", "parent_name_column", "parent_ids", "child_path"),
        [
            ("team_members", "/v2/teams", "team_id", "team_name", [1, 2], "/v2/teams/{}/team_members"),
            ("account_users", "/v2/accounts", "account_id", "account_name", ["abc", "xyz"], "/v2/accounts/{}/users"),
        ],
    )
    def test_root_fan_out_walks_each_parent_and_stages_state_before_yield(
        self,
        endpoint: str,
        parent_path: str,
        parent_key: str,
        parent_name_column: str,
        parent_ids: list[Any],
        child_path: str,
    ) -> None:
        first, second = parent_ids
        next_url = f"{HONEYBADGER_BASE_URL}{child_path.removeprefix('/v2').format(first)}?page=2"
        result = self._driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={"results": [{"id": first, "name": "First"}, {"id": second, "name": "Second"}], "links": {}}
                ),
                ScriptedResponse(json={"results": [{"id": 10}], "links": {"next": next_url}}),
                ScriptedResponse(json={"results": [{"id": 11}], "links": {}}),
                # A parent with no members still ends the walk cleanly.
                ScriptedResponse(json={"results": []}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            parent_path,
            child_path.format(first),
            child_path.format(first),
            child_path.format(second),
        ]
        assert result.params("limit") == [None, None, None, None]
        assert result.items == [
            [{"id": 10, parent_key: first, parent_name_column: "First"}],
            [{"id": 11, parent_key: first, parent_name_column: "First"}],
        ]
        assert result.saved_states == [
            HoneybadgerResumeConfig(next_url=next_url, **{parent_key: first}),
            HoneybadgerResumeConfig(**{parent_key: second}),
        ]

    @pytest.mark.parametrize(
        ("resume_state", "expected_paths", "expected_pages"),
        [
            (
                HoneybadgerResumeConfig(next_url=f"{HONEYBADGER_BASE_URL}/teams/2/team_members?page=3", team_id=2),
                ["/v2/teams", "/v2/teams/2/team_members", "/v2/teams/3/team_members"],
                [None, "3", None],
            ),
            (
                HoneybadgerResumeConfig(team_id=3),
                ["/v2/teams", "/v2/teams/3/team_members"],
                [None, None],
            ),
            (
                # The bookmarked team was deleted: start over, and don't use its saved page URL.
                HoneybadgerResumeConfig(next_url=f"{HONEYBADGER_BASE_URL}/teams/9/team_members?page=3", team_id=9),
                ["/v2/teams", "/v2/teams/1/team_members", "/v2/teams/2/team_members", "/v2/teams/3/team_members"],
                [None, None, None, None],
            ),
        ],
    )
    def test_team_members_resumes_from_team_bookmark(
        self, resume_state: HoneybadgerResumeConfig, expected_paths: list[str], expected_pages: list[str | None]
    ) -> None:
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v2/teams":
                return ScriptedResponse(json={"results": [{"id": 1}, {"id": 2}, {"id": 3}], "links": {}})
            return ScriptedResponse(json={"results": [{"id": 100}], "links": {}})

        result = self._driver().run("team_members", answer, resume_state=resume_state)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("page") == expected_pages

    def test_mid_fault_checkpoint_saved_after_yield(self) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25&page=2"

        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/v2/projects":
                return ScriptedResponse(json={"results": [{"id": 1}], "links": {}})
            if request.param("page") is None:
                return ScriptedResponse(json={"results": [{"id": 10, "project_id": 1}], "links": {"next": next_url}})
            raise requests.ConnectionError("connection lost on page 2")

        result = self._driver().run("faults", answer)

        # The first batch is written before the source saves its next-page state, so the safe point
        # after the save commits that state, and a retry starts at page 2 without losing the batch.
        assert isinstance(result.raised, requests.ConnectionError)
        assert result.items == [[{"id": 10, "project_id": 1}]]
        assert result.saved_states == [HoneybadgerResumeConfig(next_url=next_url, project_id=1)]
        assert result.committed_states == [HoneybadgerResumeConfig(next_url=next_url, project_id=1)]
        assert result.final_state == HoneybadgerResumeConfig(next_url=next_url, project_id=1)
        assert result.params("page")[0:2] == [None, None]

    @pytest.mark.parametrize(
        ("endpoint", "expected_primary_keys", "expected_partition_keys"),
        [
            ("projects", ["id"], None),
            ("faults", ["project_id", "id"], ["created_at"]),
            ("notices", ["id"], ["created_at"]),
            ("deploys", ["project_id", "id"], ["created_at"]),
            ("sites", ["project_id", "id"], None),
        ],
    )
    def test_source_response_shape(
        self, endpoint: str, expected_primary_keys: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        result = self._driver().run(endpoint, [ScriptedResponse(json={"results": [], "links": {}})])
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == "desc"
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)
