import json
from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.openai_ads import (
    OpenAIAdsResumeConfig,
    openai_ads_source,
    validate_credentials,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the openai_ads module.
OPENAI_ADS_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.openai_ads.make_tracked_session"
)


def _response(body: dict[str, Any], status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.ads.openai.com/v1/campaigns"
    return resp


def _page(items: list[dict[str, Any]], *, has_more: bool, last_id: str | None = None) -> Response:
    body: dict[str, Any] = {"object": "list", "data": items, "has_more": has_more}
    if last_id is not None:
        body["last_id"] = last_id
    return _response(body)


def _make_manager(resume_state: OpenAIAdsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and capture each request's url + params AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _source(endpoint: str, manager: mock.MagicMock, last_value: Any = None):
    return openai_ads_source(
        api_key="oa-ads-test",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
        db_incremental_field_last_value=last_value,
    )


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestListPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_cursor_pagination_uses_after_and_stops_on_has_more_false(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": "cmpn_1"}], has_more=True, last_id="cmpn_1"),
                # Final page still carries a last_id — has_more must stop the walk with no extra call.
                _page([{"id": "cmpn_2"}], has_more=False, last_id="cmpn_2"),
            ],
        )

        manager = _make_manager()
        rows = _rows(_source("campaigns", manager))

        assert [r["id"] for r in rows] == ["cmpn_1", "cmpn_2"]
        assert "after" not in params[0]["params"]
        assert params[0]["params"]["limit"] == 500
        assert params[0]["params"]["order"] == "asc"
        assert params[1]["params"]["after"] == "cmpn_1"
        assert session.send.call_count == 2
        # Checkpoint saved after the first page was yielded, pointing at the next page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OpenAIAdsResumeConfig(cursor="cmpn_1")

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_falls_back_to_last_item_id_when_last_id_missing(self, MockSession) -> None:
        # If `last_id` is ever absent, the last item's id must keep pagination moving instead of
        # stopping after page one.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": "cmpn_1"}], has_more=True),
                _page([{"id": "cmpn_2"}], has_more=False),
            ],
        )

        rows = _rows(_source("campaigns", _make_manager()))

        assert [r["id"] for r in rows] == ["cmpn_1", "cmpn_2"]
        assert params[1]["params"]["after"] == "cmpn_1"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_after_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([{"id": "cmpn_6"}], has_more=False, last_id="cmpn_6")])

        _rows(_source("campaigns", _make_manager(OpenAIAdsResumeConfig(cursor="cmpn_5"))))

        assert params[0]["params"]["after"] == "cmpn_5"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_yields_no_rows(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"object": "list", "has_more": False})])

        assert _rows(_source("campaigns", _make_manager())) == []


class TestFanOut:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ad_groups_listed_per_campaign_and_stamped_with_campaign_id(self, MockSession) -> None:
        # The API requires campaign_id as a query param and the ad group objects don't carry
        # their parent id — the stamped column is what the composite primary key merges on.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": "cmpn_1"}, {"id": "cmpn_2"}], has_more=False, last_id="cmpn_2"),
                _page([{"id": "adgrp_1"}], has_more=False, last_id="adgrp_1"),
                _page([{"id": "adgrp_2"}], has_more=False, last_id="adgrp_2"),
            ],
        )

        rows = _rows(_source("ad_groups", _make_manager()))

        assert [(r["campaign_id"], r["id"]) for r in rows] == [("cmpn_1", "adgrp_1"), ("cmpn_2", "adgrp_2")]
        assert params[0]["url"].endswith("/v1/campaigns")
        assert params[1]["url"].endswith("/v1/ad_groups")
        assert params[1]["params"]["campaign_id"] == "cmpn_1"
        assert params[2]["params"]["campaign_id"] == "cmpn_2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_ads_walk_both_levels_and_carry_full_lineage(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": "cmpn_1"}], has_more=False, last_id="cmpn_1"),
                _page([{"id": "adgrp_1"}, {"id": "adgrp_2"}], has_more=False, last_id="adgrp_2"),
                _page([{"id": "ad_1"}], has_more=False, last_id="ad_1"),
                _page([{"id": "ad_2"}], has_more=False, last_id="ad_2"),
            ],
        )

        rows = _rows(_source("ads", _make_manager()))

        assert [(r["campaign_id"], r["ad_group_id"], r["id"]) for r in rows] == [
            ("cmpn_1", "adgrp_1", "ad_1"),
            ("cmpn_1", "adgrp_2", "ad_2"),
        ]
        assert params[2]["params"]["ad_group_id"] == "adgrp_1"
        assert params[3]["params"]["ad_group_id"] == "adgrp_2"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_pagination_within_one_parent(self, MockSession) -> None:
        # The child listing itself paginates with the same after cursor; page two must keep the
        # parent's campaign_id param.
        session = MockSession.return_value
        params = _wire(
            session,
            [
                _page([{"id": "cmpn_1"}], has_more=False, last_id="cmpn_1"),
                _page([{"id": "adgrp_1"}], has_more=True, last_id="adgrp_1"),
                _page([{"id": "adgrp_2"}], has_more=False, last_id="adgrp_2"),
            ],
        )

        rows = _rows(_source("ad_groups", _make_manager()))

        assert [(r["campaign_id"], r["id"]) for r in rows] == [("cmpn_1", "adgrp_1"), ("cmpn_1", "adgrp_2")]
        assert params[2]["params"] == {"campaign_id": "cmpn_1", "limit": 500, "order": "asc", "after": "adgrp_1"}


class TestInsights:
    @freeze_time("2026-07-21")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_windows_from_watermark_to_today(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_page([], has_more=False)])

        watermark = datetime(2026, 7, 1, 12, 30, tzinfo=UTC)
        _rows(_source("campaign_insights", _make_manager(), last_value=watermark))

        sent = params[0]["params"]
        assert sent["aggregation_level"] == "campaign"
        assert sent["time_granularity"] == "daily"
        assert json.loads(sent["time_ranges[]"]) == {
            "type": "date_range",
            "since": "2026-07-01",
            "until": "2026-07-21",
            "timezone": "UTC",
        }
        # The explicit projection must keep the metrics and the bucket label in the rows.
        assert "campaign.spend" in sent["fields[]"]
        assert "metadata.readable_time" in sent["fields[]"]

    @freeze_time("2026-07-21")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_windows_from_product_launch_floor(self, MockSession) -> None:
        # Without a watermark we still need a bounded window — the API rejects unbounded/future
        # ranges — and it must cover all possible history for the product.
        session = MockSession.return_value
        params = _wire(session, [_page([], has_more=False)])

        _rows(_source("ad_account_insights", _make_manager()))

        assert json.loads(params[0]["params"]["time_ranges[]"])["since"] == "2025-01-01"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bucket_times_become_datetimes(self, MockSession) -> None:
        # start_time is the DateTime incremental watermark and the partition key — epoch ints
        # would break both.
        session = MockSession.return_value
        _wire(
            session,
            [
                _page(
                    [
                        {
                            "id": "start=1777075200:end=1777161600:entity_id=cmpn_1",
                            "start_time": 1777075200,
                            "end_time": 1777161600,
                            "impressions": 5,
                        }
                    ],
                    has_more=False,
                )
            ],
        )

        rows = _rows(_source("campaign_insights", _make_manager()))

        assert rows[0]["start_time"] == datetime(2026, 4, 25, tzinfo=UTC)
        assert rows[0]["end_time"] == datetime(2026, 4, 26, tzinfo=UTC)
        assert rows[0]["impressions"] == 5

    @freeze_time("2026-07-21")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_checkpoint_pins_the_window_alongside_the_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _page([{"id": "b1", "start_time": 1, "end_time": 2}], has_more=True, last_id="b1"),
                _page([{"id": "b2", "start_time": 2, "end_time": 3}], has_more=False, last_id="b2"),
            ],
        )

        manager = _make_manager()
        _rows(_source("campaign_insights", manager, last_value=datetime(2026, 7, 1, tzinfo=UTC)))

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == OpenAIAdsResumeConfig(
            cursor="b1", since="2026-07-01", until="2026-07-21"
        )

    @freeze_time("2026-07-21")
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resume_reuses_the_pinned_window_with_the_saved_cursor(self, MockSession) -> None:
        # A cursor is only valid for the result set it was issued for — recomputing `until` as a
        # later day on resume would pair it with a different window.
        session = MockSession.return_value
        params = _wire(session, [_page([], has_more=False)])

        resume = OpenAIAdsResumeConfig(cursor="b1", since="2026-06-01", until="2026-07-19")
        _rows(_source("campaign_insights", _make_manager(resume)))

        sent = params[0]["params"]
        assert sent["after"] == "b1"
        window = json.loads(sent["time_ranges[]"])
        assert (window["since"], window["until"]) == ("2026-06-01", "2026-07-19")


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("forbidden_scope", 403, True), ("unauthorized", 401, False)])
    def test_status_mapping(self, _name: str, status: int, expected: bool) -> None:
        # 403 is accepted at create time (a real key with restricted access); 401 means a bad key.
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status)
        with mock.patch(OPENAI_ADS_SESSION_PATCH, return_value=session):
            assert validate_credentials("oa-ads-test") is expected

    def test_network_error_is_invalid(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with mock.patch(OPENAI_ADS_SESSION_PATCH, return_value=session):
            assert validate_credentials("oa-ads-test") is False
