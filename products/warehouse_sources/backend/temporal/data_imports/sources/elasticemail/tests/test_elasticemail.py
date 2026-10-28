from datetime import UTC, date, datetime
from typing import Any

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail import elasticemail
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.elasticemail import (
    AUTH_ERROR_MARKER,
    ElasticEmailResumeConfig,
    _clamp_future_value_to_now,
    _format_datetime,
    _is_auth_error_body,
    _static_params,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import (
    ELASTICEMAIL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.source import ElasticemailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.elasticemail import (
    ElasticemailSourceConfig,
)


def _driver() -> SourceDriver:
    return SourceDriver(ElasticemailSource(), ElasticemailSourceConfig(api_key="key"))


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format_datetime(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime(value) == expected


class TestClampFutureValueToNow:
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_future_datetime_is_clamped(self) -> None:
        assert _clamp_future_value_to_now(datetime(2027, 2, 5, tzinfo=UTC)) == datetime(
            2026, 6, 15, 12, 0, 0, tzinfo=UTC
        )


class TestStaticParams:
    def test_full_refresh_endpoint_never_adds_from(self) -> None:
        # Contacts has no server-side time filter, so a cursor value must not leak into the request.
        params = _static_params(
            ELASTICEMAIL_ENDPOINTS["contacts"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert "from" not in params


class TestIsAuthErrorBody:
    @parameterized.expand(
        [
            ("401", 401, "", True),
            ("403", 403, "", True),
            ("400_apikey_expired", 400, '{"Error":"APIKey Expired"}', True),
            ("400_incorrect_key", 400, '{"Error":"Incorrect API key."}', True),
            ("400_generic_bad_request", 400, '{"Error":"Invalid date range"}', False),
            ("404", 404, '{"Error":"Not found"}', False),
            ("200", 200, "[]", False),
        ]
    )
    def test_is_auth_error_body(self, _name: str, status: int, body: str, expected: bool) -> None:
        assert _is_auth_error_body(status, body) is expected


class TestPagination:
    def test_paginates_until_short_page(self) -> None:
        full_page = [{"Email": f"c{i}@x.com"} for i in range(elasticemail.PAGE_SIZE)]
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json=full_page), ScriptedResponse(json=[{"Email": "last@x.com"}])],
        )

        assert result.raised is None
        assert [row["Email"] for row in result.rows] == [
            *(f"c{i}@x.com" for i in range(elasticemail.PAGE_SIZE)),
            "last@x.com",
        ]
        assert result.params("offset") == ["0", str(elasticemail.PAGE_SIZE)]
        assert result.params("limit") == [str(elasticemail.PAGE_SIZE)] * 2

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "contacts",
            [ScriptedResponse(json=[{"Email": "resumed@x.com"}])],
            resume_state=ElasticEmailResumeConfig(offset=2000),
        )

        assert result.raised is None
        assert result.params("offset") == ["2000"]
        assert [row["Email"] for row in result.rows] == ["resumed@x.com"]


class TestListContactsFanout:
    def test_fans_out_per_list_with_encoded_names(self) -> None:
        result = _driver().run(
            "list_contacts",
            [
                ScriptedResponse(json=[{"ListName": "News / EU"}, {"ListName": "Gone"}, {"ListName": "VIP"}]),
                ScriptedResponse(json=[{"Email": "a@example.com"}, {"Email": "b@example.com"}]),
                ScriptedResponse(status=404, body=b'{"Error":"List not found"}'),
                ScriptedResponse(json=[{"Email": "a@example.com"}]),
            ],
        )

        assert result.raised is None
        assert [(row["ListName"], row["Email"]) for row in result.rows] == [
            ("News / EU", "a@example.com"),
            ("News / EU", "b@example.com"),
            ("VIP", "a@example.com"),
        ]
        assert [request.origin for request in result.requests] == ["https://api.elasticemail.com"] * 4
        assert result.paths == [
            "/v4/lists",
            "/v4/lists/News%20%2F%20EU/contacts",
            "/v4/lists/Gone/contacts",
            "/v4/lists/VIP/contacts",
        ]
        assert result.params("limit") == [str(elasticemail.PAGE_SIZE)] * 4


class TestDailyStatistics:
    @parameterized.expand(
        [
            (
                "incremental_refetches_watermark_day",
                True,
                date(2026, 6, 13),
                None,
                ["2026-06-13", "2026-06-14", "2026-06-15"],
            ),
            (
                "resume_skips_finished_days",
                True,
                date(2026, 6, 10),
                ElasticEmailResumeConfig(next_day="2026-06-14"),
                ["2026-06-14", "2026-06-15"],
            ),
            ("future_watermark_clamps_to_today", True, date(2026, 7, 1), None, ["2026-06-15"]),
        ]
    )
    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_walks_one_day_per_request(
        self,
        _name: str,
        incremental: bool,
        watermark: date,
        resume: ElasticEmailResumeConfig | None,
        expected_days: list[str],
    ) -> None:
        result = _driver().run(
            "statistics",
            [ScriptedResponse(json={"Delivered": i}) for i in range(len(expected_days))],
            resume_state=resume,
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert [(row["Date"], row["Delivered"]) for row in result.rows] == [
            (day, i) for i, day in enumerate(expected_days)
        ]
        assert result.params("from") == [f"{day}T00:00:00" for day in expected_days]
        assert result.params("to") == [f"{day}T23:59:59" for day in expected_days]
        assert result.params("limit") == [None] * len(expected_days)
        assert result.params("offset") == [None] * len(expected_days)

    @time_machine.travel("2026-06-15T12:00:00Z", tick=False)
    def test_full_refresh_backfills_lookback_window(self) -> None:
        days = elasticemail.STATISTICS_LOOKBACK_DAYS + 1
        result = _driver().run("statistics", [ScriptedResponse(json={"Delivered": 0}) for _ in range(days)])

        assert result.raised is None
        assert len(result.rows) == days
        assert result.params("from")[0] == "2025-06-15T00:00:00"
        assert result.params("from")[-1] == "2026-06-15T00:00:00"


class TestErrorClassification:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_statuses_raise_retryable(self, _name: str, status: int) -> None:
        result = _driver().run("contacts", always(ScriptedResponse(status=status, body=b"boom")))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) > 1

    @parameterized.expand(
        [
            ("expired_key_400", 400, '{"Error":"APIKey Expired"}'),
            ("incorrect_key_400", 400, '{"Error":"Incorrect API key."}'),
            ("unauthorized_401", 401, ""),
            ("forbidden_403", 403, ""),
        ]
    )
    def test_auth_failures_raise_marked_error(self, _name: str, status: int, body: str) -> None:
        # A bad/expired/under-scoped key surfaces a permanent, marker-carrying error so the pipeline's
        # non-retryable classifier stops the sync instead of hammering the dead key.
        result = _driver().run("contacts", [ScriptedResponse(status=status, body=body.encode())])

        assert isinstance(result.raised, ValueError)
        assert AUTH_ERROR_MARKER in str(result.raised)
        assert len(result.requests) == 1

    def test_generic_400_is_not_marked_as_auth(self) -> None:
        # A non-credential 400 raises an HTTPError with no auth marker.
        result = _driver().run("contacts", [ScriptedResponse(status=400, body=b'{"Error":"Invalid date range"}')])

        assert isinstance(result.raised, requests.HTTPError)
        assert AUTH_ERROR_MARKER not in str(result.raised)

    def test_non_list_payload_raises_shape_error(self) -> None:
        # A 200 object payload is an unexpected shape; fail loud rather than sync the object as a row.
        # The error carries no auth marker.
        result = _driver().run("contacts", always(ScriptedResponse(json={"Error": "unexpected"})))

        assert isinstance(result.raised, ValueError)
        assert AUTH_ERROR_MARKER not in str(result.raised)
        assert result.rows == []

    def test_non_json_body_raises_non_retryable(self) -> None:
        # A 200 with an HTML/proxy body can't be turned into rows by retrying (a re-fetch returns
        # the same non-JSON body), so it fails fast and non-retryably rather than propagating a raw
        # JSONDecodeError.
        result = _driver().run("contacts", [ScriptedResponse(body=b"<html>gateway timeout</html>")])

        assert isinstance(result.raised, RESTClientNonRetryableError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("expired_key", 400, '{"Error":"APIKey Expired"}', False),
            # A non-auth error (e.g. a transient 500) should not be reported as an invalid key.
            ("server_error", 500, "boom", True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, body: str, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, body=body.encode()))) as network:
            assert validate_credentials("key") is expected

        assert network.requests_log[0].path == "/v4/statistics"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].param("offset") == "0"
        assert network.requests_log[0].headers["x-elasticemail-apikey"] == "key"

    def test_transport_exception_is_invalid(self) -> None:
        with scripted_network(always(requests.ConnectionError("down"))) as network:
            assert validate_credentials("key") is False

        assert network.requests_log[0].path == "/v4/statistics"


class TestElasticemailSource:
    @parameterized.expand(
        [
            ("contacts", ["Email"], "DateAdded"),
            ("lists", ["ListName"], "DateAdded"),
            ("segments", ["Name"], None),
            ("campaigns", ["Name"], None),
            ("templates", ["Name"], "DateAdded"),
            ("events", ["TransactionID", "MsgID", "EventType", "EventDate"], "EventDate"),
            ("suppressions", ["Email"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "week"
