from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.alguna._config import AlgunaSourceConfig
from products.warehouse_sources.sources.alguna.alguna import AlgunaResumeConfig, validate_credentials
from products.warehouse_sources.sources.alguna.source import AlgunaSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(AlgunaSource(), AlgunaSourceConfig(api_key="key"))


def _response(items: list[dict[str, Any]] | None, *, drop_data: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {"pagination": {"per_page": 100}}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


class TestPagination:
    @parameterized.expand(
        [
            ("customers", "created_at:asc"),
            # /bundles documents only limit/offset; a leaked `sort` would be an undocumented param.
            ("bundles", None),
        ]
    )
    def test_paginates_and_progresses_offset(self, endpoint: str, expected_sort: str | None) -> None:
        full_page = [{"id": f"c_{i}"} for i in range(100)]
        result = _driver().run(endpoint, [_response(full_page), _response([{"id": "c_last"}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(f"c_{i}" for i in range(100)), "c_last"]
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        assert result.params("sort") == [expected_sort, expected_sort]
        # Checkpoint saved after the first full page (points at the next page); short page ends it.
        assert result.saved_states == [AlgunaResumeConfig(offset=100)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("customers", [_response([{"id": "c_201"}])], resume_state=AlgunaResumeConfig(offset=200))

        assert result.raised is None
        assert result.params("offset") == ["200"]

    def test_missing_data_key_raises_loudly(self) -> None:
        # A 200 body without "data" means the response shape changed — fail loud, not silently 0 rows.
        result = _driver().run("customers", [_response(None, drop_data=True)])

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestFanout:
    def test_credit_notes_fan_out_over_customers_and_paginate_child(self) -> None:
        cust1_full = [{"id": f"cn1_{i}", "customer_id": "cust_1"} for i in range(100)]
        result = _driver().run(
            "credit_notes",
            [
                _response([{"id": "cust_1"}, {"id": "cust_2"}]),  # parent: short page ends parent walk
                _response(cust1_full),  # cust_1 credit-notes page 1 (full → another page)
                _response([{"id": "cn1_last", "customer_id": "cust_1"}]),  # cust_1 page 2 (short)
                _response([{"id": "cn2_1", "customer_id": "cust_2"}]),  # cust_2 (short)
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(f"cn1_{i}" for i in range(100)), "cn1_last", "cn2_1"]
        assert result.paths[0] == "/customers"
        # Each customer's credit-notes are fetched with its id, and a full page advances the offset.
        child = [request for request in result.requests if request.path == "/credit-notes"]
        assert [request.param("customer_id") for request in child] == ["cust_1", "cust_1", "cust_2"]
        assert [request.param("offset") for request in child] == ["0", "100", "0"]

    def test_credit_notes_skips_parent_without_id(self) -> None:
        result = _driver().run(
            "credit_notes",
            [
                _response([{"name": "no-id"}, {"id": "cust_2"}]),
                _response([{"id": "cn2_1", "customer_id": "cust_2"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["cn2_1"]
        # The id-less parent yields no child request.
        assert [request.param("customer_id") for request in result.requests if request.path == "/credit-notes"] == [
            "cust_2"
        ]

    def test_subscription_versions_fan_out_omits_child_page_size(self) -> None:
        result = _driver().run(
            "subscription_versions",
            [
                _response([{"id": "sub_1"}, {"id": "sub_2"}]),  # parent subscriptions
                _response([{"id": "v_1", "subscription_id": "sub_1"}]),
                _response([{"id": "v_2", "subscription_id": "sub_2"}]),
            ],
        )

        assert result.raised is None
        assert {row["id"] for row in result.rows} == {"v_1", "v_2"}
        parent = next(request for request in result.requests if request.path == "/subscriptions")
        assert parent.param("limit") == "100"  # parent paginates with an explicit page size
        child = [request for request in result.requests if request.path.endswith("/versions")]
        assert {request.path.split("/subscriptions/")[1].split("/")[0] for request in child} == {"sub_1", "sub_2"}
        # The versions endpoint takes no page-size param; a leaked `limit` would be an undocumented param.
        assert all(request.param("limit") is None for request in child)

    def test_subscription_revenue_fans_out_and_ignores_subscription_without_revenue(self) -> None:
        result = _driver().run(
            "subscription_revenue",
            [
                _response([{"id": "sub_1"}, {"id": "sub_2"}, {"id": "sub_3"}]),
                ScriptedResponse(
                    json={
                        "subscription_id": "sub_1",
                        "mrr": "100.00",
                        "arr": "1200.00",
                        "acv": "1200.00",
                        "currency": "USD",
                        "recurring_revenue_status": "complete",
                    }
                ),
                ScriptedResponse(status=404, json={"error": "not found"}),
                ScriptedResponse(
                    json={
                        "subscription_id": "sub_3",
                        "mrr": "0",
                        "arr": "0",
                        "acv": "0",
                        "currency": "EUR",
                        "recurring_revenue_status": "unavailable",
                    }
                ),
            ],
        )

        assert result.raised is None
        # The single-object body is one row, not exploded into its keys.
        assert [(row["subscription_id"], row["mrr"]) for row in result.rows] == [("sub_1", "100.00"), ("sub_3", "0")]
        child = [request.path for request in result.requests if request.path.endswith("/revenue")]
        assert child == ["/subscriptions/sub_1/revenue", "/subscriptions/sub_2/revenue", "/subscriptions/sub_3/revenue"]
        assert all(request.param("limit") is None for request in result.requests if request.path.endswith("/revenue"))


class TestRevenueSchedule:
    def test_rows_are_entries_with_envelope_fields(self) -> None:
        body = {
            "currency": "USD",
            "interval": "monthly",
            "start_date": "2026-01-01T00:00:00Z",
            "end_date": "2026-03-01T00:00:00Z",
            "entries": [
                {
                    "start_date": "2026-01-01T00:00:00Z",
                    "end_date": "2026-02-01T00:00:00Z",
                    "new_recognized_revenue": "10.00",
                },
                {
                    "start_date": "2026-02-01T00:00:00Z",
                    "end_date": "2026-03-01T00:00:00Z",
                    "new_recognized_revenue": "20.00",
                },
            ],
        }
        result = _driver().run("revenue_schedule", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == [
            {
                "currency": "USD",
                "interval": "monthly",
                "start_date": "2026-01-01T00:00:00Z",
                "end_date": "2026-02-01T00:00:00Z",
                "new_recognized_revenue": "10.00",
            },
            {
                "currency": "USD",
                "interval": "monthly",
                "start_date": "2026-02-01T00:00:00Z",
                "end_date": "2026-03-01T00:00:00Z",
                "new_recognized_revenue": "20.00",
            },
        ]
        assert result.paths == ["/revenue-schedules"]
        assert result.params("interval") == ["monthly"]
        assert result.params("limit") == [None]

    def test_empty_entries_yield_no_rows(self) -> None:
        body = {"currency": "USD", "interval": "monthly", "entries": []}
        result = _driver().run("revenue_schedule", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == []

    @parameterized.expand(
        [
            ("missing_entries", {"currency": "USD", "interval": "monthly"}),
            ("entries_not_a_list", {"currency": "USD", "entries": {"start_date": "2026-01-01T00:00:00Z"}}),
            ("list_body", [{"start_date": "2026-01-01T00:00:00Z"}]),
        ]
    )
    def test_unexpected_shape_raises_loudly(self, _name: str, body: Any) -> None:
        result = _driver().run("revenue_schedule", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert "'entries'" in str(result.raised)


class TestLookupFanout:
    @parameterized.expand(
        [
            (
                "connected_accounts",
                "customer_connected_accounts",
                "/customers",
                "connected-accounts",
                {"data": [{"id": "cacc_1", "customer_id": "p_1", "external_id": "cus_1", "integration_id": "intg_1"}]},
                [{"id": "cacc_1", "customer_id": "p_1", "external_id": "cus_1", "integration_id": "intg_1"}],
            ),
            (
                # Entitlement rows carry no customer id; it is copied down from the parent row.
                "entitlements",
                "customer_entitlements",
                "/customers",
                "entitlements",
                {"data": [{"key": "api_access", "subscription_id": None, "type": "boolean", "value": "true"}]},
                [
                    {
                        "key": "api_access",
                        "subscription_id": None,
                        "type": "boolean",
                        "value": "true",
                        "customer_id": "p_1",
                    }
                ],
            ),
        ]
    )
    def test_fans_out_per_parent_and_skips_deleted_parent(
        self,
        _name: str,
        endpoint: str,
        parent_path: str,
        child_suffix: str,
        child_body: dict[str, Any],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                _response([{"id": "p_1"}, {"id": "p_gone"}]),
                ScriptedResponse(json=child_body),
                # A parent deleted between the parent listing and the child fetch.
                ScriptedResponse(status=404, json={"error": "not found"}),
            ],
        )

        assert result.raised is None
        assert result.rows == expected_rows
        assert result.paths == [
            parent_path,
            f"{parent_path}/p_1/{child_suffix}",
            f"{parent_path}/p_gone/{child_suffix}",
        ]
        child = [request for request in result.requests if request.path != parent_path]
        assert all(request.param("limit") is None for request in child)


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key") is True

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/customers"
