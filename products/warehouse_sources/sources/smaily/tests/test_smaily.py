from typing import Any

import pytest

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smaily import SmailySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.settings import (
    CAMPAIGN_STATISTICS,
    ENDPOINTS,
    SEGMENT_SUBSCRIBERS,
    SMAILY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.smaily import (
    SmailyResumeConfig,
    SmailyRetryableError,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smaily.source import SmailySource

BASE_PATH = "/api"


def _run(endpoint: str, script: Script, **inputs: Any) -> DriveResult:
    config = SmailySourceConfig(subdomain="acme", username="user", password="pass")
    return SourceDriver(SmailySource(), config).run(endpoint, script, **inputs)


def _json(body: Any, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body)


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare", "acme", "acme"),
            ("uppercase_and_whitespace", "  ACME ", "acme"),
            ("full_domain", "acme.sendsmaily.net", "acme"),
            ("full_url_with_path", "https://acme.sendsmaily.net/api/", "acme"),
            ("hyphenated", "my-company", "my-company"),
        ]
    )
    def test_valid_inputs(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("other_domain", "evil.com"),
            ("smuggled_credentials", "acme.sendsmaily.net@evil.com"),
            ("leading_hyphen", "-acme"),
        ]
    )
    def test_invalid_inputs_are_rejected(self, _name: str, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_subdomain(raw)


class TestFetch:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_raise_retryable_error(self, _name: str, status: int) -> None:
        result = _run("campaigns", always(_json([], status)))

        assert isinstance(result.raised, SmailyRetryableError)

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _run("campaigns", [_json([], status)])

        assert isinstance(result.raised, requests.HTTPError)

    def test_non_json_body_is_retryable(self) -> None:
        # Smaily serves JSON with a text/html Content-Type; an HTML error page must not crash the sync.
        result = _run("campaigns", always(ScriptedResponse(body=b"<html>oops</html>")))

        assert isinstance(result.raised, SmailyRetryableError)

    @parameterized.expand([("dict_body", {"error": "nope"}), ("non_dict_rows", ["oops"])])
    def test_unexpected_list_shape_is_retryable_inside_fetch(self, _name: str, body: Any) -> None:
        # Shape validation must run inside the retried function so a malformed payload gets
        # backoff instead of failing the sync on the first hit.
        result = _run("campaigns", always(_json(body)))

        assert isinstance(result.raised, SmailyRetryableError)
        assert len(result.requests) > 1


class TestTopLevelEndpoints:
    def test_pages_until_short_page(self) -> None:
        page_size = SMAILY_ENDPOINTS["campaigns"].page_size
        assert page_size is not None
        pages = {
            "0": [{"id": i} for i in range(page_size)],
            "1": [{"id": page_size}],
        }

        result = _run("campaigns", lambda request: _json(pages[request.param("page") or ""]))

        assert len(result.rows) == page_size + 1
        # State is saved after the first full page so a retry skips straight to page 1.
        assert [s.page for s in result.saved_states] == [1]

    def test_unpaginated_endpoint_fetches_once_without_page_params(self) -> None:
        result = _run("segments", [_json([{"id": 4, "name": "Women"}])])

        assert result.rows == [{"id": 4, "name": "Women"}]
        assert result.paths == [f"{BASE_PATH}/list.php"]
        assert result.queries == [{}]
        assert result.saved_states == []


class TestSegmentSubscribers:
    @staticmethod
    def _responder(subscribers_by_segment: dict[str, list[list[dict] | None]]) -> Any:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/list.php"):
                return _json([{"id": segment_id} for segment_id in subscribers_by_segment])
            return _json(subscribers_by_segment[request.param("list") or ""][int(request.param("offset") or 0)])

        return respond

    def test_paginates_within_segment_and_saves_state_after_yield(self) -> None:
        page_size = SMAILY_ENDPOINTS[SEGMENT_SUBSCRIBERS].page_size
        assert page_size is not None
        responder = self._responder(
            {
                "1": [
                    [{"email": f"user{i}@x.com"} for i in range(page_size)],
                    [{"email": "last@x.com"}],
                ],
            }
        )
        result = _run(SEGMENT_SUBSCRIBERS, responder)

        assert len(result.rows) == page_size + 1
        # First save: next page of segment 1; second save: segment 1 finished, queue empty.
        assert [(s.page, s.pending_parent_ids) for s in result.saved_states] == [(1, ["1"]), (0, [])]

    def test_resumes_mid_segment_without_refetching_segment_list(self) -> None:
        responder = self._responder(
            {
                "5": [None, None, [{"email": "resumed@x.com"}]],  # only page 2 is ever requested
                "6": [[{"email": "next@x.com"}]],
            }
        )
        result = _run(
            SEGMENT_SUBSCRIBERS,
            responder,
            resume_state=SmailyResumeConfig(page=2, pending_parent_ids=["5", "6"]),
        )

        assert [row["email"] for row in result.rows] == ["resumed@x.com", "next@x.com"]
        # The segment list must not be re-fetched on resume — ids come from the saved queue.
        assert all(not path.endswith("/list.php") for path in result.paths)
        assert result.queries[0] == {"list": ("5",), "limit": ("25000",), "offset": ("2",)}


class TestCampaignStatistics:
    @staticmethod
    def _responder(stats_by_id: dict[str, Any]) -> Any:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            campaign_id = request.param("id")
            if campaign_id is not None:
                return _json(stats_by_id[campaign_id])
            return _json([{"id": int(campaign_id)} for campaign_id in stats_by_id])

        return respond

    def test_resume_skips_already_processed_campaigns(self) -> None:
        responder = self._responder({"3": {"id": 3, "delivered_count": 30}})
        result = _run(CAMPAIGN_STATISTICS, responder, resume_state=SmailyResumeConfig(page=0, pending_parent_ids=["3"]))

        assert result.rows == [{"id": 3, "delivered_count": 30}]
        # The campaign listing must not be re-fetched on resume.
        assert result.paths == [f"{BASE_PATH}/campaign.php"]
        assert result.queries == [{"id": ("3",)}]

    def test_unusable_stats_payload_yields_id_only_row(self) -> None:
        # A campaign whose stats come back malformed (e.g. an empty list) must not silently
        # vanish from the table — it keeps a row with a numeric id and null stats columns.
        responder = self._responder({"1": [], "2": {"id": 2, "delivered_count": 20}})
        result = _run(CAMPAIGN_STATISTICS, responder)

        assert result.rows == [{"id": 1}, {"id": 2, "delivered_count": 20}]


class TestCheckAccess:
    def test_invalid_subdomain_fails_without_a_request(self) -> None:
        valid, message = validate_credentials("evil.com/path?x=", "user", "pass")
        assert valid is False
        assert message is not None and "subdomain" in message.lower()


class TestSmailySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run(endpoint, always(_json([]))).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == SMAILY_ENDPOINTS[endpoint].primary_keys

    def test_segment_subscribers_key_includes_parent_segment(self) -> None:
        # `email` alone is only unique within one segment; dropping the parent id from the key
        # would multi-match merges for subscribers in several segments.
        assert SMAILY_ENDPOINTS[SEGMENT_SUBSCRIBERS].primary_keys == ["segment_id", "email"]
