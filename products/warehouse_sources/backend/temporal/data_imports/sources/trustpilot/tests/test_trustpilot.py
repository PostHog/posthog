from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.settings import (
    MAX_PAGE_SIZE,
    TRUSTPILOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot import (
    BASE_URL,
    TrustpilotResumeConfig,
    TrustpilotUrlError,
    _require_api_url,
    _to_reply_row,
    check_credentials,
    get_rows,
    trustpilot_source,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.trustpilot.trustpilot"


class _FakeManager(ResumableSourceManager[TrustpilotResumeConfig]):
    """Minimal stand-in for ResumableSourceManager that records saved state in memory."""

    def __init__(self, state: TrustpilotResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[TrustpilotResumeConfig] = []
        self.cleared = 0

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> TrustpilotResumeConfig | None:
        return self._state

    def save_state(self, data: TrustpilotResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared += 1


def _response(body: Any, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body
    response.text = str(body)
    return response


class _FakeSession:
    """Returns queued responses in order and records the (url, params) of each GET."""

    def __init__(self, responses: list[MagicMock]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: int | None = None) -> MagicMock:
        self.requests.append((url, params))
        return self._responses.pop(0)


def _reviews_page(count: int, *, with_reply_every: int = 0) -> dict[str, Any]:
    reviews: list[dict[str, Any]] = []
    for index in range(count):
        review: dict[str, Any] = {"id": f"r{index}", "stars": 5, "createdAt": "2026-01-01T00:00:00Z"}
        if with_reply_every and index % with_reply_every == 0:
            review["companyReply"] = {"text": "thanks", "createdAt": "2026-01-02T00:00:00Z"}
        reviews.append(review)
    return {"reviews": reviews}


def _rows(session: _FakeSession, endpoint: str, manager: _FakeManager) -> list[list[dict[str, Any]]]:
    with patch(f"{MODULE}._make_session", return_value=session):
        return list(get_rows("key", "bu-1", endpoint, MagicMock(), manager))


class TestTrustpilotTransport:
    def test_single_endpoint_yields_the_object_and_clears_state(self) -> None:
        session = _FakeSession([_response({"id": "bu-1", "displayName": "Example"})])
        manager = _FakeManager()

        batches = _rows(session, "business_units", manager)

        assert batches == [[{"id": "bu-1", "displayName": "Example"}]]
        assert session.requests[0][0] == f"{BASE_URL}/business-units/bu-1"
        assert manager.cleared == 1

    def test_pagination_walks_until_a_short_page_and_checkpoints_each_full_page(self) -> None:
        # A full page means "there may be more"; a page shorter than perPage is the last one.
        session = _FakeSession([_response(_reviews_page(MAX_PAGE_SIZE)), _response(_reviews_page(1))])
        manager = _FakeManager()

        batches = _rows(session, "service_reviews", manager)

        assert [len(batch) for batch in batches] == [MAX_PAGE_SIZE, 1]
        assert [params["page"] for _url, params in session.requests] == [1, 2]
        assert [params["perPage"] for _url, params in session.requests] == [MAX_PAGE_SIZE, MAX_PAGE_SIZE]
        # Checkpoint only the page boundary we actually crossed, and only after emitting page 1.
        assert manager.saved == [TrustpilotResumeConfig(next_page=2)]
        assert manager.cleared == 1

    def test_a_single_short_page_makes_no_checkpoint(self) -> None:
        session = _FakeSession([_response(_reviews_page(2))])
        manager = _FakeManager()

        _rows(session, "service_reviews", manager)

        assert manager.saved == []
        assert session.requests[0][1]["page"] == 1

    def test_resume_starts_from_the_saved_page(self) -> None:
        session = _FakeSession([_response(_reviews_page(1))])
        manager = _FakeManager(state=TrustpilotResumeConfig(next_page=4))

        _rows(session, "service_reviews", manager)

        assert session.requests[0][1]["page"] == 4

    def test_review_replies_lifts_company_replies_and_skips_reviews_without_one(self) -> None:
        # 4 reviews, every 2nd carries a reply → 2 reply rows, keyed on the review they answer.
        session = _FakeSession([_response(_reviews_page(4, with_reply_every=2))])
        manager = _FakeManager()

        batches = _rows(session, "review_replies", manager)

        assert session.requests[0][0] == f"{BASE_URL}/business-units/bu-1/reviews"
        assert batches == [
            [
                {
                    "review_id": "r0",
                    "business_unit_id": "bu-1",
                    "text": "thanks",
                    "createdAt": "2026-01-02T00:00:00Z",
                    "updatedAt": None,
                },
                {
                    "review_id": "r2",
                    "business_unit_id": "bu-1",
                    "text": "thanks",
                    "createdAt": "2026-01-02T00:00:00Z",
                    "updatedAt": None,
                },
            ]
        ]

    def test_product_reviews_read_from_their_own_wrapper_key(self) -> None:
        # The product-reviews endpoint wraps rows under `productReviews`, not `reviews`.
        session = _FakeSession([_response({"productReviews": [{"id": "p1"}]})])
        manager = _FakeManager()

        batches = _rows(session, "product_reviews", manager)

        assert session.requests[0][0] == f"{BASE_URL}/product-reviews/business-units/bu-1"
        assert batches == [[{"id": "p1"}]]

    @parameterized.expand(
        [
            ("no_reply", {"id": "r1"}, None),
            ("reply_but_no_id", {"companyReply": {"text": "hi"}}, None),
            ("non_dict_reply", {"id": "r1", "companyReply": "oops"}, None),
        ]
    )
    def test_to_reply_row_returns_none_when_there_is_no_usable_reply(
        self, _name: str, review: dict[str, Any], expected: Any
    ) -> None:
        assert _to_reply_row(review, "bu-1") is expected

    @parameterized.expand(
        [
            ("http", "http://api.trustpilot.com/v1/business-units/x"),
            ("other_host", "https://evil.example.com/v1/business-units/x"),
            ("subdomain_spoof", "https://api.trustpilot.com.evil.com/x"),
        ]
    )
    def test_require_api_url_rejects_non_trustpilot_targets(self, _name: str, url: str) -> None:
        with pytest.raises(TrustpilotUrlError):
            _require_api_url(url)

    def test_require_api_url_allows_the_trustpilot_origin(self) -> None:
        assert _require_api_url(f"{BASE_URL}/business-units/x") == f"{BASE_URL}/business-units/x"

    def test_check_credentials_returns_none_status_when_the_request_fails(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")

        with patch(f"{MODULE}._make_session", return_value=session):
            status, message = check_credentials("key", "bu-1")

        assert status is None
        assert message is None

    def test_check_credentials_returns_the_status_code(self) -> None:
        session = _FakeSession([_response({"id": "bu-1"}, status_code=200)])

        with patch(f"{MODULE}._make_session", return_value=session):
            status, _message = check_credentials("key", "bu-1")

        assert status == 200

    @parameterized.expand(list(TRUSTPILOT_ENDPOINTS))
    def test_source_response_carries_each_endpoints_keys_and_partitioning(self, endpoint: str) -> None:
        config = TRUSTPILOT_ENDPOINTS[endpoint]
        response = trustpilot_source("key", "bu-1", endpoint, MagicMock(), _FakeManager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
