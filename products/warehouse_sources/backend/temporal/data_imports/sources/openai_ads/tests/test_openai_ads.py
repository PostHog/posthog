import json
from datetime import UTC, datetime
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openaiads import (
    OpenAIAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.openai_ads import (
    OpenAIAdsResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.openai_ads.source import OpenAIAdsSource


def _driver() -> SourceDriver:
    return SourceDriver(OpenAIAdsSource(), OpenAIAdsSourceConfig(api_key="oa-ads-test"))


def _page(items: list[dict[str, Any]], *, has_more: bool, last_id: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"object": "list", "data": items, "has_more": has_more}
    if last_id is not None:
        body["last_id"] = last_id
    return ScriptedResponse(json=body)


class TestFanOut:
    def test_ads_walk_both_levels_and_carry_full_lineage(self) -> None:
        result = _driver().run(
            "ads",
            [
                _page([{"id": "cmpn_1"}], has_more=False, last_id="cmpn_1"),
                _page([{"id": "adgrp_1"}, {"id": "adgrp_2"}], has_more=False, last_id="adgrp_2"),
                _page([{"id": "ad_1"}], has_more=False, last_id="ad_1"),
                _page([{"id": "ad_2"}], has_more=False, last_id="ad_2"),
            ],
        )

        assert result.raised is None
        assert [(r["campaign_id"], r["ad_group_id"], r["id"]) for r in result.rows] == [
            ("cmpn_1", "adgrp_1", "ad_1"),
            ("cmpn_1", "adgrp_2", "ad_2"),
        ]
        assert result.paths == ["/v1/campaigns", "/v1/ad_groups", "/v1/ads", "/v1/ads"]
        assert result.params("ad_group_id") == [None, None, "adgrp_1", "adgrp_2"]

    def test_child_pagination_within_one_parent(self) -> None:
        # The child listing itself paginates with the same after cursor; page two must keep the
        # parent's campaign_id param.
        result = _driver().run(
            "ad_groups",
            [
                _page([{"id": "cmpn_1"}], has_more=False, last_id="cmpn_1"),
                _page([{"id": "adgrp_1"}], has_more=True, last_id="adgrp_1"),
                _page([{"id": "adgrp_2"}], has_more=False, last_id="adgrp_2"),
            ],
        )

        assert result.raised is None
        assert [(r["campaign_id"], r["id"]) for r in result.rows] == [("cmpn_1", "adgrp_1"), ("cmpn_1", "adgrp_2")]
        assert result.queries[2] == {
            "campaign_id": ("cmpn_1",),
            "limit": ("500",),
            "order": ("asc",),
            "after": ("adgrp_1",),
        }


class TestInsights:
    @parameterized.expand(
        [
            ("plan_in_middle", "start=1777075200:{plan}:end=1777161600:entity_id=cmpn_1"),
            ("plan_last", "start=1777075200:end=1777161600:entity_id=cmpn_1:{plan}"),
            ("plan_first", "{plan}:start=1777075200:end=1777161600:entity_id=cmpn_1"),
            ("no_plan", "start=1777075200:end=1777161600:entity_id=cmpn_1"),
        ]
    )
    def test_row_id_stays_the_same_across_syncs_when_plan_segment_changes(self, _name: str, id_template: str) -> None:
        ids = []
        for plan in ("plan=eJzLSM3JyVcozy/KSQEAGgQEXQ", "plan=eJwrSS0uAQAEXQHB"):
            result = _driver().run(
                "campaign_insights",
                [
                    ScriptedResponse(json={"currency_code": "EUR"}),
                    _page(
                        [{"id": id_template.format(plan=plan), "start_time": 1777075200, "end_time": 1777161600}],
                        has_more=False,
                    ),
                ],
            )
            assert result.raised is None
            ids.append(result.rows[0]["id"])

        assert ids == ["start=1777075200:end=1777161600:entity_id=cmpn_1"] * 2

    @time_machine.travel("2026-07-21", tick=False)
    def test_checkpoint_pins_the_window_alongside_the_cursor(self) -> None:
        result = _driver().run(
            "campaign_insights",
            [
                ScriptedResponse(json={"currency_code": "EUR"}),
                _page([{"id": "b1", "start_time": 1, "end_time": 2}], has_more=True, last_id="b1"),
                _page([{"id": "b2", "start_time": 2, "end_time": 3}], has_more=False, last_id="b2"),
            ],
            db_incremental_field_last_value=datetime(2026, 7, 1, tzinfo=UTC),
            should_use_incremental_field=True,
        )

        assert result.raised is None
        assert result.saved_states == [OpenAIAdsResumeConfig(cursor="b1", since="2026-07-01", until="2026-07-21")]

    @time_machine.travel("2026-07-21", tick=False)
    def test_resume_reuses_the_pinned_window_with_the_saved_cursor(self) -> None:
        # A cursor is only valid for the result set it was issued for — recomputing `until` as a
        # later day on resume would pair it with a different window.
        resume = OpenAIAdsResumeConfig(cursor="b1", since="2026-06-01", until="2026-07-19")
        result = _driver().run(
            "campaign_insights",
            [ScriptedResponse(json={"currency_code": "EUR"}), _page([], has_more=False)],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.requests[1].param("after") == "b1"
        window = json.loads(result.requests[1].param("time_ranges[]") or "null")
        assert (window["since"], window["until"]) == ("2026-06-01", "2026-07-19")

    def test_missing_account_currency_stops_sync(self) -> None:
        result = _driver().run("campaign_insights", [ScriptedResponse(json={"id": "account_example"})])

        assert isinstance(result.raised, ValueError)
        assert "account currency" in str(result.raised)
        assert result.paths == ["/v1/ad_account"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_scope", 403, True, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected: bool, message_fragment: str | None) -> None:
        # 403 is accepted at create time (a real key with restricted access); 401 means a bad key.
        # A 5xx says nothing about the key, so it must not read as a rejected credential.
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, message = validate_credentials("oa-ads-test")
        assert {request.path for request in network.requests_log} == {"/v1/campaigns"}
        assert network.requests_log[0].path == "/v1/campaigns"
        assert network.requests_log[0].param("limit") == "1"
        assert is_valid is expected
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
