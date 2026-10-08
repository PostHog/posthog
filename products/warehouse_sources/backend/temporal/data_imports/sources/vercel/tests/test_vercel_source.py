from typing import Any

from unittest import mock
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vercel import VercelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel import source as vercel_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.source import VercelSource


def _source_inputs(schema_name: str, **overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestVercelSource:
    def setup_method(self) -> None:
        self.source = VercelSource()
        self.config = VercelSourceConfig(access_token="token", team_id=None)

    def test_connection_host_fields_includes_team_id(self) -> None:
        # team_id retargets the stored token at a different Vercel team, so editing it must force
        # the token to be re-entered.
        assert self.source.connection_host_fields == ["team_id"]

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, team_id=1, names=["deployments"])
        assert [s.name for s in schemas] == ["deployments"]

    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.vercel.com/v6/deployments?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.vercel.com/v9/projects?limit=100"),
            (
                "billing_charges_team_not_found",
                "404 Client Error: Not Found for url: https://api.vercel.com/v1/billing/charges?from=2026-01-01T00%3A00%3A00.000Z&to=2026-02-01T00%3A00%3A00.000Z&teamId=team_abc",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limit", "429 Client Error: Too Many Requests for url: https://api.vercel.com/v6/deployments"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.vercel.com/v6/deployments"),
            ("read_timeout", "HTTPSConnectionPool(host='api.vercel.com', port=443): Read timed out."),
            # Not-found on a non-billing endpoint is unrelated to the billing_charges team-lookup
            # failure, so the match must stay scoped to that path rather than any 404 on the host.
            ("not_found_other_endpoint", "404 Client Error: Not Found for url: https://api.vercel.com/v6/deployments"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "Vercel API error (retryable): status=500, url=https://api.vercel.com/v1/billing/charges"),
            ("rate_limit", "Vercel API error (retryable): status=429, url=https://api.vercel.com/v6/deployments"),
        ]
    )
    def test_retryable_errors_match_known_failures(self, _name: str, observed_error: str) -> None:
        # Matches the message `_fetch_page`/`_open_billing_stream` raise after their internal
        # retry loop exhausts; keeps this benign, self-recovering failure out of error tracking.
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)

    @parameterized.expand(
        [
            (
                "connection_error",
                "HTTPSConnectionPool(host='api.vercel.com', port=443): Max retries exceeded with url: "
                '/v1/billing/charges?teamId=team_abc (Caused by ReadTimeoutError("HTTPSConnectionPool'
                "(host='api.vercel.com', port=443): Read timed out. (read timeout=120)\"))",
            ),
            (
                "read_timeout",
                "HTTPSConnectionPool(host='api.vercel.com', port=443): Read timed out. (read timeout=120)",
            ),
        ]
    )
    def test_retryable_errors_match_transient_network_failures(self, _name: str, observed_error: str) -> None:
        # `_fetch_page`/`_open_billing_stream` already retry these in-process; once exhausted, this
        # keeps the benign, self-recovering failure out of error tracking.
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)

    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        config = VercelSourceConfig(access_token="token", team_id="team_42")
        captured: dict[str, Any] = {}

        def fake_vercel_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock(name="source_response")

        manager = MagicMock()
        inputs = _source_inputs(
            "deployments",
            should_use_incremental_field=True,
            db_incremental_field_last_value=123,
            incremental_field="created",
        )

        with mock.patch.object(vercel_source_module, "vercel_source", fake_vercel_source):
            self.source.source_for_pipeline(config, manager, inputs)

        assert captured["access_token"] == "token"
        assert captured["team_id"] == "team_42"
        assert captured["endpoint"] == "deployments"
        assert captured["should_use_incremental_field"] is True
        assert captured["db_incremental_field_last_value"] == 123
        assert captured["incremental_field"] == "created"
        assert captured["resumable_source_manager"] is manager

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        captured: dict[str, Any] = {}

        def fake_vercel_source(**kwargs: Any):
            captured.update(kwargs)
            return MagicMock()

        inputs = _source_inputs("projects", should_use_incremental_field=False, db_incremental_field_last_value=999)
        with mock.patch.object(vercel_source_module, "vercel_source", fake_vercel_source):
            self.source.source_for_pipeline(self.config, MagicMock(), inputs)

        assert captured["db_incremental_field_last_value"] is None
