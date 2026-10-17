from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna import (
    AlgunaResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.source import AlgunaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alguna import AlgunaSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(AlgunaSource(), AlgunaSourceConfig(api_key="key"))


def _response(items: list[dict[str, Any]] | None, *, drop_data: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {"pagination": {"per_page": 100}}
    if not drop_data:
        body["data"] = items or []
    return ScriptedResponse(json=body)


class TestPagination:
    def test_paginates_and_progresses_offset(self) -> None:
        full_page = [{"id": f"c_{i}"} for i in range(100)]
        result = _driver().run("customers", [_response(full_page), _response([{"id": "c_last"}])])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [*(f"c_{i}" for i in range(100)), "c_last"]
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
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


class TestValidateCredentials:
    def test_ok(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key") is True

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/customers"
