from datetime import UTC, datetime
from urllib.parse import parse_qs

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.coupa import (
    CoupaResumeConfig,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.settings import (
    COUPA_ENDPOINTS,
    ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.source import CoupaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coupa import CoupaSourceConfig


def _driver() -> SourceDriver:
    return SourceDriver(
        CoupaSource(),
        CoupaSourceConfig(instance_url="https://myorg.coupahost.com", client_id="cid", client_secret="sec"),
    )


def _token_response() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "tok-1", "token_type": "bearer", "expires_in": 86399})


def _form_body(body: bytes | None) -> dict[str, list[str]]:
    return parse_qs((body or b"").decode())


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://myorg.coupahost.com", "https://myorg.coupahost.com"),
            ("myorg.coupahost.com", "https://myorg.coupahost.com"),
            ("https://myorg.coupacloud.com/", "https://myorg.coupacloud.com"),
        ],
    )
    def test_valid_hosts(self, value: str, expected: str) -> None:
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://", "http://myorg.coupahost.com"])
    def test_invalid_hosts_raise(self, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_host(value)


class TestValidateCredentials:
    def test_valid_credentials_mint_a_token(self) -> None:
        with scripted_network([_token_response()]) as network:
            assert validate_credentials("https://myorg.coupahost.com", "cid", "sec") is True

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.method == "POST"
        assert request.url == "https://myorg.coupahost.com/oauth2/token"
        assert request.headers["authorization"] == "Basic Y2lkOnNlYw=="
        assert _form_body(request.body) == {"grant_type": ["client_credentials"]}

    def test_invalid_credentials(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={})]) as network:
            assert validate_credentials("https://myorg.coupahost.com", "cid", "bad") is False

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/oauth2/token"


class TestGetRows:
    def test_mints_endpoint_scoped_token_and_paginates(self) -> None:
        full_page = [{"id": i, "updated-at": "2024-01-01T00:00:00Z"} for i in range(PAGE_SIZE)]
        result = _driver().run(
            "invoices",
            [
                _token_response(),
                ScriptedResponse(json=full_page),
                ScriptedResponse(json=[{"id": "last", "updated-at": "2024-01-02T00:00:00Z"}]),
            ],
        )

        assert result.raised is None
        assert [len(batch) for batch in result.items] == [PAGE_SIZE, 1]
        # Keys are normalized so the cursor field always exists.
        assert all("updated_at" in row for row in result.rows)
        assert result.paths == ["/oauth2/token", "/api/invoices", "/api/invoices"]
        assert _form_body(result.requests[0].body)["scope"] == ["core.invoice.read"]
        assert result.params("offset") == [None, "0", str(PAGE_SIZE)]
        assert result.saved_states == [CoupaResumeConfig(next_offset=PAGE_SIZE)]
        assert result.committed_states == [CoupaResumeConfig(next_offset=PAGE_SIZE)]

    def test_scope_rejection_falls_back_to_scopeless_token(self) -> None:
        result = _driver().run(
            "invoices",
            [
                ScriptedResponse(status=400, json={"error": "invalid_scope"}),
                _token_response(),
                ScriptedResponse(json=[]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/oauth2/token", "/oauth2/token", "/api/invoices"]
        assert _form_body(result.requests[0].body)["scope"] == ["core.invoice.read"]
        assert "scope" not in _form_body(result.requests[1].body)

    def test_non_scope_400_does_not_fall_back(self) -> None:
        result = _driver().run("invoices", [ScriptedResponse(status=400, json={"error": "invalid_client"})])

        assert isinstance(result.raised, Exception)
        # Only the original (scoped) request is made; no scopeless retry.
        assert result.paths == ["/oauth2/token"]
        assert _form_body(result.requests[0].body)["scope"] == ["core.invoice.read"]

    def test_incremental_passes_updated_at_gt(self) -> None:
        result = _driver().run(
            "invoices",
            [_token_response(), ScriptedResponse(json=[])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        )

        assert result.raised is None
        assert result.requests[1].param("updated_at[gt]") == "2024-01-02T03:04:05Z"
        assert "updated_at%5Bgt%5D=2024-01-02T03%3A04%3A05Z" in result.urls[1]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "invoices",
            [_token_response(), ScriptedResponse(json=[{"id": 1}])],
            resume_state=CoupaResumeConfig(next_offset=150),
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}]
        assert result.requests[1].param("offset") == "150"

    def test_mid_sync_401_re_mints_token(self) -> None:
        result = _driver().run(
            "invoices",
            [
                _token_response(),
                ScriptedResponse(status=401, json={}),
                _token_response(),
                ScriptedResponse(json=[{"id": 1}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1]
        assert result.paths == ["/oauth2/token", "/api/invoices", "/oauth2/token", "/api/invoices"]
        assert result.requests[1].headers["authorization"] == "Bearer tok-1"


class TestEndpointPaths:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_paths_have_no_parent_placeholder(self, endpoint: str) -> None:
        # get_rows builds the URL by concatenation, so a nested path such as
        # /purchase_orders/{id}/order_lines would be requested verbatim. Coupa
        # exposes its line-level objects as top-level collections instead.
        assert "{" not in COUPA_ENDPOINTS[endpoint].path
        assert ":" not in COUPA_ENDPOINTS[endpoint].path


class TestCoupaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [_token_response(), ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        # Ordering within an updated_at window is undocumented — deferred watermark.
        assert result.response.sort_mode == "desc"
