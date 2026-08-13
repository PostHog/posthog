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

    def test_build_params_full_refresh(self) -> None:
        params = _build_params(HONEYBADGER_ENDPOINTS["faults"], MagicMock(), False, WATERMARK, None)
        assert params == {"limit": 25}

    def test_build_params_defaults_to_endpoint_default_field(self) -> None:
        params = _build_params(HONEYBADGER_ENDPOINTS["faults"], MagicMock(), True, WATERMARK, None)
        assert params == {"limit": 25, "occurred_after": WATERMARK_TS}

    def test_build_params_honors_user_chosen_field(self) -> None:
        params = _build_params(HONEYBADGER_ENDPOINTS["faults"], MagicMock(), True, WATERMARK, "created_at")
        assert params == {"limit": 25, "created_after": WATERMARK_TS}

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

    def test_fetch_page_retries_transient_error_then_succeeds(self) -> None:
        session = MagicMock()
        session.get.side_effect = [_response(None, status=500), _response({"results": [{"id": 1}]})]
        result = _fetch_page.retry_with(wait=wait_none())(session, f"{HONEYBADGER_BASE_URL}/projects", MagicMock())  # type: ignore[attr-defined]
        assert result == {"results": [{"id": 1}]}
        assert session.get.call_count == 2

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

    def test_projects_resumes_from_saved_url(self) -> None:
        next_url = f"{HONEYBADGER_BASE_URL}/projects?limit=25&page=2"
        routes = {next_url: {"results": [{"id": 3}], "links": {}}}

        batches, session, _ = _run(
            routes, "projects", manager=_make_manager(HoneybadgerResumeConfig(next_url=next_url))
        )

        assert batches == [[{"id": 3}]]
        assert session.calls == [next_url]

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

    def test_faults_fan_out_over_projects(self) -> None:
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}, {"id": 2}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25": {
                "results": [{"id": 10, "project_id": 1}],
                "links": {},
            },
            f"{HONEYBADGER_BASE_URL}/projects/2/faults?limit=25": {
                "results": [{"id": 20, "project_id": 2}],
                "links": {},
            },
        }

        batches, _, manager = _run(routes, "faults")

        assert batches == [[{"id": 10, "project_id": 1}], [{"id": 20, "project_id": 2}]]
        # Bookmark advanced to the next project so a crash between projects resumes there.
        manager.save_state.assert_called_once_with(HoneybadgerResumeConfig(project_id=2))

    def test_sites_rows_gain_parent_project_id(self) -> None:
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 7}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/7/sites?limit=25": {
                "results": [{"id": "site-uuid", "name": "Main site"}],
                "links": {},
            },
        }

        batches, _, _ = _run(routes, "sites")

        assert batches == [[{"project_id": 7, "id": "site-uuid", "name": "Main site"}]]

    @pytest.mark.parametrize(
        ("incremental_field", "expected_param"),
        [
            (None, "occurred_after"),  # endpoint default: last_notice_at
            ("created_at", "created_after"),
            ("last_notice_at", "occurred_after"),
        ],
    )
    def test_faults_incremental_uses_server_side_filter(
        self, incremental_field: str | None, expected_param: str
    ) -> None:
        child_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25&{expected_param}={WATERMARK_TS}"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            child_url: {"results": [{"id": 10, "project_id": 1}], "links": {}},
        }

        _, session, _ = _run(
            routes,
            "faults",
            should_use_incremental_field=True,
            db_incremental_field_last_value=WATERMARK,
            incremental_field=incremental_field,
        )

        assert child_url in session.calls

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

    def test_fan_out_restarts_when_bookmarked_project_vanished(self) -> None:
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25": {
                "results": [{"id": 10, "project_id": 1}],
                "links": {},
            },
        }

        batches, _, _ = _run(
            routes,
            "faults",
            manager=_make_manager(HoneybadgerResumeConfig(next_url="https://app.honeybadger.io/stale", project_id=99)),
        )

        assert batches == [[{"id": 10, "project_id": 1}]]

    def test_notices_fan_out_over_projects_and_faults(self) -> None:
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25": {"results": [{"id": 10}, {"id": 11}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults/10/notices?limit=25": {
                "results": [{"id": "uuid-1", "fault_id": 10}],
                "links": {},
            },
            f"{HONEYBADGER_BASE_URL}/projects/1/faults/11/notices?limit=25": {
                "results": [{"id": "uuid-2", "fault_id": 11}],
                "links": {},
            },
        }

        batches, _, manager = _run(routes, "notices")

        assert batches == [
            [{"project_id": 1, "id": "uuid-1", "fault_id": 10}],
            [{"project_id": 1, "id": "uuid-2", "fault_id": 11}],
        ]
        manager.save_state.assert_called_once_with(HoneybadgerResumeConfig(project_id=1, fault_id=11))

    def test_notices_incremental_bounds_fault_enumeration(self) -> None:
        # The notice watermark is also applied as `occurred_after` on the fault listing:
        # faults whose last notice predates the watermark can't have new notices.
        faults_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25&occurred_after={WATERMARK_TS}"
        notices_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults/10/notices?limit=25&created_after={WATERMARK_TS}"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            faults_url: {"results": [{"id": 10}], "links": {}},
            notices_url: {"results": [{"id": "uuid-1", "fault_id": 10}], "links": {}},
        }

        _, session, _ = _run(
            routes,
            "notices",
            should_use_incremental_field=True,
            db_incremental_field_last_value=WATERMARK,
            incremental_field="created_at",
        )

        assert faults_url in session.calls
        assert notices_url in session.calls

    def test_notices_resume_from_fault_bookmark(self) -> None:
        resume_url = f"{HONEYBADGER_BASE_URL}/projects/1/faults/11/notices?limit=25&page=3"
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25": {"results": [{"id": 10}, {"id": 11}], "links": {}},
            resume_url: {"results": [{"id": "uuid-2", "fault_id": 11}], "links": {}},
        }

        batches, session, _ = _run(
            routes,
            "notices",
            manager=_make_manager(HoneybadgerResumeConfig(next_url=resume_url, project_id=1, fault_id=11)),
        )

        # Fault 10 is skipped; fault 11 resumes at its saved page URL.
        assert f"{HONEYBADGER_BASE_URL}/projects/1/faults/10/notices?limit=25" not in session.calls
        assert batches == [[{"project_id": 1, "id": "uuid-2", "fault_id": 11}]]

    def test_notices_discards_saved_url_when_bookmarked_fault_vanished(self) -> None:
        routes = {
            f"{HONEYBADGER_BASE_URL}/projects?limit=25": {"results": [{"id": 1}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults?limit=25": {"results": [{"id": 10}], "links": {}},
            f"{HONEYBADGER_BASE_URL}/projects/1/faults/10/notices?limit=25": {
                "results": [{"id": "uuid-1", "fault_id": 10}],
                "links": {},
            },
        }

        batches, session, _ = _run(
            routes,
            "notices",
            manager=_make_manager(
                HoneybadgerResumeConfig(next_url="https://app.honeybadger.io/stale", project_id=1, fault_id=99)
            ),
        )

        # The stale fault's page URL must not seed another fault's pagination.
        assert "https://app.honeybadger.io/stale" not in session.calls
        assert batches == [[{"project_id": 1, "id": "uuid-1", "fault_id": 10}]]

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
