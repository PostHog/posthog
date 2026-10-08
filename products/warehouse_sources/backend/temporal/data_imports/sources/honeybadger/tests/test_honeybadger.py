import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger import (
    HONEYBADGER_BASE_URL,
    MAX_RATE_LIMIT_SLEEP_SECONDS,
    HoneybadgerResumeConfig,
    HoneybadgerRetryableError,
    _build_params,
    _fetch_page,
    _to_unix_timestamp,
    get_rows,
    honeybadger_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.settings import HONEYBADGER_ENDPOINTS

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


class FakeSession:
    """Maps exact request URLs to canned page payloads and records the call order."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, timeout: Any = None) -> MagicMock:
        self.calls.append(url)
        assert url in self.routes, f"unexpected request: {url}"
        return _response(self.routes[url])


def _make_manager(resume: HoneybadgerResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _run(
    routes: dict[str, Any],
    endpoint: str,
    manager: MagicMock | None = None,
    **kwargs: Any,
) -> tuple[list[list[dict]], FakeSession, MagicMock]:
    session = FakeSession(routes)
    manager = manager if manager is not None else _make_manager()
    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger._make_session",
        return_value=session,
    ):
        batches = list(
            get_rows(
                api_key="token",
                endpoint=endpoint,
                logger=MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return batches, session, manager


class TestHoneybadger:
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
                "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger.time.time",
                return_value=1_000.0,
            ),
            mock.patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger.time.sleep"
            ) as mock_sleep,
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
        session = MagicMock()
        session.get.return_value = _response({}, status=status)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger._make_session",
            return_value=session,
        ):
            assert validate_credentials("token") is expected

    def test_validate_credentials_swallows_connection_errors(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger._make_session",
            return_value=session,
        ):
            assert validate_credentials("token") is False

    def test_projects_paginates_and_checkpoints(self) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}/projects?limit=25&page=2"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {
                "results": [{"id": 1}, {"id": 2}],
                "links": {"next": next_url},
            },
            next_url: {"results": [{"id": 3}], "links": {}},
        }

        batches, _, manager = _run(routes, "projects")

        assert batches == [[{"id": 1}, {"id": 2}], [{"id": 3}]]
        manager.save_state.assert_called_once_with(HoneybadgerResumeConfig(next_url=next_url))

    def test_projects_skips_empty_page_with_next_link(self) -> None:
        # The docs allow a `next` link that resolves to an empty page; the walk must follow
        # `next` links and not yield empty batches.
        next_url = f"{HONEYBADGER_BASE_URL}/projects?limit=25&page=2"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [], "links": {"next": next_url}},
            next_url: {"results": [{"id": 1}], "links": {}},
        }

        batches, _, _ = _run(routes, "projects")

        assert batches == [[{"id": 1}]]

    def test_fan_out_resumes_from_project_bookmark(self) -> None:
        resume_url = f"{HONEYBADGER_BASE_URL}/projects/2/faults?limit=25&page=5"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}, {"id": 2}, {"id": 3}], "links": {}},
            resume_url: {"results": [{"id": 20, "project_id": 2}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/3/faults?limit=25": {
                "results": [{"id": 30, "project_id": 3}],
                "links": {},
            },
        }

        batches, session, _ = _run(
            routes,
            "faults",
            manager=_make_manager(HoneybadgerResumeConfig(next_url=resume_url, project_id=2)),
        )

        # Project 1 is skipped, project 2 resumes at its saved page, project 3 starts fresh.
        assert f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25" not in session.calls
        assert batches == [[{"id": 20, "project_id": 2}], [{"id": 30, "project_id": 3}]]

    def test_affected_users_fan_out_injects_fault_columns_and_bounds_faults(self) -> None:
        faults_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25&occurred_after={WATERMARK_TS}"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            faults_url: {
                "results": [
                    {"id": 10, "last_notice_at": "2023-11-15T00:00:00Z"},
                    {"id": 11, "last_notice_at": "2023-11-16T00:00:00Z"},
                ],
                "links": {},
            },
            # Bare arrays with no paging, and the endpoint takes no time filter.
            f"{HONEYBADGER_BASE_URL}/projects/1/faults/10/affected_users": [
                {
                    "project_id": 999,
                    "fault_id": 999,
                    "fault_last_notice_at": "2020-01-01T00:00:00Z",
                    "user": "bob@example.com",
                    "count": 4,
                }
            ],
            f"{HONEYBADGER_BASE_URL}/projects/1/faults/11/affected_users": [],
        }

        batches, _, manager = _run(
            routes,
            "affected_users",
            should_use_incremental_field=True,
            db_incremental_field_last_value=WATERMARK,
            incremental_field="fault_last_notice_at",
        )

        assert batches == [
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
        manager.save_state.assert_called_once_with(HoneybadgerResumeConfig(project_id=1, fault_id=11))

    def test_alarm_history_reads_triggers_and_resumes_from_alarm_bookmark(self) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}/projects/1/alarms/alarm-b/history?limit=25&page=2"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/alarms?limit=25": {
                "results": [{"id": "alarm-a"}, {"id": "alarm-b"}],
                "links": {},
            },
            # History pages wrap their rows in `triggers`, not `results`.
            f"{HONEYBADGER_BASE_URL}/projects/1/alarms/alarm-b/history?limit=25": {
                "triggers": [{"id": "trigger-2", "state": "alarm"}],
                "links": {"next": next_url},
            },
            next_url: {"triggers": [{"id": "trigger-1", "state": "ok"}], "links": {}},
        }

        batches, session, manager = _run(
            routes, "alarm_history", manager=_make_manager(HoneybadgerResumeConfig(project_id=1, alarm_id="alarm-b"))
        )

        assert f"{HONEYBADGER_BASE_URL}/projects/1/alarms/alarm-a/history?limit=25" not in session.calls
        assert batches == [
            [{"project_id": 1, "alarm_id": "alarm-b", "id": "trigger-2", "state": "alarm"}],
            [{"project_id": 1, "alarm_id": "alarm-b", "id": "trigger-1", "state": "ok"}],
        ]
        manager.save_state.assert_called_once_with(
            HoneybadgerResumeConfig(next_url=next_url, project_id=1, alarm_id="alarm-b")
        )

    def test_occurrences_maps_time_series_pairs_to_rows(self) -> None:
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/occurrences?period=month": [[1510963200, 3], [1511049600, 0]],
        }

        batches, _, _ = _run(routes, "occurrences")

        assert batches == [
            [
                {"project_id": 1, "bucket_start": datetime(2017, 11, 18, tzinfo=UTC), "count": 3},
                {"project_id": 1, "bucket_start": datetime(2017, 11, 19, tzinfo=UTC), "count": 0},
            ]
        ]

    def test_mid_fault_checkpoint_saved_after_yield(self) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25&page=2"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25": {
                "results": [{"id": 10, "project_id": 1}],
                "links": {"next": next_url},
            },
            next_url: {"results": [{"id": 11, "project_id": 1}], "links": {}},
        }
        manager = _make_manager()
        session = FakeSession(routes)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.honeybadger.honeybadger._make_session",
            return_value=session,
        ):
            rows = get_rows(api_key="token", endpoint="faults", logger=MagicMock(), resumable_source_manager=manager)
            # State is only saved AFTER the first batch is yielded (it runs when the consumer
            # pulls again), so a crash re-yields the batch instead of skipping it.
            next(rows)
            manager.save_state.assert_not_called()
            next(rows)
            manager.save_state.assert_called_once_with(HoneybadgerResumeConfig(next_url=next_url, project_id=1))
            list(rows)

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
        response = honeybadger_source(
            api_key="token",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(spec=ResumableSourceManager),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == "desc"
        assert response.partition_keys == expected_partition_keys
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)
