from collections.abc import Collection, Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo import (
    CRITEO_NO_ADVERTISERS_ERROR,
    PAGE_SIZE,
    REPORT_MAX_HISTORY_DAYS,
    REPORT_WINDOW_DAYS,
    CriteoClient,
    CriteoReportShapeError,
    CriteoResumeConfig,
    _flatten_resource,
    _make_auth,
    _report_payload_rows,
    _resources,
    _retry_policy,
    _total_items,
    criteo_source,
    get_rows,
    report_start_day,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.criteo.settings import (
    CRITEO_API_VERSION,
    CRITEO_ENDPOINTS,
    CRITEO_TOKEN_URL,
    ENDPOINTS,
    REPORT_DIMENSIONS,
    REPORT_METRICS,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.criteo.criteo"


class FakeResumeManager(ResumableSourceManager[CriteoResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: Optional[CriteoResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[CriteoResumeConfig] = []
        self.clear_calls = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[CriteoResumeConfig]:
        return self.state

    def save_state(self, data: CriteoResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.clear_calls += 1


def _response(payload: Any) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _error_response(status: int) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    inner = mock.MagicMock()
    inner.status_code = status
    response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error", response=inner)
    return response


def _envelope(*ids: str, total: Optional[int] = None, **attributes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "data": [{"id": id_, "type": "Resource", "attributes": {"name": f"name-{id_}", **attributes}} for id_ in ids],
        "errors": [],
        "warnings": [],
    }
    if total is not None:
        payload["meta"] = {"limit": PAGE_SIZE, "offset": 0, "totalItems": total}
    return payload


def _page(count: int, *, prefix: str = "row", total: Optional[int] = None) -> dict[str, Any]:
    return _envelope(*[f"{prefix}-{index}" for index in range(count)], total=total)


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    return [row for page in cast("Iterable[Any]", source_response.items()) for row in page]


def _collect(
    endpoint: str,
    manager: FakeResumeManager,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    pages = get_rows(
        client_id="cid",
        client_secret="sec",
        endpoint=endpoint,
        api_version=CRITEO_API_VERSION,
        resumable_source_manager=manager,
        **kwargs,
    )
    return [row for page in pages for row in page]


class TestEnvelopeParsing:
    @pytest.mark.parametrize(
        "payload, expected_count",
        [
            ({"data": [{"id": "1"}, {"id": "2"}]}, 2),
            ({"data": []}, 0),
            ({"data": None}, 0),
            ({"data": [{"id": "1"}, "not-a-resource"]}, 1),
            ({}, 0),
            ([], 0),
            (None, 0),
        ],
    )
    def test_resources_tolerates_odd_bodies(self, payload: Any, expected_count: int) -> None:
        assert len(_resources(payload)) == expected_count

    @pytest.mark.parametrize(
        "payload, expected",
        [
            ({"meta": {"totalItems": 7}}, 7),
            ({"meta": {"totalItems": True}}, None),
            ({"meta": {}}, None),
            ({"meta": "nope"}, None),
            ({}, None),
            ("nope", None),
        ],
    )
    def test_total_items(self, payload: Any, expected: Optional[int]) -> None:
        assert _total_items(payload) == expected


class TestFlattenResource:
    def test_attributes_become_the_row(self) -> None:
        row = _flatten_resource(
            {"id": "1", "type": "Campaign", "attributes": {"name": "Retargeting", "goal": "acquisition"}}
        )

        assert row == {"id": "1", "type": "Campaign", "name": "Retargeting", "goal": "acquisition"}

    def test_envelope_id_wins_over_an_echoed_attribute_id(self) -> None:
        # Some entities echo `id` inside attributes; the envelope id is the one the primary key uses.
        row = _flatten_resource({"id": "outer", "type": "AdSet", "attributes": {"id": "inner"}})

        assert row["id"] == "outer"

    def test_extra_fields_are_merged(self) -> None:
        row = _flatten_resource({"id": "1", "attributes": {}}, {"_advertiser_id": "adv-1"})

        assert row["_advertiser_id"] == "adv-1"

    @pytest.mark.parametrize("attributes", [None, "not-a-dict", []])
    def test_missing_attributes_still_yields_an_identifiable_row(self, attributes: Any) -> None:
        row = _flatten_resource({"id": "1", "type": "Ad", "attributes": attributes})

        assert row == {"id": "1", "type": "Ad"}


class TestTransportPolicy:
    def test_read_only_posts_are_retried(self) -> None:
        # Criteo's searches and the report are POSTs; the shared default only retries idempotent
        # verbs, which would leave every Criteo call unretried on a 429.
        policy = _retry_policy()

        assert "POST" in cast(Collection[str], policy.allowed_methods)
        assert 429 in cast(Collection[int], policy.status_forcelist)

    def test_auth_is_client_credentials_in_the_body(self) -> None:
        auth = _make_auth("cid", "sec")

        assert auth.token_url == CRITEO_TOKEN_URL
        assert auth.grant_type == "client_credentials"
        assert auth.client_auth_method == "body"
        # The secret must be redactable wherever it surfaces in logs or samples.
        assert "sec" in auth.secret_values()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_urls_carry_the_pinned_api_version(self, make_session: mock.MagicMock) -> None:
        client = CriteoClient("cid", "sec", "2026-01")

        assert client.url("/advertisers/me") == "https://api.criteo.com/2026-01/advertisers/me"
        assert make_session.call_args.kwargs["redact_values"] == ("sec",)


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestPortfolioAndSearch:
    def test_portfolio_rows_are_flattened(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.return_value = _response(_envelope("13", "14", advertiserName="Acme"))

        rows = _collect("advertisers", FakeResumeManager())

        assert [row["id"] for row in rows] == ["13", "14"]
        assert rows[0]["advertiserName"] == "Acme"
        assert session.get.call_args.args[0].endswith("/advertisers/me")

    @pytest.mark.parametrize(
        "endpoint, expected_path",
        [
            ("campaigns", "/marketing-solutions/campaigns/search"),
            ("ad_sets", "/marketing-solutions/ad-sets/search"),
        ],
    )
    def test_search_endpoints_post_an_unfiltered_body(
        self, make_session: mock.MagicMock, endpoint: str, expected_path: str
    ) -> None:
        session = make_session.return_value
        session.post.return_value = _response(_envelope("1", "2"))

        rows = _collect(endpoint, FakeResumeManager())

        assert [row["id"] for row in rows] == ["1", "2"]
        assert session.post.call_args.args[0].endswith(expected_path)
        # Empty filters means "everything in the portfolio"; the search is not paginated.
        assert session.post.call_args.kwargs["json"] == {"filters": {}}
        assert session.post.call_count == 1

    def test_empty_search_yields_no_pages(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.post.return_value = _response(_envelope())

        assert _collect("campaigns", FakeResumeManager()) == []

    def test_state_is_cleared_once_the_stream_completes(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.post.return_value = _response(_envelope("1"))
        manager = FakeResumeManager()

        _collect("campaigns", manager)

        assert manager.clear_calls == 1


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestOffsetPagination:
    def test_audiences_walks_offsets_until_a_short_page(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.post.side_effect = [_response(_page(PAGE_SIZE)), _response(_page(3, prefix="last"))]
        manager = FakeResumeManager()

        rows = _collect("audiences", manager)

        assert len(rows) == PAGE_SIZE + 3
        assert [call.kwargs["params"]["offset"] for call in session.post.call_args_list] == [0, PAGE_SIZE]
        # Checkpointed after the first full page was yielded, and not again on the terminal page.
        assert [state.offset for state in manager.saved] == [PAGE_SIZE]

    def test_audiences_sends_the_search_body_alongside_the_page_params(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.post.return_value = _response(_page(1))

        _collect("audiences", FakeResumeManager())

        assert session.post.call_args.kwargs["json"] == {"data": {"attributes": {}}}
        assert session.post.call_args.kwargs["params"] == {"limit": PAGE_SIZE, "offset": 0}

    def test_pagination_stops_at_the_reported_total(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        # A full page whose `meta.totalItems` says the collection is exhausted must not be followed.
        session.post.return_value = _response(_page(PAGE_SIZE, total=PAGE_SIZE))

        rows = _collect("audiences", FakeResumeManager())

        assert len(rows) == PAGE_SIZE
        assert session.post.call_count == 1

    def test_audiences_resumes_from_the_saved_offset(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.post.return_value = _response(_page(2))

        _collect("audiences", FakeResumeManager(CriteoResumeConfig(offset=200)))

        assert session.post.call_args.kwargs["params"]["offset"] == 200


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestAdsFanOut:
    def test_rows_carry_the_advertiser_they_were_fetched_for(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        portfolio = _response(_envelope("adv-1", "adv-2"))
        session.get.side_effect = [portfolio, _response(_envelope("ad-1")), _response(_envelope("ad-2"))]

        rows = _collect("ads", FakeResumeManager())

        assert [(row["_advertiser_id"], row["id"]) for row in rows] == [("adv-1", "ad-1"), ("adv-2", "ad-2")]
        # The parent advertiser is part of the primary key, so it has to be on every row.
        assert CRITEO_ENDPOINTS["ads"].primary_key == ["_advertiser_id", "id"]

    def test_checkpoint_points_at_the_next_advertiser(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.side_effect = [
            _response(_envelope("adv-1", "adv-2", "adv-3")),
            _response(_envelope("ad-1")),
            _response(_envelope("ad-2")),
            _response(_envelope("ad-3")),
        ]
        manager = FakeResumeManager()

        _collect("ads", manager)

        # A retry must not re-walk the advertiser that just finished, and the final advertiser saves
        # nothing because the run completed.
        assert [state.advertiser_id for state in manager.saved] == ["adv-2", "adv-3"]

    def test_resume_skips_already_synced_advertisers(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.side_effect = [
            _response(_envelope("adv-1", "adv-2", "adv-3")),
            _response(_envelope("ad-2")),
            _response(_envelope("ad-3")),
        ]

        rows = _collect("ads", FakeResumeManager(CriteoResumeConfig(advertiser_id="adv-2")))

        assert [row["_advertiser_id"] for row in rows] == ["adv-2", "adv-3"]

    def test_resume_applies_the_saved_offset_only_to_the_resumed_advertiser(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.side_effect = [
            _response(_envelope("adv-1", "adv-2")),
            _response(_page(PAGE_SIZE, prefix="adv1")),
            _response(_page(1, prefix="adv1-last")),
            _response(_page(1, prefix="adv2")),
        ]

        _collect("ads", FakeResumeManager(CriteoResumeConfig(advertiser_id="adv-1", offset=PAGE_SIZE)))

        offsets = [call.kwargs["params"]["offset"] for call in session.get.call_args_list[1:]]
        # adv-1 picks up mid-collection; adv-2 starts from the beginning.
        assert offsets == [PAGE_SIZE, PAGE_SIZE * 2, 0]

    def test_unknown_saved_advertiser_restarts_the_fan_out(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.side_effect = [
            _response(_envelope("adv-1", "adv-2")),
            _response(_envelope("ad-1")),
            _response(_envelope("ad-2")),
        ]

        rows = _collect("ads", FakeResumeManager(CriteoResumeConfig(advertiser_id="adv-gone", offset=500)))

        # Restarting is the safe choice: honoring a stale offset would skip rows silently.
        assert [row["_advertiser_id"] for row in rows] == ["adv-1", "adv-2"]
        assert session.get.call_args_list[1].kwargs["params"]["offset"] == 0

    def test_empty_portfolio_fails_with_the_consent_message(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.return_value = _response(_envelope())

        with pytest.raises(ValueError, match="advertiser admin"):
            _collect("ads", FakeResumeManager())


class TestReportStartDay:
    TODAY = date(2026, 7, 26)
    RETENTION_FLOOR = TODAY - timedelta(days=REPORT_MAX_HISTORY_DAYS)

    @pytest.mark.parametrize(
        "watermark, expected",
        [
            # No watermark: pull Criteo's full two-year retention.
            (None, RETENTION_FLOOR),
            (date(2026, 7, 1), date(2026, 7, 1)),
            (datetime(2026, 7, 1, 12, tzinfo=UTC), date(2026, 7, 1)),
            ("2026-07-01", date(2026, 7, 1)),
            # A future watermark can't produce a backwards range.
            (date(2027, 1, 1), TODAY),
            # Older than retention clamps to the floor.
            (date(2015, 1, 1), RETENTION_FLOOR),
            # Unparseable values fall back to a full pull rather than syncing nothing.
            ("not-a-date", RETENTION_FLOOR),
        ],
    )
    def test_start_day(self, watermark: Any, expected: date) -> None:
        assert report_start_day(watermark, self.TODAY) == expected

    def test_retention_floor_matches_the_documented_two_years(self) -> None:
        assert (self.TODAY - report_start_day(None, self.TODAY)).days == REPORT_MAX_HISTORY_DAYS


class TestReportPayloadRows:
    @pytest.mark.parametrize(
        "payload, expected_count",
        [
            ([{"Day": "2026-07-01"}, {"Day": "2026-07-02"}], 2),
            ([], 0),
            ([{"Day": "2026-07-01"}, "junk"], 1),
            ({"Rows": [{"Day": "2026-07-01"}]}, 1),
            ({"rows": [{"Day": "2026-07-01"}]}, 1),
            ({"data": [{"Day": "2026-07-01"}]}, 1),
        ],
    )
    def test_accepted_shapes(self, payload: Any, expected_count: int) -> None:
        assert len(_report_payload_rows(payload)) == expected_count

    @pytest.mark.parametrize("payload", [None, "text", 42, {"unexpected": 1}])
    def test_unreadable_shape_fails_loud(self, payload: Any) -> None:
        # Silently syncing zero rows would look like "no data" instead of a broken response.
        with pytest.raises(CriteoReportShapeError):
            _report_payload_rows(payload)


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestStatisticsReport:
    TODAY = date(2026, 7, 26)

    def _wire(self, session: mock.MagicMock, windows: int) -> None:
        session.get.return_value = _response(_envelope("adv-1", "adv-2"))
        session.post.side_effect = [_response([{"Day": f"window-{index}"}]) for index in range(windows)]

    def test_the_window_runs_from_the_watermark_to_today(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        self._wire(session, windows=1)

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            rows = _collect(
                "campaign_stats",
                FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 7, 20),
            )

        body = session.post.call_args.kwargs["json"]
        # Seven days fit in one window, and the range never runs past today.
        assert (body["startDate"], body["endDate"]) == ("2026-07-20T00:00:00Z", "2026-07-26T00:00:00Z")
        assert session.post.call_count == 1
        assert [row["Day"] for row in rows] == ["window-0"]

    def test_a_range_longer_than_one_window_is_split(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        self._wire(session, windows=3)

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            _collect(
                "campaign_stats",
                FakeResumeManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 7, 8),
            )

        ranges = [
            (call.kwargs["json"]["startDate"][:10], call.kwargs["json"]["endDate"][:10])
            for call in session.post.call_args_list
        ]
        # 19 days over a 7-day window: three calls, none overlapping, none past today.
        assert ranges == [
            ("2026-07-08", "2026-07-14"),
            ("2026-07-15", "2026-07-21"),
            ("2026-07-22", "2026-07-26"),
        ]
        assert REPORT_WINDOW_DAYS == 7

    def test_window_body_carries_every_advertiser_dimension_and_metric(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        self._wire(session, windows=1)

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            _collect(
                "campaign_stats",
                FakeResumeManager(),
                report_currency="EUR",
                report_timezone="Europe/Paris",
                should_use_incremental_field=True,
                db_incremental_field_last_value=self.TODAY,
            )

        body = session.post.call_args.kwargs["json"]
        assert body["advertiserIds"] == "adv-1,adv-2"
        assert body["dimensions"] == list(REPORT_DIMENSIONS)
        assert body["metrics"] == list(REPORT_METRICS)
        assert body["currency"] == "EUR"
        assert body["timezone"] == "Europe/Paris"
        assert body["format"] == "json"

    def test_blank_currency_and_timezone_fall_back_to_defaults(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        self._wire(session, windows=1)

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            _collect(
                "campaign_stats",
                FakeResumeManager(),
                report_currency=None,
                report_timezone="",
                should_use_incremental_field=True,
                db_incremental_field_last_value=self.TODAY,
            )

        body = session.post.call_args.kwargs["json"]
        assert body["currency"] == "USD"
        assert body["timezone"] == "UTC"

    def test_each_completed_window_is_checkpointed(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        self._wire(session, windows=2)
        manager = FakeResumeManager()

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            _collect(
                "campaign_stats",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 7, 15),
            )

        # Saved after the window's rows were yielded, and not after the final window.
        assert [state.next_start_date for state in manager.saved] == ["2026-07-22"]
        assert manager.clear_calls == 1

    def test_resume_picks_up_at_the_saved_window(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        self._wire(session, windows=1)

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            _collect(
                "campaign_stats",
                FakeResumeManager(CriteoResumeConfig(next_start_date="2026-07-22")),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 7, 1),
            )

        # The saved window wins over the watermark, so resumed work isn't redone.
        assert session.post.call_args.kwargs["json"]["startDate"] == "2026-07-22T00:00:00Z"
        assert session.post.call_count == 1

    def test_full_refresh_pulls_the_whole_retention_window(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.return_value = _response(_envelope("adv-1"))
        session.post.return_value = _response([])

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY):
            _collect("campaign_stats", FakeResumeManager(), should_use_incremental_field=False)

        floor = self.TODAY - timedelta(days=REPORT_MAX_HISTORY_DAYS)
        assert session.post.call_args_list[0].kwargs["json"]["startDate"] == f"{floor.isoformat()}T00:00:00Z"

    def test_empty_portfolio_fails_with_the_consent_message(self, make_session: mock.MagicMock) -> None:
        session = make_session.return_value
        session.get.return_value = _response(_envelope())

        with mock.patch(f"{_MODULE}._today", return_value=self.TODAY), pytest.raises(ValueError) as error:
            _collect("campaign_stats", FakeResumeManager())

        assert str(error.value) == CRITEO_NO_ADVERTISERS_ERROR


@mock.patch(f"{_MODULE}.make_tracked_session")
class TestValidateCredentials:
    def test_valid_when_the_portfolio_lists_advertisers(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.get.return_value = _response(_envelope("13"))

        assert validate_credentials("cid", "sec", CRITEO_API_VERSION) == (True, None)

    def test_token_rejection_reports_bad_credentials(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.get.side_effect = OAuth2AuthRequestError("invalid_client", is_permanent=True)

        valid, message = validate_credentials("cid", "sec", CRITEO_API_VERSION)

        assert valid is False
        assert message is not None and "client ID" in message

    @pytest.mark.parametrize(
        "status, expected_fragment",
        [
            (401, "client ID"),
            # A valid token with no grant is the consent step, not a bad secret.
            (403, "advertiser admin"),
            (500, "Could not reach"),
        ],
    )
    def test_http_status_is_mapped_to_an_actionable_message(
        self, make_session: mock.MagicMock, status: int, expected_fragment: str
    ) -> None:
        make_session.return_value.get.return_value = _error_response(status)

        valid, message = validate_credentials("cid", "sec", CRITEO_API_VERSION)

        assert valid is False
        assert message is not None and expected_fragment in message

    def test_transport_failure_never_raises(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.get.side_effect = requests.ConnectionError("boom")

        assert validate_credentials("cid", "sec", CRITEO_API_VERSION)[0] is False

    def test_authenticated_but_ungranted_app_is_rejected(self, make_session: mock.MagicMock) -> None:
        # The token mints and /advertisers/me answers, but the app was never granted an advertiser.
        make_session.return_value.get.return_value = _response(_envelope())

        assert validate_credentials("cid", "sec", CRITEO_API_VERSION) == (False, CRITEO_NO_ADVERTISERS_ERROR)


class TestCriteoSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_shape_per_endpoint(self, endpoint: str) -> None:
        config = CRITEO_ENDPOINTS[endpoint]
        response = criteo_source(
            client_id="cid",
            client_secret="sec",
            endpoint=endpoint,
            api_version=CRITEO_API_VERSION,
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
            assert response.partition_format == "month"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_flow_through_the_source_response(self, make_session: mock.MagicMock) -> None:
        make_session.return_value.post.return_value = _response(_envelope("1", "2"))

        response = criteo_source(
            client_id="cid",
            client_secret="sec",
            endpoint="campaigns",
            api_version=CRITEO_API_VERSION,
            resumable_source_manager=FakeResumeManager(),
        )

        assert [row["id"] for row in _rows(response)] == ["1", "2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_building_the_response_issues_no_request(self, make_session: mock.MagicMock) -> None:
        # The response is built on the API request thread; only `items()` may touch the network.
        criteo_source(
            client_id="cid",
            client_secret="sec",
            endpoint="advertisers",
            api_version=CRITEO_API_VERSION,
            resumable_source_manager=FakeResumeManager(),
        )

        make_session.return_value.get.assert_not_called()
        make_session.return_value.post.assert_not_called()
