import json
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.moengage import (
    MoEngageResumeConfig,
    MoEngageSearchPaginator,
    MoEngageStatsPaginator,
    _explode_stats,
    _report_days,
    moengage_base_url,
    moengage_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.settings import (
    ATTRIBUTION_TYPE,
    DEFAULT_BACKFILL_DAYS,
    METRIC_TYPE,
    MOENGAGE_DATA_CENTERS,
    REPORT_WINDOW_DAYS,
    SEARCH_PAGE_SIZE,
    STATS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.moengage.source import MoEngageSource

# RESTClient builds its session via make_tracked_session in the rest_client module; the daily
# report shares one session built in the moengage module instead.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
MOENGAGE_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.moengage.moengage.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    resp.url = "https://api-01.moengage.com/"
    return resp


def _campaigns_page(count: int) -> Response:
    return _response({"data": {"campaigns": [{"id": f"c{i}", "created_at": "2025-01-01"} for i in range(count)]}})


def _stats_page(campaign_ids: list[str], *, current_page: int | None = 1, total_pages: int | None = 1) -> Response:
    body: dict[str, Any] = {
        "data": {
            campaign_id: [
                {
                    "platforms": {
                        "android": {
                            "locales": {
                                "all_locales": {
                                    "variations": {
                                        "all_variations": {
                                            "performance_stats": {"attempted": 2, "sent": 2, "click": 4},
                                            "delivery_funnel": {"sent": 2},
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            ]
            for campaign_id in campaign_ids
        }
    }
    if current_page is not None:
        body["current_page"] = current_page
    if total_pages is not None:
        body["total_pages"] = total_pages
    return _response(body)


def _make_manager(resume: MoEngageResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _drive(
    endpoint: str,
    responses: list[Response],
    *,
    manager: mock.MagicMock | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    configured_start_date: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]], mock.MagicMock]:
    """Drive ``moengage_source`` with a mocked HTTP session.

    Returns ``(sent_bodies, sent_headers, rows, manager)``. Bodies and headers are copied at
    send time because the paginators mutate the Request in place between pages.
    """
    manager = manager if manager is not None else _make_manager()
    sent_bodies: list[dict[str, Any]] = []
    sent_headers: list[dict[str, str]] = []
    response_iter = iter(responses)

    def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
        sent_bodies.append(dict(request.json or {}))
        sent_headers.append(dict(request.headers or {}))
        return next(response_iter)

    with mock.patch(CLIENT_SESSION_PATCH) as MockClientSession, mock.patch(MOENGAGE_SESSION_PATCH) as MockMoeSession:
        for factory in (MockClientSession, MockMoeSession):
            session = factory.return_value
            session.headers = {}
            session.prepare_request.side_effect = lambda req: req
            session.send.side_effect = fake_send

        source_response = moengage_source(
            data_center="01",
            workspace_id="ws-1",
            api_key="test-key",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            configured_start_date=configured_start_date,
        )
        rows = [row for page in cast(Iterable[Any], source_response.items()) for row in page]
    return sent_bodies, sent_headers, rows, manager


class TestMoEngageBaseUrl:
    @pytest.mark.parametrize("data_center", MOENGAGE_DATA_CENTERS)
    def test_builds_moengage_host_for_every_data_center(self, data_center: str) -> None:
        assert moengage_base_url(data_center) == f"https://api-{data_center}.moengage.com"

    @pytest.mark.parametrize("data_center", ["01.evil.com", "evil.com/", "07", ""])
    def test_rejects_values_outside_the_allowlist(self, data_center: str) -> None:
        # The value is interpolated into the hostname, so an unknown value must never build a URL.
        with pytest.raises(ValueError):
            moengage_base_url(data_center)


class TestMoEngageSearchPaginator:
    @pytest.mark.parametrize(
        ("rows_on_page", "expects_next"),
        [
            (SEARCH_PAGE_SIZE, True),
            (SEARCH_PAGE_SIZE - 1, False),
            (0, False),
        ],
    )
    def test_full_page_advances_and_short_page_stops(self, rows_on_page: int, expects_next: bool) -> None:
        paginator = MoEngageSearchPaginator()
        paginator.update_state(_campaigns_page(rows_on_page), data=[{}] * rows_on_page)

        assert paginator.has_next_page is expects_next
        assert paginator.get_resume_state() == ({"page": 2} if expects_next else None)

    def test_each_request_gets_a_fresh_idempotency_key(self) -> None:
        # MoEngage replays the response recorded for a reused Idempotency-Key, so a reused key
        # would return page 1's body for every page.
        paginator = MoEngageSearchPaginator()
        request = Request(method="POST", url="https://api-01.moengage.com/v5/campaigns/search", json={})
        paginator.init_request(request)
        first_key = request.headers["Idempotency-Key"]
        paginator.update_state(_campaigns_page(SEARCH_PAGE_SIZE), data=[{}] * SEARCH_PAGE_SIZE)
        paginator.update_request(request)

        assert request.headers["Idempotency-Key"] != first_key
        assert request.json["page"] == 2

    def test_set_resume_state_targets_the_saved_page(self) -> None:
        paginator = MoEngageSearchPaginator()
        paginator.set_resume_state({"page": 5})
        request = Request(method="POST", url="https://api-01.moengage.com/v5/campaigns/search", json={})
        paginator.init_request(request)

        assert request.json["page"] == 5


class TestMoEngageStatsPaginator:
    @pytest.mark.parametrize(
        ("campaign_count", "current_page", "total_pages", "expects_next"),
        [
            (STATS_PAGE_SIZE, 1, 3, True),
            (STATS_PAGE_SIZE, 3, 3, False),
            (0, 1, 1, False),
            # Counters missing from the response: a full page keeps walking, a short page stops,
            # so the walk can never loop on one offset.
            (STATS_PAGE_SIZE, None, None, True),
            (STATS_PAGE_SIZE - 1, None, None, False),
        ],
    )
    def test_termination_follows_page_counters_then_page_size(
        self, campaign_count: int, current_page: int | None, total_pages: int | None, expects_next: bool
    ) -> None:
        paginator = MoEngageStatsPaginator()
        response = _stats_page(
            [f"c{i}" for i in range(campaign_count)], current_page=current_page, total_pages=total_pages
        )
        paginator.update_state(response)

        assert paginator.has_next_page is expects_next

    def test_next_page_advances_offset_in_the_body(self) -> None:
        paginator = MoEngageStatsPaginator()
        paginator.update_state(_stats_page([f"c{i}" for i in range(STATS_PAGE_SIZE)], current_page=1, total_pages=2))
        request = Request(method="POST", url="https://api-01.moengage.com/core-services/v1/campaign-stats", json={})
        paginator.update_request(request)

        assert request.json["offset"] == STATS_PAGE_SIZE
        assert request.json["limit"] == STATS_PAGE_SIZE

    def test_non_json_body_stops(self) -> None:
        paginator = MoEngageStatsPaginator()
        resp = Response()
        resp.status_code = 200
        resp._content = b"<html>gateway</html>"
        paginator.update_state(resp)

        assert paginator.has_next_page is False


class TestExplodeStats:
    DATA = {
        "66e933029ff25f3322d8279d": [
            {
                "platforms": {
                    "android": {
                        "locales": {
                            "all_locales": {
                                "variations": {
                                    "all_variations": {
                                        "performance_stats": {"attempted": 2, "sent": 2, "click": 4, "ctr": 200},
                                        "conversion_goal_stats": {"Goal 1": {"conversions": 0}},
                                        "delivery_funnel": {"sent": 2, "impressions": 2},
                                        "failure_breakdown": {},
                                    },
                                    "campaign_control_group": {
                                        "delivery_funnel": {"reachable_users_in_segment": 0},
                                        "failure_breakdown": {"user_removed_due_to_campaing_control_group": 1},
                                    },
                                }
                            }
                        }
                    }
                }
            }
        ]
    }

    def test_explodes_one_row_per_campaign_platform_locale_variation(self) -> None:
        rows = _explode_stats({"date": "2025-01-05"}, self.DATA)

        assert [(r["campaign_id"], r["platform"], r["locale"], r["variation"]) for r in rows] == [
            ("66e933029ff25f3322d8279d", "android", "all_locales", "all_variations"),
            ("66e933029ff25f3322d8279d", "android", "all_locales", "campaign_control_group"),
        ]
        main = rows[0]
        # Flat metrics become columns; groups with dynamic keys stay nested.
        assert main["attempted"] == 2
        assert main["ctr"] == 200
        assert main["date"] == "2025-01-05"
        assert main["conversion_goal_stats"] == {"Goal 1": {"conversions": 0}}
        assert main["delivery_funnel"] == {"sent": 2, "impressions": 2}
        # A variation with no performance_stats block still lands as a row.
        assert rows[1]["failure_breakdown"] == {"user_removed_due_to_campaing_control_group": 1}

    def test_id_is_stable_when_metrics_restate(self) -> None:
        # Merge updates a restated row in place only if the id hashes identity dimensions, never
        # the metric values.
        restated = json.loads(json.dumps(self.DATA))
        variations = restated["66e933029ff25f3322d8279d"][0]["platforms"]["android"]["locales"]["all_locales"][
            "variations"
        ]
        variations["all_variations"]["performance_stats"]["click"] = 99

        original_ids = [r["id"] for r in _explode_stats({"date": "2025-01-05"}, self.DATA)]
        restated_ids = [r["id"] for r in _explode_stats({"date": "2025-01-05"}, restated)]
        next_day_ids = [r["id"] for r in _explode_stats({"date": "2025-01-06"}, self.DATA)]

        assert original_ids == restated_ids
        assert set(original_ids).isdisjoint(next_day_ids)

    def test_empty_data_yields_no_rows(self) -> None:
        assert _explode_stats({"date": "2025-01-05"}, {}) == []


class TestReportDays:
    TODAY = date(2025, 6, 15)

    @pytest.mark.parametrize(
        ("watermark", "configured_start", "resume_from", "expected_first", "expected_len"),
        [
            # Incremental run continues from the watermark.
            (date(2025, 6, 13), None, None, date(2025, 6, 13), 3),
            # Full refresh starts at the configured start date.
            (None, date(2025, 6, 10), None, date(2025, 6, 10), 6),
            # Full refresh without a start date backfills the default window.
            (None, None, None, date(2025, 6, 15) - timedelta(days=DEFAULT_BACKFILL_DAYS - 1), DEFAULT_BACKFILL_DAYS),
            # A watermark at or past today still re-pulls today rather than requesting the future.
            (date(2025, 6, 16), None, None, date(2025, 6, 15), 1),
            # A resume checkpoint skips the days already yielded.
            (date(2025, 6, 10), None, date(2025, 6, 14), date(2025, 6, 14), 2),
        ],
    )
    def test_resolves_the_requested_days(
        self,
        watermark: date | None,
        configured_start: date | None,
        resume_from: date | None,
        expected_first: date,
        expected_len: int,
    ) -> None:
        days = _report_days(watermark, self.TODAY, configured_start, resume_from)

        assert days[0] == expected_first
        assert days[-1] == self.TODAY
        assert len(days) == expected_len


class TestMoEngageSourceCampaigns:
    def test_fresh_run_pages_until_a_short_page_and_checkpoints(self) -> None:
        responses = [_campaigns_page(SEARCH_PAGE_SIZE), _campaigns_page(SEARCH_PAGE_SIZE), _campaigns_page(1)]
        sent_bodies, sent_headers, rows, manager = _drive("campaigns", responses)

        assert [body["page"] for body in sent_bodies] == [1, 2, 3]
        assert all(body["limit"] == SEARCH_PAGE_SIZE for body in sent_bodies)
        assert all(body["include_child_campaigns"] is True for body in sent_bodies)
        keys = [headers["Idempotency-Key"] for headers in sent_headers]
        assert len(set(keys)) == len(keys)
        assert len(rows) == SEARCH_PAGE_SIZE * 2 + 1

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MoEngageResumeConfig(search_state={"page": 2}),
            MoEngageResumeConfig(search_state={"page": 3}),
        ]

    def test_resume_seeds_the_saved_page(self) -> None:
        manager = _make_manager(MoEngageResumeConfig(search_state={"page": 4}))
        sent_bodies, _, _, _ = _drive("campaigns", [_campaigns_page(0)], manager=manager)

        assert [body["page"] for body in sent_bodies] == [4]


class TestMoEngageSourceDailyReport:
    def test_incremental_run_requests_one_window_per_day_from_the_watermark(self) -> None:
        today = datetime.now(UTC).date()
        watermark = today - timedelta(days=2)
        responses = [_stats_page(["c1"]) for _ in range(3)]
        sent_bodies, _, rows, manager = _drive(
            "daily_campaign_report",
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        expected_days = [(watermark + timedelta(days=i)).isoformat() for i in range(3)]
        assert [body["start_date"] for body in sent_bodies] == expected_days
        assert [body["end_date"] for body in sent_bodies] == expected_days
        assert all(body["attribution_type"] == ATTRIBUTION_TYPE for body in sent_bodies)
        assert all(body["metric_type"] == METRIC_TYPE for body in sent_bodies)

        # Each row is stamped with the day its request asked for, since the response carries none.
        assert [row["date"] for row in rows] == expected_days
        assert rows[0]["campaign_id"] == "c1"

        # The checkpoint names the first day not yet yielded, once per completed day.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            MoEngageResumeConfig(report_day_state={"start": expected_days[1]}),
            MoEngageResumeConfig(report_day_state={"start": expected_days[2]}),
        ]

    def test_resume_skips_days_already_yielded(self) -> None:
        today = datetime.now(UTC).date()
        manager = _make_manager(MoEngageResumeConfig(report_day_state={"start": today.isoformat()}))
        sent_bodies, _, _, _ = _drive(
            "daily_campaign_report",
            [_stats_page(["c1"])],
            manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=today - timedelta(days=5),
        )

        assert [body["start_date"] for body in sent_bodies] == [today.isoformat()]

    def test_full_refresh_starts_at_the_configured_date(self) -> None:
        today = datetime.now(UTC).date()
        start = today - timedelta(days=1)
        sent_bodies, _, _, _ = _drive(
            "daily_campaign_report",
            [_stats_page(["c1"]), _stats_page(["c1"])],
            configured_start_date=start.isoformat(),
        )

        assert [body["start_date"] for body in sent_bodies] == [start.isoformat(), today.isoformat()]


class TestMoEngageSourceCampaignReport:
    def test_requests_the_trailing_window_and_pages_by_offset(self) -> None:
        today = datetime.now(UTC).date()
        responses = [
            _stats_page([f"c{i}" for i in range(STATS_PAGE_SIZE)], current_page=1, total_pages=2),
            _stats_page(["c10"], current_page=2, total_pages=2),
        ]
        sent_bodies, _, rows, manager = _drive("campaign_report", responses)

        window_start = (today - timedelta(days=REPORT_WINDOW_DAYS - 1)).isoformat()
        assert all(body["start_date"] == window_start for body in sent_bodies)
        assert all(body["end_date"] == today.isoformat() for body in sent_bodies)
        assert [body["offset"] for body in sent_bodies] == [0, STATS_PAGE_SIZE]
        assert len(rows) == STATS_PAGE_SIZE + 1
        assert rows[0]["start_date"] == window_start
        assert rows[0]["end_date"] == today.isoformat()

        # The window is anchored to today, so a checkpointed offset from a previous attempt would
        # point into a different result set; this endpoint restarts instead of resuming.
        manager.save_state.assert_not_called()


class TestMoEngageSourceErrors:
    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown MoEngage endpoint"):
            moengage_source(
                data_center="01",
                workspace_id="ws-1",
                api_key="k",
                endpoint="not_a_table",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
            )

    @pytest.mark.parametrize(
        "error_message",
        [
            "401 Client Error: Unauthorized for url: https://api-01.moengage.com/v5/campaigns/search",
            "403 Client Error: Forbidden for url: https://api-03.moengage.com/core-services/v1/campaign-stats",
        ],
    )
    def test_auth_failures_match_a_non_retryable_pattern(self, error_message: str) -> None:
        # A sync hitting revoked credentials must fail permanently with the curated message rather
        # than retry forever.
        assert error_message_matches(error_message, MoEngageSource().get_non_retryable_errors())


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "is_valid", "message_fragment"),
        [
            (200, True, None),
            (401, False, "authentication failed"),
            (403, False, "authentication failed"),
            (500, False, "unexpected response"),
        ],
    )
    def test_maps_probe_status_to_user_message(self, status: int, is_valid: bool, message_fragment: str | None) -> None:
        with mock.patch(MOENGAGE_SESSION_PATCH) as MockSession:
            MockSession.return_value.post.return_value = _response({}, status=status)
            ok, message = validate_credentials("01", "ws-1", "key")

        assert ok is is_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message.lower()

    def test_connection_failure_reports_the_data_center(self) -> None:
        with mock.patch(MOENGAGE_SESSION_PATCH) as MockSession:
            MockSession.return_value.post.side_effect = ConnectionError("boom")
            ok, message = validate_credentials("01", "ws-1", "key")

        assert ok is False
        assert message is not None and "data center" in message
