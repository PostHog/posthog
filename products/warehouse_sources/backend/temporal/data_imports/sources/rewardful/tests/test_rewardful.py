from datetime import UTC, date, datetime
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rewardful import (
    RewardfulSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rewardful.rewardful import (
    RewardfulResumeConfig,
    format_updated_since,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rewardful.source import RewardfulSource


def _driver() -> SourceDriver:
    return SourceDriver(RewardfulSource(), RewardfulSourceConfig(api_secret="rw_secret"))


def _page(rows: list[dict[str, Any]], current_page: int, total_pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "pagination": {
                "previous_page": current_page - 1 or None,
                "current_page": current_page,
                "next_page": current_page + 1 if current_page < total_pages else None,
                "count": len(rows),
                "limit": 100,
                "total_pages": total_pages,
                "total_count": 0,
            },
            "data": rows,
        }
    )


class TestPagination:
    def test_walks_pages_until_total_pages_and_saves_the_next_page_before_each_yield(self) -> None:
        result = _driver().run(
            "affiliates",
            [
                _page([{"id": "a1"}], 1, 3),
                _page([{"id": "a2"}], 2, 3),
                _page([{"id": "a3"}], 3, 3),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("limit") == ["100", "100", "100"]
        assert result.requests[0].headers["authorization"] == "Basic cndfc2VjcmV0Og=="
        assert [row["id"] for row in result.rows] == ["a1", "a2", "a3"]
        # The third page is the last one, so no cursor is saved past it.
        assert result.saved_states == [RewardfulResumeConfig(next_page=2), RewardfulResumeConfig(next_page=3)]
        assert result.committed_states == [RewardfulResumeConfig(next_page=2), RewardfulResumeConfig(next_page=3)]

    def test_resumes_from_the_saved_page(self) -> None:
        result = _driver().run(
            "commissions",
            [_page([{"id": "c9"}], 3, 3)],
            resume_state=RewardfulResumeConfig(next_page=3),
        )

        assert result.raised is None
        assert result.params("page") == ["3"]
        assert result.params("expand[]") == ["sale"]

    def test_a_bare_array_body_on_a_paged_table_fails_loud_instead_of_syncing_zero_rows(self) -> None:
        result = _driver().run("affiliates", [ScriptedResponse(json=[{"id": "a1"}])])

        assert result.rows == []
        assert isinstance(result.raised, ValueError)
        assert "data" in str(result.raised)

    @pytest.mark.parametrize(
        "body",
        [
            [{"id": "camp_1"}, {"id": "camp_2"}],
            {"pagination": {"next_page": None}, "data": [{"id": "camp_1"}, {"id": "camp_2"}]},
        ],
    )
    def test_campaigns_read_one_page_in_either_documented_shape(self, body: Any) -> None:
        result = _driver().run("campaigns", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.paths == ["/v1/campaigns"]
        assert result.params("page") == [None]
        assert [row["id"] for row in result.rows] == ["camp_1", "camp_2"]

    def test_a_paged_campaigns_answer_fails_instead_of_syncing_a_partial_table(self) -> None:
        body = {"pagination": {"next_page": 2}, "data": [{"id": "camp_1"}]}
        result = _driver().run("campaigns", [ScriptedResponse(json=body)])

        assert result.raised is not None
        assert "more than one page of campaigns" in str(result.raised)


class TestIncrementalRequestShaping:
    @pytest.mark.parametrize(
        ("incremental_field", "last_value", "expected_updated_since"),
        [
            ("updated_at", datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC), "2026-03-04T05:06:07Z"),
            ("updated_at", None, None),
            (None, datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC), None),
        ],
    )
    def test_referrals_send_updated_since_only_with_a_watermark(
        self, incremental_field: str | None, last_value: Any, expected_updated_since: str | None
    ) -> None:
        kwargs: dict[str, Any] = {"db_incremental_field_last_value": last_value}
        if incremental_field is not None:
            kwargs["incremental_field"] = incremental_field
        result = _driver().run("referrals", [_page([{"id": "r1"}], 1, 1)], **kwargs)

        assert result.raised is None
        assert result.params("updated_since") == [expected_updated_since]
        assert result.response is not None and result.response.sort_mode == "desc"

    def test_tables_without_a_server_filter_ignore_the_watermark(self) -> None:
        result = _driver().run(
            "commissions",
            [_page([{"id": "c1"}], 1, 1)],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.params("updated_since") == [None]


class TestFormatUpdatedSince:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05Z"),
            (datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05Z"),
            (date(2026, 1, 2), "2026-01-02T00:00:00Z"),
            ("2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
        ],
    )
    def test_formats_as_utc_iso_8601(self, value: Any, expected: str) -> None:
        assert format_updated_since(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("response", "expected_valid", "expected_message_fragment"),
        [
            (ScriptedResponse(json={"pagination": {}, "data": []}), True, None),
        ],
    )
    def test_maps_the_probe_result_to_a_message(
        self, response: Any, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        with scripted_network(always(response)) as network:
            is_valid, message = validate_credentials("rw_secret")

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_message_fragment in message
        # Setup waits on the probe, so a failed request gets no retry.
        assert [request.path for request in network.requests_log] == ["/v1/affiliates"]
