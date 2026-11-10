import datetime as dt
from typing import Any, Optional

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.sources.stigg._config import StiggSourceConfig
from products.warehouse_sources.sources.stigg.settings import ENDPOINTS, STIGG_ENDPOINTS
from products.warehouse_sources.sources.stigg.source import StiggSource
from products.warehouse_sources.sources.stigg.stigg import PAGE_SIZE, StiggResumeConfig, validate_credentials


def _response(
    items: Optional[list[dict[str, Any]]], next_cursor: Optional[str] = None, *, raw_body: Any = None
) -> ScriptedResponse:
    """Build a Stigg list-endpoint response: ``{"data": [...], "pagination": {"next": ...}}``.

    ``raw_body`` overrides the whole body for malformed-shape cases (a bare array, or a dict
    without ``data``).
    """
    if raw_body is not None:
        body: Any = raw_body
    else:
        body = {"data": items or [], "pagination": {"next": next_cursor, "prev": None}}
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(StiggSource(), StiggSourceConfig(api_key="stigg-key"))


class TestPagination:
    def test_follows_next_cursor_until_null(self) -> None:
        result = _driver().run(
            "customers",
            [
                _response([{"id": "1"}, {"id": "2"}], next_cursor="cursor-page-2"),
                _response([{"id": "3"}], next_cursor=None),
            ],
        )

        assert result.rows == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        # First page carries only `limit`; the second sends the `after` cursor.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),)}
        assert result.queries[1] == {"limit": (str(PAGE_SIZE),), "after": ("cursor-page-2",)}
        # State is saved after the first page (cursor advances to pagination.next), then we stop.
        assert result.saved_states == [StiggResumeConfig(cursor="cursor-page-2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "customers",
            [_response([{"id": "5"}], next_cursor=None)],
            resume_state=StiggResumeConfig(cursor="cur-99"),
        )

        assert result.rows == [{"id": "5"}]
        # The initial (cursorless) page is never fetched on resume — the first request carries `after`.
        assert len(result.requests) == 1
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),), "after": ("cur-99",)}

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("customers", [_response([], next_cursor=None)])

        assert result.rows == []
        assert result.saved_states == []

    def test_empty_page_with_cursor_stops_without_saving(self) -> None:
        # Defensive: an empty page terminates even if the API still returns a next cursor,
        # so a buggy upstream cursor can't loop us forever.
        result = _driver().run("customers", [_response([], next_cursor="phantom-cursor")])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("customers", always(ScriptedResponse(status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        # 429/5xx are retried up to the client's attempt cap.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("customers", [ScriptedResponse(status=status)])

        # 4xx (other than 429) is a permanent failure — surfaced immediately, not retried.
        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("bare_array", [{"id": "1"}]),
            ("missing_data_key", {"pagination": {"next": None}}),
            ("data_not_a_list", {"data": {"id": "1"}, "pagination": {"next": None}}),
        ]
    )
    def test_malformed_body_shape_is_retryable(self, _name: str, raw_body: Any) -> None:
        result = _driver().run("customers", always(ScriptedResponse(json=raw_body)))

        # A 200 whose body isn't `{"data": [...]}` is transient — retried, then reraised.
        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            (
                "forbidden",
                403,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            ("server_error", 500, False, "Stigg returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: Optional[str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("stigg-key") == (expected_valid, expected_message)

    def test_connection_error_maps_to_generic_message(self) -> None:
        # validate_via_probe swallows transport errors and returns (False, None).
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("stigg-key") == (False, "Could not validate Stigg API key")


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == STIGG_ENDPOINTS[endpoint].primary_keys
        partition_key = STIGG_ENDPOINTS[endpoint].partition_key
        if partition_key is None:
            # Customer entitlement rows carry no creation time to partition on.
            assert response.partition_keys is None
        else:
            # createdAt is required on every list DTO and never changes, so it's a stable partition key.
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"
            assert response.partition_keys == [partition_key]

    @parameterized.expand([("plans",), ("addons",)])
    def test_versioned_packages_use_composite_primary_key(self, endpoint: str) -> None:
        # Plans and addons share their `id` slug across versions; dropping `versionNumber` from
        # the key would seed duplicate rows and multi-match every later merge.
        assert STIGG_ENDPOINTS[endpoint].primary_keys == ["id", "versionNumber"]


def _routed(table: dict[tuple[str, frozenset[tuple[str, str]]], list[ScriptedResponse]]) -> Any:
    """Answer each (path, query) pair from its own queue, so a test pins the exact request set."""
    queues = {key: list(responses) for key, responses in table.items()}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        key = (request.path, frozenset((name, values[0]) for name, values in request.query.items()))
        queue = queues.get(key)
        if not queue:
            raise AssertionError(f"unexpected request {request.url}")
        return queue.pop(0)

    return respond


def _key(path: str, **query: str) -> tuple[str, frozenset[tuple[str, str]]]:
    return f"/api/v1{path}", frozenset(query.items())


_LIMIT = str(PAGE_SIZE)


class TestVersionedPackageFanout:
    @parameterized.expand(
        [
            ("plan_entitlements", "plans", "planId", "/entitlements", {}),
            ("plan_charges", "plans", "planId", "/charges", {"limit": _LIMIT}),
            ("plan_overage_charges", "plans", "planId", "/overage-charges", {"limit": _LIMIT}),
            ("addon_charges", "addons", "addonId", "/charges", {"limit": _LIMIT}),
        ]
    )
    def test_one_request_series_per_package_id_across_versions(
        self, endpoint: str, parent: str, parent_key: str, suffix: str, child_query: dict[str, str]
    ) -> None:
        # `basic` is listed twice (two versions, pages apart) but its sub-resource takes only the
        # package id, so it is fetched once. The framework only skips a repeated path within the
        # last two parent pages.
        responses = {
            _key(f"/{parent}", limit=_LIMIT): [
                _response([{"id": "basic", "versionNumber": 1}, {"id": "pro", "versionNumber": 1}], "page-2")
            ],
            _key(f"/{parent}", limit=_LIMIT, after="page-2"): [
                _response([{"id": "team", "versionNumber": 1}], "page-3")
            ],
            _key(f"/{parent}", limit=_LIMIT, after="page-3"): [_response([{"id": "basic", "versionNumber": 2}])],
            _key(f"/{parent}/basic{suffix}", **child_query): [_response([{"id": "c1"}], "child-2")],
            _key(f"/{parent}/basic{suffix}", **child_query, after="child-2"): [_response([{"id": "c2"}])],
            _key(f"/{parent}/pro{suffix}", **child_query): [_response([{"id": "c1"}])],
            _key(f"/{parent}/team{suffix}", **child_query): [_response([])],
        }

        result = _driver().run(endpoint, _routed(responses))

        assert result.raised is None
        assert [(row[parent_key], row["id"]) for row in result.rows] == [
            ("basic", "c1"),
            ("basic", "c2"),
            ("pro", "c1"),
        ]
        assert all(not any(key.startswith(f"_{parent}_") for key in row) for row in result.rows)
        assert len(result.requests) == 7

    def test_deleted_plan_404_is_skipped(self) -> None:
        responses = {
            _key("/plans", limit=_LIMIT): [_response([{"id": "gone"}, {"id": "pro"}])],
            _key("/plans/gone/charges", limit=_LIMIT): [ScriptedResponse(status=404, json={})],
            _key("/plans/pro/charges", limit=_LIMIT): [_response([{"id": "c1"}])],
        }

        result = _driver().run("plan_charges", _routed(responses))

        assert result.raised is None
        assert [(row["planId"], row["id"]) for row in result.rows] == [("pro", "c1")]

    def test_resumes_inside_the_saved_plan(self) -> None:
        responses = {
            _key("/plans", limit=_LIMIT, after="plans-2"): [_response([{"id": "basic"}, {"id": "pro"}])],
            _key("/plans/pro/charges", limit=_LIMIT, after="child-3"): [_response([{"id": "c3"}])],
        }
        fanout_state: dict[str, Any] = {
            "completed": ["/plans/basic/charges"],
            "current": "/plans/pro/charges",
            "child_state": {"cursor": "child-3"},
            "parent": {"cursor": "plans-2"},
        }

        result = _driver().run(
            "plan_charges", _routed(responses), resume_state=StiggResumeConfig(fanout_state=fanout_state)
        )

        assert result.raised is None
        assert [(row["planId"], row["id"]) for row in result.rows] == [("pro", "c3")]


class TestCustomerFanout:
    @parameterized.expand(
        [
            ("full_refresh", False, dt.datetime(2026, 3, 1, tzinfo=dt.UTC), {}),
            ("first_incremental_sync", True, None, {}),
            (
                "incremental",
                True,
                dt.datetime(2026, 3, 1, 12, 30, tzinfo=dt.UTC),
                {"startDate": "2026-03-01T12:30:00.000Z"},
            ),
            (
                "incremental_naive_value",
                True,
                dt.datetime(2026, 3, 1, 12, 30),
                {"startDate": "2026-03-01T12:30:00.000Z"},
            ),
        ]
    )
    def test_credit_ledger_sends_the_watermark_on_every_page_of_every_customer(
        self,
        _name: str,
        should_use_incremental_field: bool,
        last_value: Optional[dt.datetime],
        window: dict[str, str],
    ) -> None:
        responses = {
            _key("/customers", limit=_LIMIT): [_response([{"id": "acme"}, {"id": "beta"}])],
            _key("/credits/ledger", customerId="acme", limit=_LIMIT, **window): [
                _response([{"timestamp": "2026-03-02T00:00:00Z", "eventType": "CREDITS_GRANTED"}], "ledger-2")
            ],
            _key("/credits/ledger", customerId="acme", limit=_LIMIT, after="ledger-2", **window): [
                _response([{"timestamp": "2026-03-03T00:00:00Z", "eventType": "CREDITS_CONSUMED"}])
            ],
            _key("/credits/ledger", customerId="beta", limit=_LIMIT, **window): [_response([])],
        }

        result = _driver().run(
            "credit_ledger",
            _routed(responses),
            should_use_incremental_field=should_use_incremental_field,
            incremental_field="timestamp",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [(row["customerId"], row["eventType"]) for row in result.rows] == [
            ("acme", "CREDITS_GRANTED"),
            ("acme", "CREDITS_CONSUMED"),
        ]
        assert len(result.requests) == 4

    def test_credit_grants_walk_pages_per_customer_with_an_encoded_id(self) -> None:
        responses = {
            _key("/customers", limit=_LIMIT): [_response([{"id": "acme/eu team"}, {"id": "beta"}])],
            _key("/credits/grants", customerId="acme/eu team", limit=_LIMIT): [
                _response([{"id": "g1", "customerId": "acme/eu team"}], "grants-2")
            ],
            _key("/credits/grants", customerId="acme/eu team", limit=_LIMIT, after="grants-2"): [
                _response([{"id": "g2", "customerId": "acme/eu team"}])
            ],
            _key("/credits/grants", customerId="beta", limit=_LIMIT): [_response([])],
        }

        result = _driver().run("credit_grants", _routed(responses))

        assert result.raised is None
        assert [(row["customerId"], row["id"]) for row in result.rows] == [
            ("acme/eu team", "g1"),
            ("acme/eu team", "g2"),
        ]
        assert "customerId=acme%2Feu%20team" in result.requests[1].url

    def test_customer_entitlements_lift_the_feature_or_currency_key(self) -> None:
        feature = {"isGranted": True, "type": "FEATURE", "feature": {"id": "feature-seats"}, "usageLimit": 5}
        credit = {"isGranted": True, "type": "CREDIT", "currency": {"currencyId": "cred-ai"}, "usageLimit": 100}
        responses = {
            _key("/customers", limit=_LIMIT): [_response([{"id": "acme/eu"}, {"id": "lapsed"}])],
            _key("/customers/acme%2Feu/entitlements"): [
                ScriptedResponse(json={"data": {"entitlements": [feature, credit], "accessDeniedReason": None}})
            ],
            _key("/customers/lapsed/entitlements"): [
                ScriptedResponse(
                    json={"data": {"entitlements": [], "accessDeniedReason": "NoActiveSubscription"}},
                )
            ],
        }

        result = _driver().run("customer_entitlements", _routed(responses))

        assert result.raised is None
        assert [(row["customerId"], row["type"], row["featureId"], row["currencyId"]) for row in result.rows] == [
            ("acme/eu", "FEATURE", "feature-seats", None),
            ("acme/eu", "CREDIT", None, "cred-ai"),
        ]
        assert len(result.requests) == 3
