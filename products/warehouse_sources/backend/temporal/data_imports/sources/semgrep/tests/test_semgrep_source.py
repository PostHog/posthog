from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import (
    ENDPOINTS,
    SEMGREP_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source import SemgrepSource


def _config(api_token: str = "token") -> Any:
    config = MagicMock()
    config.api_token = api_token
    return config


class TestGetSchemas:
    def test_lists_every_endpoint_as_full_refresh(self) -> None:
        schemas = SemgrepSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Semgrep has no server-side updated-since filter (the findings `since` param doesn't move
        # on status/triage changes), so nothing may be advertised as incremental/append.
        assert all(not s.supports_incremental and not s.supports_append for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)
        for schema in schemas:
            assert schema.detected_primary_keys == SEMGREP_ENDPOINTS[schema.name].primary_keys

    def test_names_filter(self) -> None:
        schemas = SemgrepSource().get_schemas(_config(), team_id=1, names=["deployments", "secrets"])
        assert {s.name for s in schemas} == {"deployments", "secrets"}

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog (no I/O) — public docs render the table list.
        assert SemgrepSource.lists_tables_without_credentials is True
        tables = SemgrepSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        findings = next(t for t in tables if t["name"] == "sast_findings")
        assert findings["sync_methods"] == ["Full refresh"]
        assert findings["primary_keys"] == ["deployment_id", "id"]


class TestValidateCredentials:
    def test_success(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source.validate_semgrep_credentials",
            return_value=True,
        ) as mocked:
            ok, error = SemgrepSource().validate_credentials(_config(), team_id=1)
        assert ok is True
        assert error is None
        mocked.assert_called_once_with("token")

    def test_failure(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.source.validate_semgrep_credentials",
            return_value=False,
        ):
            ok, error = SemgrepSource().validate_credentials(_config(), team_id=1, schema_name="sast_findings")
        assert ok is False
        assert error is not None


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://semgrep.dev/api/v1/deployments/my-org/findings?issue_type=sast",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://semgrep.dev/api/v1/deployments/123/secrets",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = SemgrepSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='semgrep.dev', port=443): Read timed out."),
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://semgrep.dev/api/v1/deployments",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://semgrep.dev/api/v1/deployments",
            ),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = SemgrepSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)


class TestCanonicalDescriptions:
    def test_canonical_descriptions_keys_are_known_endpoints(self) -> None:
        # Every documented table must map to a real endpoint, or its descriptions never apply.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)
