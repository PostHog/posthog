from datetime import UTC, date, datetime
from typing import Any, cast

from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter import (
    FirstPromoterPaginator,
    FirstPromoterResumeConfig,
    _format_filter_date,
    first_promoter_source,
    get_resource,
    rest_api_client_config,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.settings import DEFAULT_PAGE_SIZE


def _rows(count: int, start_id: int = 1) -> list[dict[str, Any]]:
    return [{"id": start_id + i} for i in range(count)]


def _request() -> Mock:
    request = Mock()
    request.params = None
    return request


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

    def test_paginator_keeps_paging_through_distinct_full_pages(self) -> None:
        paginator = FirstPromoterPaginator()
        paginator.update_state(Mock(), data=_rows(DEFAULT_PAGE_SIZE, start_id=1))
        paginator.update_state(Mock(), data=_rows(DEFAULT_PAGE_SIZE, start_id=1 + DEFAULT_PAGE_SIZE))
        assert paginator.has_next_page is True

    def test_paginator_sends_page_and_page_size(self) -> None:
        paginator = FirstPromoterPaginator()
        request = _request()

        paginator.init_request(request)
        assert request.params == {"page": 1, "per_page": DEFAULT_PAGE_SIZE}

        paginator.update_state(Mock(), data=_rows(DEFAULT_PAGE_SIZE))
        paginator.update_request(request)
        assert request.params == {"page": 2, "per_page": DEFAULT_PAGE_SIZE}

    def test_paginator_resume_state_round_trip(self) -> None:
        paginator = FirstPromoterPaginator()
        paginator.update_state(Mock(), data=_rows(DEFAULT_PAGE_SIZE))
        state = paginator.get_resume_state()
        assert state == {"page": 2}

        resumed = FirstPromoterPaginator()
        resumed.set_resume_state(cast(dict[str, Any], state))
        request = _request()
        resumed.init_request(request)
        assert request.params["page"] == 2

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

    def test_commissions_resource_is_incremental(self) -> None:
        resource = cast(dict[str, Any], get_resource("commissions", should_use_incremental_field=True))
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        incremental = resource["endpoint"]["incremental"]
        # A flat `created_at` param is silently ignored by the API — the filter is bracket-nested.
        assert incremental["start_param"] == "filters[created_at][from]"
        assert incremental["cursor_path"] == "created_at"
        # sort_mode="asc" checkpoints the watermark mid-sync, so the request must pin that order.
        assert resource["endpoint"]["params"]["sorting[created_at]"] == "asc"

    def test_commissions_resource_full_refresh(self) -> None:
        resource = cast(dict[str, Any], get_resource("commissions", should_use_incremental_field=False))
        assert resource["write_disposition"] == "replace"
        assert "incremental" not in resource["endpoint"]

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

    def test_client_config_sends_both_credentials_and_pins_the_host(self) -> None:
        config = rest_api_client_config("fp-key", "98765", "v2")
        assert config["base_url"] == "https://api.firstpromoter.com/api/v2/company"
        assert config["auth"] == {"type": "bearer", "token": "fp-key"}
        # Omitting the account id header fails auth even with a valid bearer token.
        assert cast(dict[str, str], config["headers"])["ACCOUNT-ID"] == "98765"
        # A redirect off the FirstPromoter host would otherwise replay the bearer token.
        assert config["allowed_hosts"] == []
        assert config["allow_redirects"] is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter.make_tracked_session"
    )
    def test_client_config_keeps_response_bodies_out_of_sample_capture(self, mock_session: MagicMock) -> None:
        # Sample capture sees the raw body before the data_map runs, so the promoter credential (and
        # PII) would leak into shared sample storage unless capture is off on the sync session.
        config = rest_api_client_config("fp-key", "98765", "v2")
        assert config["session"] is mock_session.return_value
        assert mock_session.call_args.kwargs["capture"] is False
        assert mock_session.call_args.kwargs["redact_values"] == ("fp-key",)

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "rejected these credentials"),
            (403, False, "rejected these credentials"),
            (404, False, "couldn't find an account for that account ID"),
            (500, False, "unexpected status code"),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(
        self, status: int, expected_valid: bool, message_fragment: str | None, mock_session: MagicMock
    ) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        is_valid, message = validate_credentials("fp-key", "98765", "v2")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message

        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.firstpromoter.com/api/v2/company/promoters"
        assert call.kwargs["headers"]["Authorization"] == "Bearer fp-key"
        assert call.kwargs["headers"]["ACCOUNT-ID"] == "98765"
        assert mock_session.call_args.kwargs["allow_redirects"] is False
        # The probe reads /promoters, whose bodies carry the password_setup_url credential and PII.
        assert mock_session.call_args.kwargs["capture"] is False

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter.rest_api_resource"
    )
    def test_saved_state_resumes_at_the_next_page(self, mock_rest_api_resource: MagicMock) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = FirstPromoterResumeConfig(page=7)

        first_promoter_source(
            api_key="fp-key",
            account_id="98765",
            endpoint="commissions",
            team_id=1,
            job_id="job-1",
            api_version="v2",
            resumable_source_manager=manager,
        )

        assert mock_rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"page": 7}

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
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.first_promoter.first_promoter.rest_api_resource"
    )
    def test_source_response_keys_and_partitioning(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_partition_keys: list[str] | None,
        _mock_rest_api_resource: MagicMock,
    ) -> None:
        response = first_promoter_source(
            api_key="fp-key",
            account_id="98765",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            api_version="v2",
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == expected_partition_keys
        # Partitioning on a field that never changes once set; never on a mutating one.
        assert response.partition_mode == ("datetime" if expected_partition_keys else None)
