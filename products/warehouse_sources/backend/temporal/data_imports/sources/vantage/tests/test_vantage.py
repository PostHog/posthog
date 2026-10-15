from typing import Any, Optional

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vantage import (
    VantageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source import VantageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.vantage import (
    VANTAGE_BASE_URL,
    VantageResumeConfig,
    VantageUntrustedURLError,
    validate_credentials,
)


def _response(
    items: Optional[list[dict[str, Any]]],
    *,
    data_key: str = "cost_reports",
    next_url: Optional[str] = None,
    include_links: bool = True,
    status_code: int = 200,
) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if items is not None:
        body[data_key] = items
    if include_links:
        body["links"] = {"next": next_url}
    return ScriptedResponse(status=status_code, json=body)


def _run(script: Script, endpoint: str = "cost_reports", **kwargs: Any) -> DriveResult:
    driver = SourceDriver(VantageSource(), VantageSourceConfig(api_key="tok"))
    return driver.run(endpoint, script, **kwargs)


class TestPagination:
    def test_follows_links_next_and_terminates(self) -> None:
        # Regression guard: not advancing the URL loops forever; not terminating on a null `next`
        # over-fetches. Rows must come back across every page, in order.
        p2 = f"{VANTAGE_BASE_URL}/cost_reports?page=2&limit=1000"
        result = _run(
            [
                _response([{"token": "a"}, {"token": "b"}], next_url=p2),
                _response([{"token": "c"}], next_url=None),
            ]
        )

        assert result.rows == [{"token": "a"}, {"token": "b"}, {"token": "c"}]
        assert len(result.requests) == 2
        assert result.params("limit")[0] == "1000"
        assert result.urls[1] == p2  # second request follows the body's `links.next` verbatim

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run([_response([{"token": "a"}], next_url=None)])

        assert result.queries == [{"limit": ("1000",)}]


class TestResume:
    def test_resumes_from_saved_url(self) -> None:
        # Resuming starts from the saved next-page URL verbatim, not page 1.
        resume_url = f"{VANTAGE_BASE_URL}/cost_reports?page=5&limit=1000"

        result = _run(
            [_response([{"token": "z"}], next_url=None)],
            resume_state=VantageResumeConfig(next_url=resume_url),
        )

        assert result.rows == [{"token": "z"}]
        assert result.urls[0] == resume_url
        # The self-contained resume URL carries its own page/limit.
        assert result.queries[0] == {"page": ("5",), "limit": ("1000",)}


class TestUntrustedUrl:
    @parameterized.expand(
        [
            ("off_host", "https://evil.example.com/v2/cost_reports"),
            ("subdomain_lookalike", "https://api.vantage.sh.evil.example.com/v2/cost_reports"),
            ("plain_http", "http://api.vantage.sh/v2/cost_reports"),
            ("wrong_path_prefix", "https://api.vantage.sh/internal/cost_reports"),
        ]
    )
    def test_untrusted_next_url_is_refused_without_sending_token(self, _name: str, bad_url: str) -> None:
        # `links.next` is server-controlled; the bearer token must never leave Vantage's own HTTPS
        # host and `/v2/` path, so an off-host/non-HTTPS/wrong-path next link is refused before the
        # request that would carry the token to it goes out.
        result = _run([_response([{"token": "a"}], next_url=bad_url)])

        assert isinstance(result.raised, VantageUntrustedURLError)
        assert len(result.requests) == 1  # only the trusted first page was fetched

    def test_untrusted_resume_url_is_refused_before_any_request(self) -> None:
        result = _run(
            [_response([{"token": "a"}], next_url=None)],
            resume_state=VantageResumeConfig(next_url="https://evil.example.com/v2/cost_reports"),
        )

        assert isinstance(result.raised, VantageUntrustedURLError)
        assert result.requests == []


class TestRetries:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 502)])
    def test_retryable_status_is_retried(self, _name: str, status: int) -> None:
        result = _run(
            [
                _response(None, include_links=False, status_code=status),
                _response([{"token": "a"}], next_url=None),
            ]
        )

        assert result.rows == [{"token": "a"}]
        assert len(result.requests) == 2

    def test_client_error_is_raised_not_retried(self) -> None:
        # A 4xx (other than 429) is a permanent client error — raise immediately so
        # get_non_retryable_errors can classify it, rather than burning retries.
        result = _run([_response(None, include_links=False, status_code=404)])

        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    def test_status_maps_to_validity(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            assert validate_credentials("tok") is expected

        assert network.requests_log[0].url == f"{VANTAGE_BASE_URL}/ping"
        assert network.requests_log[0].headers["authorization"] == "Bearer tok"


class TestSourceResponse:
    @parameterized.expand([("cost_reports", "created_at"), ("workspaces", "created_at")])
    def test_datetime_partitioning_on_created_at(self, endpoint: str, partition_key: str) -> None:
        response = _run([_response(None, next_url=None)], endpoint=endpoint).response

        assert response is not None
        assert response.primary_keys == ["token"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]

    @parameterized.expand([("teams",), ("users",), ("report_notifications",)])
    def test_no_partitioning_when_no_stable_created_at(self, endpoint: str) -> None:
        # These objects carry no creation timestamp; partitioning on a missing field would break sync.
        response = _run([_response(None, next_url=None)], endpoint=endpoint).response

        assert response is not None
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.primary_keys == ["token"]
