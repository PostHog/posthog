from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.judgemereviews import (
    JudgeMeReviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.judgeme_reviews import (
    PAGE_SIZE,
    JudgeMeReviewsResumeConfig,
    _normalize_shop_domain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import (
    ENDPOINTS,
    JUDGEME_REVIEWS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.source import JudgeMeReviewsSource


def _driver() -> SourceDriver:
    return SourceDriver(
        JudgeMeReviewsSource(),
        JudgeMeReviewsSourceConfig(shop_domain="example.myshopify.com", api_token="jm-token"),
    )


def _response(
    items: list[dict[str, Any]] | None,
    *,
    list_key: str = "reviews",
    page: int = 1,
    body: Any = None,
) -> ScriptedResponse:
    if body is None:
        payload: Any = {"current_page": page, "per_page": PAGE_SIZE, list_key: items or []}
        body = payload
    return ScriptedResponse(json=body)


class TestPagination:
    def test_resumes_from_saved_page(self) -> None:
        # Page 1 must never be fetched on resume.
        result = _driver().run(
            "reviews",
            [_response([{"id": 2}], page=2), _response([], page=3)],
            resume_state=JudgeMeReviewsResumeConfig(next_page=2),
        )

        assert result.raised is None
        assert result.rows == [{"id": 2}]
        assert result.params("page") == ["2", "3"]
        assert result.params("per_page") == [str(PAGE_SIZE), str(PAGE_SIZE)]
        assert result.params("shop_domain") == ["example.myshopify.com"] * 2


class TestMalformedBody:
    @parameterized.expand(
        [
            ("missing_list_key", {"current_page": 1, "per_page": PAGE_SIZE}),
            ("bare_array", [{"id": 1}]),
            ("non_list_value", {"reviews": {"id": 1}}),
        ]
    )
    def test_malformed_body_is_retried_then_exhausts(self, _name: str, body: Any) -> None:
        # A 200 whose body isn't the expected `{"reviews": [...]}` envelope is treated as transient:
        # the client reissues it (default 5 attempts) rather than failing loud or ingesting garbage.
        result = _driver().run("reviews", [_response(None, body=body) for _ in range(5)])

        assert isinstance(result.raised, Exception)
        assert "Unexpected 200 response body shape" in str(result.raised)
        assert result.rows == []
        assert result.paths == ["/api/v1/reviews"] * 5


class TestRetryableStatuses:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_are_reissued(self, _name: str, status: int) -> None:
        result = _driver().run("reviews", always(ScriptedResponse(status=status, json={})))

        assert isinstance(result.raised, Exception)
        # 429/5xx are retried up to the client's attempt cap rather than surfacing on the first hit.
        assert len(result.requests) > 1
        assert set(result.paths) == {"/api/v1/reviews"}

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_immediately(self, _name: str, status: int) -> None:
        result = _driver().run("reviews", [ScriptedResponse(status=status, json={})])

        assert isinstance(result.raised, Exception)
        # A 4xx (bad credentials, missing scope, unknown path) is permanent — no retry.
        assert result.paths == ["/api/v1/reviews"]


class TestNormalizeShopDomain:
    @parameterized.expand(
        [
            ("bare", "example.myshopify.com", "example.myshopify.com"),
            ("https", "https://example.myshopify.com", "example.myshopify.com"),
            ("http", "http://example.myshopify.com", "example.myshopify.com"),
            ("trailing_slash", "https://example.myshopify.com/", "example.myshopify.com"),
            ("whitespace", "  example.myshopify.com ", "example.myshopify.com"),
        ]
    )
    def test_normalization(self, _name: str, raw: str, expected: str) -> None:
        assert _normalize_shop_domain(raw) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("connection_error", None, (False, "Could not connect to Judge.me to validate your credentials")),
        ]
    )
    def test_status_mapping(self, _name: str, status: int | None, expected: tuple[bool, str | None]) -> None:
        answer = ConnectionError("boom") if status is None else ScriptedResponse(status=status)
        with scripted_network(always(answer)) as network:
            assert validate_credentials("jm-token", "example.myshopify.com") == expected

        assert {request.path for request in network.requests_log} == {"/api/v1/reviews/count"}
        assert {request.param("shop_domain") for request in network.requests_log} == {"example.myshopify.com"}
        assert all(request.headers["x-api-token"] == "jm-token" for request in network.requests_log)


class TestJudgeMeReviewsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_response([], list_key=endpoint)])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Response ordering is undocumented and syncs are full refresh, so we don't partition.
        assert result.response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in JUDGEME_REVIEWS_ENDPOINTS.values())
        assert set(JUDGEME_REVIEWS_ENDPOINTS) == set(ENDPOINTS)
