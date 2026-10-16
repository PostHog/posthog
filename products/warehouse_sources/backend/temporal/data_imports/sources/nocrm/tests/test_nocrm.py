from datetime import UTC, date, datetime

import pytest

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nocrm import NoCRMSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.nocrm import (
    PAGE_SIZE,
    NoCRMConfigError,
    NoCRMResumeConfig,
    _base_url,
    _build_base_params,
    _clamp_future_value_to_now,
    _format_updated_after,
    normalize_subdomain,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.settings import NOCRM_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.nocrm.source import NoCRMSource


class TestNormalizeSubdomain:
    @parameterized.expand(
        [
            ("bare_label", "acme", "acme"),
            ("uppercase", "ACME", "acme"),
            ("whitespace", "  acme  ", "acme"),
            ("full_host", "acme.nocrm.io", "acme"),
            ("full_url", "https://acme.nocrm.io/", "acme"),
            ("url_with_path", "https://acme.nocrm.io/api/v2/leads", "acme"),
            ("hyphenated", "acme-sales", "acme-sales"),
            # A stray path segment is truncated to the leading label rather than reaching the host.
            ("path_truncated", "acme/evil", "acme"),
        ]
    )
    def test_valid_subdomains_reduce_to_label(self, _name: str, value: str, expected: str) -> None:
        assert normalize_subdomain(value) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("dot_breakout", "acme.evil"),
            ("at_breakout", "evil@acme"),
            ("leading_hyphen", "-acme"),
            ("underscore", "acme_sales"),
            ("space_inside", "acme corp"),
        ]
    )
    def test_invalid_subdomains_raise(self, _name: str, value: str) -> None:
        with pytest.raises(NoCRMConfigError):
            normalize_subdomain(value)

    def test_base_url_is_pinned_to_nocrm_origin(self) -> None:
        # Only the subdomain label is user-controlled; the origin is always *.nocrm.io.
        assert _base_url("acme") == "https://acme.nocrm.io/api/v2"
        assert _base_url("https://acme.nocrm.io") == "https://acme.nocrm.io/api/v2"


class TestFormatUpdatedAfter:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("string_passthrough", "2026-03-04T02:58:14Z", "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: object, expected: str) -> None:
        assert _format_updated_after(value) == expected


class TestClampFutureValueToNow:
    def test_string_passthrough(self) -> None:
        assert _clamp_future_value_to_now("cursor") == "cursor"


class TestBuildBaseParams:
    def test_leads_incremental_adds_updated_after_and_sorts_by_last_update(self) -> None:
        params = _build_base_params(
            NOCRM_ENDPOINTS["leads"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
        )
        assert params["updated_after"] == "2026-03-04T02:58:14Z"
        # Incremental syncs must sort ascending by the changed field so the asc watermark advances.
        assert params["order"] == "last_update"
        assert params["direction"] == "asc"

    @parameterized.expand([("users",), ("teams",), ("steps",), ("pipelines",), ("categories",), ("tags",), ("fields",)])
    def test_metadata_endpoints_send_no_order_or_filter(self, endpoint: str) -> None:
        # These endpoints don't document an `order` param, so we must not send one (nor a filter).
        params = _build_base_params(
            NOCRM_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        assert params == {}


def _page(n: int, start_id: int = 1) -> list[dict[str, int]]:
    return [{"id": start_id + i} for i in range(n)]


def _driver(api_key: str = "key") -> SourceDriver:
    return SourceDriver(NoCRMSource(), NoCRMSourceConfig(subdomain="acme", api_key=api_key))


class TestPagination:
    def test_stops_when_offset_is_ignored(self) -> None:
        # An endpoint that ignores offset re-serves the same first page; the no-progress guard must
        # break the loop after the repeat instead of looping forever (merge dedupes the repeat).
        result = _driver().run(
            "leads", [ScriptedResponse(json=_page(PAGE_SIZE, 1)), ScriptedResponse(json=_page(PAGE_SIZE, 1))]
        )
        # Exactly two requests were made and iteration terminated — no infinite loop.
        assert result.raised is None
        assert len(result.requests) == 2
        # The repeated ids are all id 1..PAGE_SIZE (dedup drops the duplicates downstream).
        assert {r["id"] for r in result.rows} == set(range(1, PAGE_SIZE + 1))

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "leads", [ScriptedResponse(json=_page(2, PAGE_SIZE + 1))], resume_state=NoCRMResumeConfig(offset=PAGE_SIZE)
        )
        assert result.raised is None
        assert len(result.rows) == 2
        # The first (and only) request must start at the saved offset, not 0.
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestRetryAndErrors:
    @parameterized.expand([(429,), (500,), (503,)])
    def test_retryable_status_is_retried_then_succeeds(self, status: int) -> None:
        result = _driver().run("leads", [ScriptedResponse(status=status, json=[]), ScriptedResponse(json=_page(2))])
        assert result.raised is None
        assert len(result.rows) == 2
        # The retryable status was re-issued rather than surfaced as an error.
        assert len(result.requests) == 2

    @parameterized.expand([(401, "Unauthorized"), (403, "Forbidden"), (404, "Not Found")])
    def test_client_error_raises_http_error(self, status: int, reason: str) -> None:
        result = _driver().run("leads", [ScriptedResponse(status=status, json=[])])
        # The status text stays intact so get_non_retryable_errors can match "40x Client Error".
        assert isinstance(result.raised, HTTPError)
        assert f"{status} Client Error" in str(result.raised)
        assert reason in str(result.raised)


class TestSSRFAndRedaction:
    def test_api_key_is_registered_for_redaction(self) -> None:
        result = _driver(api_key="secret-key").run("leads", [ScriptedResponse(json=[])])
        assert result.raised is None
        # The framework masks the auth secret in logs and raised errors.
        assert any(options.get("redact_values") == ("secret-key",) for options in result.session_options)

    def test_redirect_is_refused(self) -> None:
        result = _driver().run(
            "leads", [ScriptedResponse(status=302, headers={"Location": "https://evil.example/api"})]
        )
        # allow_redirects=False: a 3xx must be rejected so the key can't be steered off-host.
        assert isinstance(result.raised, ValueError)
        assert "refusing to follow" in str(result.raised)

    def test_validate_credentials_rejects_invalid_subdomain_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("key", "acme.evil") is False
        # An invalid subdomain must fail before any authenticated request is built.
        assert network.requests_log == []

    def test_validate_credentials_false_on_non_200(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            assert validate_credentials("key", "acme") is False
        assert [request.path for request in network.requests_log] == ["/api/v2/ping"]


class TestSourceResponse:
    @parameterized.expand(
        [
            ("users",),
            ("teams",),
            ("steps",),
            ("pipelines",),
            ("categories",),
            ("tags",),
            ("fields",),
            ("activities",),
            ("client_folders",),
        ]
    )
    def test_metadata_endpoints_are_unpartitioned(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])
        assert result.raised is None
        assert result.response is not None
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
