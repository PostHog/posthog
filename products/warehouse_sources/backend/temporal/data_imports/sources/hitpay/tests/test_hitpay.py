import json
from datetime import UTC, date, datetime
from typing import Any

from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.hitpay import (
    HitpayResumeConfig,
    _format_charge_date,
    _paginator_for,
    base_url_for_environment,
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
    def test_single_endpoint_gets_single_page_paginator(self) -> None:
        assert isinstance(_paginator_for(HITPAY_ENDPOINTS["RecurringBilling"]), SinglePagePaginator)


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
