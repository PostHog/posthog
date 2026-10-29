from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gainsight_cs.source import GainsightCsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gainsightcs import (
    GainsightCsSourceConfig,
)


def _config(custom_objects: str | None = None) -> GainsightCsSourceConfig:
    return GainsightCsSourceConfig(
        domain="acme.gainsightcloud.com",
        access_key="key",
        custom_objects=custom_objects,
    )


class TestGainsightCsSourceCredentials:
    def test_probes_the_object_behind_the_schema_being_checked(self) -> None:
        fields = {"result": True, "data": [{"objectName": "health__gc", "fields": [{"fieldName": "Gsid"}]}]}
        with scripted_network([ScriptedResponse(json=fields)]) as network:
            result = GainsightCsSource().validate_credentials(
                _config("health__gc"), team_id=1, schema_name="health__gc"
            )

        assert result == (True, None)
        assert [request.path for request in network.requests_log] == ["/v1/meta/services/objects/health__gc/describe"]

    @parameterized.expand(
        [
            (
                "cta_configuration",
                {"result": True, "data": {"CTA_STATUS": [{"gsid": "s1", "name": "New"}]}},
                "/v2/cockpit/admin/picklist/lite",
            ),
            (
                "cta_task",
                {"result": True, "data": [{"objectName": "call_to_action", "fields": [{"fieldName": "Gsid"}]}]},
                "/v1/meta/services/objects/call_to_action/describe",
            ),
        ]
    )
    def test_probes_the_cockpit_route_a_cockpit_table_reads(self, schema_name: str, body: dict, path: str) -> None:
        with scripted_network([ScriptedResponse(json=body)]) as network:
            result = GainsightCsSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)

        assert result == (True, None)
        assert [request.path for request in network.requests_log] == [path]

    def test_probes_company_when_no_schema_is_named(self) -> None:
        fields = {"result": True, "data": [{"objectName": "company", "fields": [{"fieldName": "Gsid"}]}]}
        with scripted_network([ScriptedResponse(json=fields)]) as network:
            result = GainsightCsSource().validate_credentials(_config(), team_id=1)

        assert result == (True, None)
        assert [request.path for request in network.requests_log] == ["/v1/meta/services/objects/company/describe"]

    def test_reports_an_unknown_schema_without_calling_gainsight(self) -> None:
        with scripted_network([]) as network:
            ok, error = GainsightCsSource().validate_credentials(_config(), team_id=1, schema_name="not_an_object")

        assert ok is False
        assert error is not None and "Unknown Gainsight object" in error
        assert network.requests_log == []


class TestGainsightCsSourcePipeline:
    def test_refuses_a_schema_that_is_neither_standard_nor_declared_custom(self) -> None:
        result = SourceDriver(GainsightCsSource(), _config()).run("dropped_by_validation", [])

        assert isinstance(result.raised, ValueError)
        assert "Unknown Gainsight object" in str(result.raised)
        assert result.requests == []
