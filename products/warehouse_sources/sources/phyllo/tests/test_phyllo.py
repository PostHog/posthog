from datetime import UTC, datetime
from typing import Any

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.phyllo import PhylloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.phyllo import (
    PAGE_SIZE,
    PhylloResumeConfig,
    get_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.settings import ENDPOINTS, PHYLLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.phyllo.source import PhylloSource


def _driver() -> SourceDriver:
    return SourceDriver(
        PhylloSource(), PhylloSourceConfig(client_id="cid", client_secret="cs-secret", environment="production")
    )


def _response(items: list[dict[str, Any]] | None, *, drop_data: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {"metadata": {"limit": PAGE_SIZE}}
    if not drop_data:
        body["data"] = items if items is not None else []
    return ScriptedResponse(json=body)


class TestTopLevelPagination:
    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "users",
            [_response([{"id": "z"}])],
            resume_state=PhylloResumeConfig(paginator_state={"offset": PAGE_SIZE}),
        )

        assert result.raised is None
        assert result.rows == [{"id": "z"}]
        # Offset 0 must never be fetched on resume.
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestFanOut:
    def test_disconnected_bookmarked_account_does_not_leak_offset(self) -> None:
        # The bookmarked account was disconnected between runs; the saved offset must not leak into
        # the remaining account's pagination.
        result = _driver().run(
            "social_contents",
            route(
                {
                    "/v1/accounts": [_response([{"id": "acc_a"}, {"id": "acc_c"}])],
                    "/v1/social/contents": [_response([{"id": "a1"}]), _response([{"id": "c1"}])],
                }
            ),
            resume_state=PhylloResumeConfig(
                paginator_state={
                    "completed": [],
                    "current": "/v1/social/contents?account_id=acc_b",
                    "child_state": {"offset": PAGE_SIZE},
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "a1"}, {"id": "c1"}]
        child_requests = [request for request in result.requests if request.path == "/v1/social/contents"]
        assert [request.param("account_id") for request in child_requests] == ["acc_a", "acc_c"]
        assert [request.param("offset") for request in child_requests] == ["0", "0"]

    def test_comments_bind_account_and_content_ids(self) -> None:
        result = _driver().run(
            "social_comments",
            route(
                {
                    "/v1/accounts": [_response([{"id": "acc_a"}, {"id": "acc_b"}])],
                    "/v1/social/contents": [
                        _response([{"id": "con_1"}, {"id": "con_2"}]),
                        _response([{"id": "con_3"}]),
                    ],
                    "/v1/social/comments": [
                        _response([{"id": "cm_1"}]),
                        _response([]),
                        _response([{"id": "cm_3"}]),
                    ],
                }
            ),
        )

        assert result.raised is None
        # The account id carried onto each content row to bind the request must not leak into rows.
        assert result.rows == [{"id": "cm_1"}, {"id": "cm_3"}]
        comment_requests = [request for request in result.requests if request.path == "/v1/social/comments"]
        assert [(request.param("account_id"), request.param("content_id")) for request in comment_requests] == [
            ("acc_a", "con_1"),
            ("acc_a", "con_2"),
            ("acc_b", "con_3"),
        ]

    def test_audience_yields_one_row_per_account(self) -> None:
        result = _driver().run(
            "audience",
            route(
                {
                    "/v1/accounts": [_response([{"id": "acc_a"}, {"id": "acc_b"}])],
                    "/v1/audience": [
                        ScriptedResponse(json={"id": "aud_a", "countries": [{"code": "US", "value": 60.5}]}),
                        ScriptedResponse(json={"id": "aud_b", "countries": []}),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["aud_a", "aud_b"]
        audience_requests = [request for request in result.requests if request.path == "/v1/audience"]
        assert [request.param("account_id") for request in audience_requests] == ["acc_a", "acc_b"]


class TestCommerceTransactionDateWindow:
    def test_window_covers_full_history(self) -> None:
        with time_machine.travel(datetime(2026, 3, 15, 12, 0, tzinfo=UTC), tick=False):
            result = _driver().run(
                "commerce_income_transactions",
                route(
                    {
                        "/v1/accounts": [_response([{"id": "acc_a"}])],
                        "/v1/commerce/income/transactions": [_response([{"id": "txn_1"}])],
                    }
                ),
            )

        assert result.raised is None
        assert result.rows == [{"id": "txn_1"}]
        [request] = [r for r in result.requests if r.path == "/v1/commerce/income/transactions"]
        assert request.param("account_id") == "acc_a"
        assert request.param("transaction_from_date") == "2000-01-01"
        assert request.param("transaction_to_date") == "2026-03-15"


class TestMalformedBody:
    def test_top_level_persistent_malformed_body_reraises(self) -> None:
        result = _driver().run("users", always(_response(None, drop_data=True)))

        assert isinstance(result.raised, RESTClientRetryableError)

    def test_fan_out_child_malformed_body_fails_loud(self) -> None:
        # Dependent resources can't classify a malformed body as retryable, so the child fails loud
        # rather than silently syncing 0 rows.
        result = _driver().run(
            "social_contents",
            route(
                {
                    "/v1/accounts": [_response([{"id": "acc_a"}])],
                    "/v1/social/contents": [_response(None, drop_data=True)],
                }
            ),
        )

        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
        ]
    )
    def test_status_mapping(
        self,
        _name: str,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status))) as network:
            assert validate_credentials("cid", "cs-secret", "production") == (expected_valid, expected_message)

        assert network.requests_log[0].path == "/v1/work-platforms"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].param("offset") == "0"


class TestPhylloSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Phyllo doesn't guarantee ordering or a stable creation timestamp, so we don't partition.
        assert result.response.partition_mode is None
        # The two-level comments fan-out has no framework checkpoint, so it must not claim resume.
        assert result.response.supports_resume is (endpoint != "social_comments")
        assert PhylloSource().resume_covers_run(incremental_or_append=False, schema_name=endpoint) is (
            endpoint != "social_comments"
        )

    def test_fan_out_endpoints_are_account_scoped(self) -> None:
        # These endpoints require an account_id query param; a config regression here would 400 on
        # every page.
        fan_out = {name for name, config in PHYLLO_ENDPOINTS.items() if config.fan_out_by_account}
        assert fan_out == {
            "social_contents",
            "income_transactions",
            "income_payouts",
            "audience",
            "social_comments",
            "social_content_groups",
            "commerce_income_transactions",
        }

    @parameterized.expand(
        [("production", "https://api.getphyllo.com"), ("sandbox", "https://api.sandbox.getphyllo.com")]
    )
    def test_get_base_url(self, environment: str, expected: str) -> None:
        assert get_base_url(environment) == expected
