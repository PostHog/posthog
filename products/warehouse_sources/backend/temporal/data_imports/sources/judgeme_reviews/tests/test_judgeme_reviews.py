import json
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.judgeme_reviews import (
    FORBIDDEN_MESSAGE,
    INVALID_CREDENTIALS_MESSAGE,
    PAGE_SIZE,
    JudgeMeReviewsResumeConfig,
    _normalize_shop_domain,
    judgeme_reviews_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.settings import (
    ENDPOINTS,
    JUDGEME_REVIEWS_ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the judgeme_reviews module.
JUDGEME_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.judgeme_reviews.judgeme_reviews.make_tracked_session"


def _response(
    items: list[dict[str, Any]] | None,
    *,
    list_key: str = "reviews",
    page: int = 1,
    drop_key: bool = False,
    body: Any = None,
) -> Response:
    if body is None:
        payload: Any = {"current_page": page, "per_page": PAGE_SIZE}
        if not drop_key:
            payload[list_key] = items or []  # ty: ignore[invalid-assignment]
        body = payload
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _error_response(status_code: int) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = b"{}"
    resp.url = "https://judge.me/api/v1/reviews?shop_domain=example.myshopify.com&page=1"
    return resp


def _make_manager(resume_state: JudgeMeReviewsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session; return a list capturing each request's params AT SEND TIME.

    ``request.params`` is one dict mutated in place across pages, so snapshot a copy per request.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _source(endpoint: str, manager: mock.MagicMock):
    return judgeme_reviews_source(
        api_token="jm-token",
        shop_domain="example.myshopify.com",
        endpoint=endpoint,
        team_id=1,
        job_id="j",
        resumable_source_manager=manager,
    )


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_empty_page(self, MockSession) -> None:
        # There is no has_more flag, so a full page must still be followed by another fetch.
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], page=1), _response([{"id": 2}], page=2), _response([], page=3)])

        rows = _rows(_source("reviews", _make_manager()))

        assert rows == [{"id": 1}, {"id": 2}]
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == PAGE_SIZE
        assert params[0]["shop_domain"] == "example.myshopify.com"
        assert params[1]["page"] == 2
        assert params[2]["page"] == 3

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing_and_saves_no_state(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([], page=1)])

        manager = _make_manager()
        rows = _rows(_source("reviews", manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_yielding_each_batch(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_response([{"id": 1}], page=1), _response([], page=2)])

        manager = _make_manager()
        _rows(_source("reviews", manager))

        # State is saved AFTER page 1 is yielded (pointing at page 2), never before; the empty
        # page 2 that ends the sync saves nothing.
        assert [c.args[0].next_page for c in manager.save_state.call_args_list] == [2]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession) -> None:
        session = MockSession.return_value
        # Page 1 must never be fetched on resume.
        params = _wire(session, [_response([{"id": 2}], page=2), _response([], page=3)])

        rows = _rows(_source("reviews", _make_manager(JudgeMeReviewsResumeConfig(next_page=2))))

        assert rows == [{"id": 2}]
        assert params[0]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_uses_endpoint_specific_list_key(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [_response([{"id": 7}], list_key="products", page=1), _response([], list_key="products", page=2)],
        )

        rows = _rows(_source("products", _make_manager()))
        assert rows == [{"id": 7}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_header_is_set_and_not_in_params(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([{"id": 1}], page=1), _response([], page=2)])

        _rows(_source("reviews", _make_manager()))
        # The private token rides the X-Api-Token header (via framework auth), never the query string.
        assert "api_token" not in params[0]
        assert "X-Api-Token" not in params[0]


class TestMalformedBody:
    @parameterized.expand(
        [
            ("missing_list_key", {"current_page": 1, "per_page": PAGE_SIZE}),
            ("bare_array", [{"id": 1}]),
            ("non_list_value", {"reviews": {"id": 1}}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_malformed_body_is_retried_then_exhausts(self, _name: str, body: Any, MockSession) -> None:
        # A 200 whose body isn't the expected `{"reviews": [...]}` envelope is treated as transient:
        # the client reissues it (default 5 attempts) rather than failing loud or ingesting garbage.
        session = MockSession.return_value
        _wire(session, [_response(None, body=body) for _ in range(5)])

        with pytest.raises(Exception, match="Unexpected 200 response body shape"):
            _rows(_source("reviews", _make_manager()))
        assert session.send.call_count == 5

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_envelope_is_valid_not_malformed(self, MockSession) -> None:
        # `{"reviews": []}` is a legitimate zero-row page, not a malformed body — one request, no retry.
        session = MockSession.return_value
        _wire(session, [_response([], page=1)])

        rows = _rows(_source("reviews", _make_manager()))
        assert rows == []
        assert session.send.call_count == 1


class TestRetryableStatuses:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_retryable_statuses_are_reissued(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status) for _ in range(5)])

        with pytest.raises(Exception):
            _rows(_source("reviews", _make_manager()))
        # 429/5xx are retried up to the client's attempt cap rather than surfacing on the first hit.
        assert session.send.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_client_errors_fail_immediately(self, _name: str, status: int, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_error_response(status)])

        with pytest.raises(Exception):
            _rows(_source("reviews", _make_manager()))
        # A 4xx (bad credentials, missing scope, unknown path) is permanent — no retry.
        assert session.send.call_count == 1


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

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_normalized_domain_is_sent_as_param(self, MockSession) -> None:
        session = MockSession.return_value
        params = _wire(session, [_response([], page=1)])

        _rows(
            judgeme_reviews_source(
                api_token="jm-token",
                shop_domain="https://example.myshopify.com/",
                endpoint="reviews",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        )
        assert params[0]["shop_domain"] == "example.myshopify.com"


class TestValidateCredentials:
    def _patch_session(self, status: int | None) -> Any:
        session = mock.MagicMock()
        if status is None:
            session.get.side_effect = Exception("boom")
        else:
            session.get.return_value = mock.MagicMock(status_code=status)
        return mock.patch(JUDGEME_SESSION_PATCH, return_value=session)

    @parameterized.expand(
        [
            ("valid", 200, (True, None)),
            ("unauthorized", 401, (False, INVALID_CREDENTIALS_MESSAGE)),
            ("forbidden", 403, (False, FORBIDDEN_MESSAGE)),
            ("server_error", 500, (False, "Judge.me returned HTTP 500")),
            ("connection_error", None, (False, "Could not connect to Judge.me to validate your credentials")),
        ]
    )
    def test_status_mapping(self, _name: str, status: int | None, expected: tuple[bool, str | None]) -> None:
        with self._patch_session(status):
            assert validate_credentials("jm-token", "example.myshopify.com") == expected

    def test_probe_targets_count_endpoint_with_shop_domain(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(JUDGEME_SESSION_PATCH, return_value=session):
            validate_credentials("jm-token", "https://example.myshopify.com/")
        url = session.get.call_args.args[0]
        assert url == "https://judge.me/api/v1/reviews/count?shop_domain=example.myshopify.com"
        assert session.get.call_args.kwargs["headers"]["X-Api-Token"] == "jm-token"


class TestJudgeMeReviewsSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _source(endpoint, _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Response ordering is undocumented and syncs are full refresh, so we don't partition.
        assert response.partition_mode is None

    def test_every_endpoint_uses_id_primary_key(self) -> None:
        assert all(config.primary_keys == ["id"] for config in JUDGEME_REVIEWS_ENDPOINTS.values())
        assert set(JUDGEME_REVIEWS_ENDPOINTS) == set(ENDPOINTS)
