from typing import Any, Optional

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailtrap import (
    MailtrapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.mailtrap import (
    STATS_START_DATE,
    MailtrapResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.settings import (
    ENDPOINTS,
    MAILTRAP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.source import MailtrapSource


def _driver() -> SourceDriver:
    return SourceDriver(MailtrapSource(), MailtrapSourceConfig(api_token="token"))


class TestPagination:
    def test_email_logs_incremental_sends_sent_after_on_every_page(self) -> None:
        result = _driver().run(
            "email_logs",
            [
                ScriptedResponse(json={"messages": [{"message_id": "m1"}], "next_page_cursor": "c2"}),
                ScriptedResponse(json={"messages": [{"message_id": "m2"}], "next_page_cursor": None}),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        # The server-side bound must ride along with the cursor, or later pages walk unbounded
        # through already-synced history.
        assert result.raised is None
        assert result.rows == [{"message_id": "m1"}, {"message_id": "m2"}]
        assert result.params("filters[sent_after]") == ["2026-01-01T00:00:00Z"] * 2
        assert result.params("search_after") == [None, "c2"]

    def test_email_logs_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "email_logs",
            [ScriptedResponse(json={"messages": [{"message_id": "m2"}], "next_page_cursor": None})],
            resume_state=MailtrapResumeConfig(cursor="c2"),
        )
        assert result.raised is None
        assert result.rows == [{"message_id": "m2"}]
        # The first page must never be re-fetched on resume: the saved cursor rides the first request.
        assert result.params("search_after") == ["c2"]

    def test_suppressions_paginates_by_last_row_id_until_short_page(self) -> None:
        page_size = MAILTRAP_ENDPOINTS["suppressions"].page_size
        assert page_size is not None
        full_page = [{"id": f"s{i}"} for i in range(page_size)]
        short_page = [{"id": "last"}]
        result = _driver().run("suppressions", [ScriptedResponse(json=full_page), ScriptedResponse(json=short_page)])
        assert result.raised is None
        assert len(result.rows) == page_size + 1
        # The cursor advances from the last row of the full page; the short page ends the sync.
        assert result.params("last_id") == [None, full_page[-1]["id"]]
        assert result.saved_states == [MailtrapResumeConfig(cursor=full_page[-1]["id"])]

    def test_suppressions_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "suppressions",
            [ScriptedResponse(json=[{"id": "s_last"}])],
            resume_state=MailtrapResumeConfig(cursor="s99"),
        )
        assert result.raised is None
        # The saved last-row id seeds the first request so already-synced pages are skipped.
        assert result.params("last_id") == ["s99"]

    @parameterized.expand(
        [
            ("contacts", "018dd5e3-a", 50),
            ("email_campaigns", 2, 100),
        ]
    )
    def test_pagination_token_endpoints_follow_next_token(self, endpoint: str, next_token: Any, per_page: int) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "a"}], "pagination": {"next_token": next_token}}),
                ScriptedResponse(json={"data": [{"id": "b"}], "pagination": {"next_token": None}}),
            ],
        )
        assert result.raised is None
        assert result.rows == [{"id": "a"}, {"id": "b"}]
        assert result.params("token") == [None, str(next_token)]
        assert result.params("per_page") == [str(per_page)] * 2
        assert result.saved_states == [MailtrapResumeConfig(cursor=str(next_token))]

    def test_sending_stats_by_date_sends_required_window_and_flattens_stats(self) -> None:
        with time_machine.travel("2026-03-15T12:00:00Z", tick=False):
            result = _driver().run(
                "sending_stats_by_date",
                [ScriptedResponse(json=[{"date": "2026-01-01", "stats": {"delivery_count": 190, "open_rate": 0.9}}])],
            )
        assert result.raised is None
        # start_date and end_date are required: omitting either returns a 400.
        assert result.params("start_date") == [STATS_START_DATE]
        assert result.params("end_date") == ["2026-03-15"]
        assert result.rows == [{"date": "2026-01-01", "delivery_count": 190, "open_rate": 0.9}]

    @parameterized.expand(
        [
            ("email_templates", [{"id": 1}]),
            ("contact_lists", [{"id": 2, "name": "list"}]),
            ("accounts", [{"id": 3, "name": "acct"}]),
        ]
    )
    def test_unpaginated_bare_array_endpoints_fetch_once(self, endpoint: str, body: list[dict[str, Any]]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        assert result.rows == body
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestRetryClassification:
    @parameterized.expand(
        [
            ("email_logs_bare_list", "email_logs", [{"message_id": "m1"}]),
            ("email_logs_missing_key", "email_logs", {"total_count": 0}),
            ("templates_wrapped", "email_templates", {"data": []}),
        ]
    )
    def test_unexpected_payload_is_retryable(self, _name: str, endpoint: str, body: Any) -> None:
        result = _driver().run(endpoint, always(ScriptedResponse(json=body)))
        assert isinstance(result.raised, RESTClientRetryableError)

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _driver().run("email_logs", always(ScriptedResponse(status=status, json={"messages": []})))
        assert isinstance(result.raised, RESTClientRetryableError)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("email_logs", [ScriptedResponse(status=status, json={"error": "nope"})])
        assert isinstance(result.raised, requests.HTTPError)


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        config = MAILTRAP_ENDPOINTS[endpoint]
        body: Any = {config.data_key: []} if config.data_key else []
        result = _driver().run(endpoint, [ScriptedResponse(json=body)])
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.incremental_param:
            # The watermark must only commit once a sync completes: email_logs is documented
            # newest-first and suppressions ordering is undocumented.
            assert response.sort_mode == "desc"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.sort_mode == "asc"
        assert response.partition_mode == ("datetime" if config.partition_key else None)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: Optional[str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("token") == (expected_valid, expected_message)
        assert {request.path for request in network.requests_log} == {"/api/accounts"}

    def test_connection_error_is_not_validated(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))) as network:
            valid, message = validate_credentials("token")
        assert valid is False
        assert message == "Could not connect to Mailtrap"
        assert {request.path for request in network.requests_log} == {"/api/accounts"}
