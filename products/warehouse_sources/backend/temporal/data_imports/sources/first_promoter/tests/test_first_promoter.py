from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter import (
    FirstPromoterPaginator,
    FirstPromoterResumeConfig,
    _format_filter_date,
    first_promoter_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.settings import (
    DEFAULT_PAGE_SIZE,
    PROGRAM_REPORT_COLUMNS,
    TRAFFIC_SOURCES_REPORT_COLUMNS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.source import FirstPromoterSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.firstpromoter import (
    FirstPromoterSourceConfig,
)


def _rows(count: int, start_id: int = 1) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(count)]


def _request() -> Mock:
    request = Mock()
    request.params = None
    return request


def _driver() -> SourceDriver:
    return SourceDriver(FirstPromoterSource(), FirstPromoterSourceConfig(api_key="fp-key", account_id="98765"))


class TestFirstPromoterTransport:
    @parameterized.expand(
        [
            ("full_page_keeps_paging", _rows(DEFAULT_PAGE_SIZE), True),
            # The vendor's documented end-of-data signal: fewer records than per_page.
            ("short_page_is_terminal", _rows(DEFAULT_PAGE_SIZE - 1), False),
            ("empty_page_is_terminal", [], False),
        ]
    )
    def test_paginator_termination(self, _name: str, data: list[dict[str, Any]], expected_has_next: bool) -> None:
        paginator = FirstPromoterPaginator()
        paginator.update_state(Mock(), data=data)
        assert paginator.has_next_page is expected_has_next

    def test_paginator_stops_when_a_page_repeats(self) -> None:
        # An endpoint that ignores `page` would otherwise return the same full page forever and
        # spin until the Temporal activity times out.
        paginator = FirstPromoterPaginator()
        page = _rows(DEFAULT_PAGE_SIZE)

        paginator.update_state(Mock(), data=page)
        assert paginator.has_next_page is True

        paginator.update_state(Mock(), data=list(page))
        assert paginator.has_next_page is False

    def test_paginator_sends_page_and_page_size(self) -> None:
        paginator = FirstPromoterPaginator()
        request = _request()

        paginator.init_request(request)
        assert request.params == {"page": 1, "per_page": DEFAULT_PAGE_SIZE}

        paginator.update_state(Mock(), data=_rows(DEFAULT_PAGE_SIZE))
        paginator.update_request(request)
        assert request.params == {"page": 2, "per_page": DEFAULT_PAGE_SIZE}

    @parameterized.expand(
        [
            ("naive_datetime", datetime(2026, 3, 1, 12, 30, 45, 999999), "2026-03-01"),
            ("aware_datetime", datetime(2026, 3, 1, 23, 59, 59, tzinfo=UTC), "2026-03-01"),
            ("date", date(2026, 3, 1), "2026-03-01"),
            ("passthrough_string", "1970-01-01", "1970-01-01"),
        ]
    )
    def test_format_filter_date(self, _name: str, value: Any, expected: str) -> None:
        assert _format_filter_date(value) == expected

    def test_commissions_resource_honors_user_selected_cursor(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource("commissions", should_use_incremental_field=True, incremental_field_name="created_at"),
        )
        assert resource["endpoint"]["incremental"]["cursor_path"] == "created_at"

    @parameterized.expand(
        [
            ("payouts",),
            ("promo_codes",),
            ("promoter_campaigns",),
            ("promoters",),
            ("referrals",),
        ]
    )
    def test_full_refresh_endpoints_never_send_an_incremental_filter(self, endpoint: str) -> None:
        # These have no usable incremental filter, so asking for incremental must not quietly
        # produce a merge write with no window on it.
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=True))
        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]

    @parameterized.expand(
        [
            # Only /promoters wraps its rows in an envelope; the rest return a bare array.
            ("promoters", "data"),
            ("commissions", None),
            ("referrals", None),
            ("payouts", None),
            ("promo_codes", None),
            ("promoter_campaigns", None),
        ]
    )
    def test_response_envelope_per_endpoint(self, endpoint: str, expected_selector: str | None) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=False))
        assert resource["endpoint"].get("data_selector") == expected_selector
        # Fail loud on a changed response shape instead of silently syncing 0 rows.
        assert resource["endpoint"]["data_selector_required"] is True

    def test_promoters_resource_strips_the_password_setup_credential(self) -> None:
        # `password_setup_url` is a live link that sets the promoter's password; stripping it in the
        # data_map is what keeps it out of the warehouse table. Losing this wiring is a silent
        # account-takeover leak, so pin the behaviour end to end.
        resource = cast(dict[str, Any], get_resource("promoters", should_use_incremental_field=False))
        redacted = resource["data_map"]({"id": 1, "email": "a@b.com", "password_setup_url": "https://fp/setup"})
        assert redacted == {"id": 1, "email": "a@b.com"}

    @parameterized.expand([("commissions",), ("payouts",), ("promo_codes",), ("promoter_campaigns",), ("referrals",)])
    def test_non_promoter_resources_keep_every_field(self, endpoint: str) -> None:
        # Only /promoters carries a credential; the redaction must not silently drop columns anywhere
        # else, so these endpoints get no data_map at all.
        resource = cast(dict[str, Any], get_resource(endpoint, should_use_incremental_field=False))
        assert "data_map" not in resource

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "rejected these credentials"),
            (403, False, "rejected these credentials"),
            (404, False, "couldn't find an account for that account ID"),
            (500, False, "unexpected status code"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, status: int, expected_valid: bool, message_fragment: str | None
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            is_valid, message = validate_credentials("fp-key", "98765", "v2")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        request = network.requests_log[0]
        assert request.url == "https://api.firstpromoter.com/api/v2/company/promoters?per_page=1"
        assert request.headers["authorization"] == "Bearer fp-key"
        assert request.headers["account-id"] == "98765"
        assert network.session_options[0]["allow_redirects"] is False
        # The probe reads /promoters, whose bodies carry the password_setup_url credential and PII.
        assert network.session_options[0]["capture"] is False

    def test_saved_state_resumes_at_the_next_page(self) -> None:
        result = _driver().run(
            "commissions",
            [ScriptedResponse(json=_rows(1))],
            resume_state=FirstPromoterResumeConfig(page=7),
        )

        assert result.raised is None
        assert result.params("page") == ["7"]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter.rest_api_resource"
    )
    def test_resume_hook_saves_state_only_when_there_is_a_next_page(self, mock_rest_api_resource: MagicMock) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = False

        first_promoter_source(
            api_key="fp-key",
            account_id="98765",
            endpoint="commissions",
            team_id=1,
            job_id="job-1",
            api_version="v2",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]

        resume_hook({"page": 3})
        assert manager.save_state.call_args.args[0] == FirstPromoterResumeConfig(page=3)

        manager.save_state.reset_mock()
        resume_hook(None)
        resume_hook({})
        manager.save_state.assert_not_called()

    @parameterized.expand(
        [
            ("commissions", ["id"], ["created_at"]),
            ("promoters", ["id"], ["joined_at"]),
            ("promo_codes", ["id"], None),
        ]
    )
    def test_source_response_keys_and_partitioning(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_partition_keys: list[str] | None,
    ) -> None:
        payload = {"data": _rows(1)} if endpoint == "promoters" else _rows(1)
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])
        assert result.raised is None
        response = result.response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == expected_partition_keys
        # Partitioning on a field that never changes once set; never on a mutating one.
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)

    @parameterized.expand(
        [
            (
                "reports_overview",
                PROGRAM_REPORT_COLUMNS,
                [
                    {"period": "2026-01", "id": "2026-01", "data": {"clicks_count": 10, "3m_epc": 1.5}},
                    {"period": "2026-02", "id": "2026-02", "data": {"clicks_count": 4, "3m_epc": 0.5}},
                ],
                [
                    {"period": "2026-01", "clicks_count": 10, "3m_epc": 1.5},
                    {"period": "2026-02", "clicks_count": 4, "3m_epc": 0.5},
                ],
            ),
            (
                # Grouped reports nest the per-period buckets under each campaign; the whole-window
                # totals in `data` must not become a row of their own.
                "reports_campaigns",
                PROGRAM_REPORT_COLUMNS,
                [
                    {
                        "campaign": {"id": 7, "name": "Partners", "color": "#fff"},
                        "id": 7,
                        "data": {"clicks_count": 14},
                        "sub_data": [
                            {"period": "2026-01", "id": "2026-01", "data": {"clicks_count": 10}},
                            {"period": "2026-02", "id": "2026-02", "data": {"clicks_count": 4}},
                        ],
                    },
                    {"campaign": {"id": 8, "name": "Empty"}, "id": 8, "data": {}, "sub_data": []},
                ],
                [
                    {"campaign_id": 7, "campaign_name": "Partners", "period": "2026-01", "clicks_count": 10},
                    {"campaign_id": 7, "campaign_name": "Partners", "period": "2026-02", "clicks_count": 4},
                ],
            ),
            (
                "reports_traffic_sources",
                TRAFFIC_SOURCES_REPORT_COLUMNS,
                [
                    {
                        "source": "youtube.com",
                        "id": "youtube.com",
                        "data": {"clicks_count": 3},
                        "sub_data": [{"period": "2026-01", "id": "2026-01", "data": {"clicks_count": 3}}],
                    }
                ],
                [{"source": "youtube.com", "period": "2026-01", "clicks_count": 3}],
            ),
        ]
    )
    def test_report_is_one_windowed_request_flattened_to_one_row_per_period(
        self,
        endpoint: str,
        expected_columns: tuple[str, ...],
        payload: list[dict[str, Any]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])

        assert result.raised is None
        assert result.rows == expected_rows
        assert len(result.requests) == 1
        query = result.queries[0]
        assert query["columns[]"] == expected_columns
        assert query["group_by"] == ("month",)
        assert query["start_date"] == ("2014-01-01T00:00:00Z",)
        assert "end_date" in query
        assert "page" not in query

    def test_referral_links_fan_out_over_promoters(self) -> None:
        result = _driver().run(
            "promoter_referral_links",
            route(
                {
                    "/promoters": [
                        ScriptedResponse(
                            json={"data": [{"id": 1, "password_setup_url": "https://fp/setup"}, {"id": 2}]}
                        )
                    ],
                    "/promoters/1/referral_links": [
                        ScriptedResponse(
                            json=[
                                {"id": None, "url": "https://example.com/?fpr=a", "is_default": True},
                                {"id": "5", "url": "https://example.com/?fpr=a&fp_sid=x", "sub_id": "x"},
                            ]
                        )
                    ],
                    # A promoter deleted after the listing must not fail the whole fan-out.
                    "/promoters/2/referral_links": [ScriptedResponse(status=404, json={"code": "not_found"})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": None, "url": "https://example.com/?fpr=a", "is_default": True, "promoter_id": 1},
            {"id": "5", "url": "https://example.com/?fpr=a&fp_sid=x", "sub_id": "x", "promoter_id": 1},
        ]
        assert result.queries[0] == {
            "page": ("1",),
            "per_page": (str(DEFAULT_PAGE_SIZE),),
            "sorting[joined_at]": ("asc",),
        }
