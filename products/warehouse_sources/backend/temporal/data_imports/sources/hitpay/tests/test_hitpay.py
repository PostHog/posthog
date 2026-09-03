import json
from datetime import UTC, date, datetime
from typing import Any, cast

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.hitpay import (
    HitpayResumeConfig,
    _format_charge_date,
    _paginator_for,
    base_url_for_environment,
    get_resource,
    hitpay_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.settings import (
    HITPAY_ENDPOINTS,
    RECURRING_BILLING_STATUSES,
)

# RESTClient (and the hand-rolled RecurringBilling client) build their session via
# make_tracked_session, imported directly into the hitpay module.
SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.hitpay.make_tracked_session"
VALIDATE_SESSION_PATCH = SESSION_PATCH


class TestBaseUrlForEnvironment:
    @parameterized.expand(
        [
            ("production", "production", "https://api.hit-pay.com"),
            ("sandbox", "sandbox", "https://api.sandbox.hit-pay.com"),
            ("none_defaults_to_production", None, "https://api.hit-pay.com"),
            ("unknown_defaults_to_production", "staging", "https://api.hit-pay.com"),
        ]
    )
    def test_base_url(self, _name: str, environment: str | None, expected: str) -> None:
        assert base_url_for_environment(environment) == expected


class TestFormatChargeDate:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04"),
            ("date_value", date(2026, 3, 4), "2026-03-04"),
            ("string_passthrough", "1970-01-01", "1970-01-01"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_charge_date(value) == expected


class TestPaginatorFor:
    def test_cursor_endpoint_gets_cursor_paginator(self) -> None:
        paginator = _paginator_for(HITPAY_ENDPOINTS["Charges"])
        assert isinstance(paginator, JSONResponseCursorPaginator)
        assert paginator.cursor_path == "meta.next_cursor"
        assert paginator.cursor_param == "cursor"

    def test_page_endpoint_gets_page_number_paginator_with_configured_param(self) -> None:
        paginator = _paginator_for(HITPAY_ENDPOINTS["PaymentRequests"])
        assert isinstance(paginator, PageNumberPaginator)
        assert paginator.page_param == "current_page"
        assert paginator.base_page == 1

    def test_single_endpoint_gets_single_page_paginator(self) -> None:
        assert isinstance(_paginator_for(HITPAY_ENDPOINTS["RecurringBilling"]), SinglePagePaginator)


class TestGetResource:
    def test_full_refresh_endpoint_has_no_incremental_param(self) -> None:
        resource = cast(dict[str, Any], get_resource("Customers", should_use_incremental_field=True))
        assert resource["endpoint"]["params"] == {}
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["data_selector"] == "data"
        assert resource["endpoint"]["path"] == "/v1/customers"

    def test_incremental_endpoint_adds_date_from_when_enabled(self) -> None:
        resource = cast(dict[str, Any], get_resource("Charges", should_use_incremental_field=True))
        assert "date_from" in resource["endpoint"]["params"]
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_incremental_endpoint_omits_date_from_when_disabled(self) -> None:
        resource = cast(dict[str, Any], get_resource("Charges", should_use_incremental_field=False))
        assert resource["endpoint"]["params"] == {}
        assert resource["write_disposition"] == "replace"

    def test_table_name_matches_settings(self) -> None:
        resource = cast(dict[str, Any], get_resource("SubscriptionPlans", should_use_incremental_field=False))
        assert resource["table_name"] == "subscription_plans"


def _response(items: list[dict[str, Any]], *, extra: dict[str, Any] | None = None) -> Response:
    body: dict[str, Any] = {"data": items}
    if extra:
        body.update(extra)
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _make_manager(resume_state: HitpayResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestHitpaySourcePageNumberEndpoint:
    @mock.patch(SESSION_PATCH)
    def test_paginates_until_last_page(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}, {"id": "2"}], extra={"meta": {"last_page": 2}}),
                _response([{"id": "3"}], extra={"meta": {"last_page": 2}}),
            ],
        )

        rows = _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="SubscriptionPlans",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        assert session.send.call_count == 2

    @mock.patch(SESSION_PATCH)
    def test_saves_resume_state_only_while_pages_remain(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], extra={"meta": {"last_page": 2}}),
                _response([{"id": "2"}], extra={"meta": {"last_page": 2}}),
            ],
        )
        manager = _make_manager()

        _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="SubscriptionPlans",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HitpayResumeConfig(next_page=2)

    @mock.patch(SESSION_PATCH)
    def test_resumes_from_saved_page(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        snapshots = _wire(session, [_response([{"id": "2"}], extra={"meta": {"last_page": 2}})])

        rows = _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="SubscriptionPlans",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(HitpayResumeConfig(next_page=2)),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert [r["id"] for r in rows] == ["2"]
        assert session.send.call_count == 1
        assert snapshots[0]["params"]["page"] == 2

    @mock.patch(SESSION_PATCH)
    def test_current_page_param_used_for_payment_requests(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        snapshots = _wire(session, [_response([{"id": "1"}], extra={"meta": {"last_page": 1}})])

        _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="PaymentRequests",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert "current_page" in snapshots[0]["params"]
        assert "page" not in snapshots[0]["params"]


class TestHitpaySourceCursorEndpoint:
    @mock.patch(SESSION_PATCH)
    def test_paginates_via_cursor(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], extra={"meta": {"next_cursor": "abc"}}),
                _response([{"id": "2"}], extra={"meta": {"next_cursor": None}}),
            ],
        )

        rows = _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="Charges",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert [r["id"] for r in rows] == ["1", "2"]
        assert session.send.call_count == 2

    @mock.patch(SESSION_PATCH)
    def test_saves_cursor_resume_state(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        _wire(
            session,
            [
                _response([{"id": "1"}], extra={"meta": {"next_cursor": "abc"}}),
                _response([{"id": "2"}], extra={"meta": {"next_cursor": None}}),
            ],
        )
        manager = _make_manager()

        _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="Charges",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == HitpayResumeConfig(next_cursor="abc")

    @mock.patch(SESSION_PATCH)
    def test_incremental_date_from_sent_when_enabled(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        snapshots = _wire(session, [_response([{"id": "1"}], extra={"meta": {"next_cursor": None}})])

        _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="Charges",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
            )
        )

        assert snapshots[0]["params"]["date_from"] == "2026-03-04"


class TestRecurringBillingFanOut:
    @mock.patch(SESSION_PATCH)
    def test_requests_every_status_and_concatenates_rows(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        responses = [_response([{"id": status}]) for status in RECURRING_BILLING_STATUSES]
        snapshots = _wire(session, responses)

        rows = _rows(
            hitpay_source(
                api_key="key",
                platform_api_key="platform-key",
                environment="production",
                endpoint="RecurringBilling",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert [r["id"] for r in rows] == list(RECURRING_BILLING_STATUSES)
        assert session.send.call_count == len(RECURRING_BILLING_STATUSES)
        assert [s["params"]["status"] for s in snapshots] == list(RECURRING_BILLING_STATUSES)

    @mock.patch(SESSION_PATCH)
    def test_empty_status_pages_are_skipped(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        responses = [_response([]) for _ in RECURRING_BILLING_STATUSES]
        responses[0] = _response([{"id": "only-active"}])
        _wire(session, responses)

        rows = _rows(
            hitpay_source(
                api_key="key",
                platform_api_key=None,
                environment="production",
                endpoint="RecurringBilling",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_make_manager(),
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )
        )

        assert [r["id"] for r in rows] == ["only-active"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, True, None),
            ("invalid_key", 401, False, "Invalid HitPay API key"),
            ("forbidden", 403, False, "Could not connect to HitPay"),
            ("unreachable", None, False, "Could not connect to HitPay"),
        ]
    )
    @mock.patch(VALIDATE_SESSION_PATCH)
    def test_validate_credentials(
        self,
        _name: str,
        status_code: int | None,
        expected_valid: bool,
        expected_message_snippet: str | None,
        mock_make_session: mock.MagicMock,
    ) -> None:
        session = mock_make_session.return_value
        if status_code is None:
            session.get.side_effect = ConnectionError("boom")
        else:
            resp = Response()
            resp.status_code = status_code
            session.get.return_value = resp

        is_valid, message = validate_credentials("key", None, "production")

        assert is_valid is expected_valid
        if expected_message_snippet is None:
            assert message is None
        else:
            assert expected_message_snippet in (message or "")

    @mock.patch(VALIDATE_SESSION_PATCH)
    def test_sends_platform_key_header_when_provided(self, mock_make_session: mock.MagicMock) -> None:
        session = mock_make_session.return_value
        resp = Response()
        resp.status_code = 200
        session.get.return_value = resp

        validate_credentials("key", "platform-key", "sandbox")

        _, kwargs = session.get.call_args
        assert kwargs["headers"]["X-BUSINESS-API-KEY"] == "key"
        assert kwargs["headers"]["X-PLATFORM-KEY"] == "platform-key"
        assert session.get.call_args.args[0] == "https://api.sandbox.hit-pay.com/v1/account-status"
