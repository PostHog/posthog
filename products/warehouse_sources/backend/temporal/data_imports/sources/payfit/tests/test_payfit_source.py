from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.payfit import PayFitSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source import PayFitSource


class TestPayFitSource:
    def setup_method(self) -> None:
        self.source = PayFitSource()
        self.team_id = 123
        self.config = PayFitSourceConfig(api_key="payfit-key")

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://partner-api.payfit.com/companies/c/collaborators?maxResults=50",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://partner-api.payfit.com/companies/c/contracts?maxResults=50",
            ),
            ("inactive_token", "PayFit API key is inactive or invalid"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    def test_validate_credentials_probes_endpoint_scope_for_schema(self) -> None:
        # PayFit keys carry per-endpoint scopes, so per-schema validation must probe that endpoint
        # rather than only introspecting the token.
        with scripted_network(
            [
                ScriptedResponse(json={"active": True, "company_id": "company-1"}),
                ScriptedResponse(json={}),
            ]
        ) as network:
            result = self.source.validate_credentials(self.config, self.team_id, schema_name="absences")

        assert [request.path for request in network.requests_log] == [
            "/introspect",
            "/companies/company-1/absences",
        ]
        assert network.requests_log[1].param("status") == "all"
        assert network.requests_log[1].param("maxResults") == "1"
        assert result == (True, None)

    def test_validate_credentials_falls_back_for_unknown_schema(self) -> None:
        with scripted_network([ScriptedResponse(json={"active": True, "company_id": "company-1"})]) as network:
            result = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")

        assert [request.path for request in network.requests_log] == ["/introspect"]
        assert network.requests_log[0].json() == {"token": "payfit-key"}
        assert result == (True, None)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.payfit.source.payfit_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "collaborators"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "payfit-key"
        assert kwargs["endpoint"] == "collaborators"
        assert kwargs["resumable_source_manager"] is manager
