from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.folk.source import FolkSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.folk import FolkSourceConfig


class TestFolkValidateCredentials:
    @parameterized.expand(
        [
            # (probe status, schema_name, expected_ok)
            ("ok", 200, None, True),
            ("ok_for_schema", 200, "people", True),
            # A 403 at source-create is a genuine key scoped away from the probe resource — accept it.
            ("forbidden_at_create_accepted", 403, None, True),
            # A 403 while configuring a specific schema means no access to that resource — reject.
            ("forbidden_for_schema_rejected", 403, "people", False),
            ("unauthorized_rejected", 401, None, False),
            ("connection_failure_rejected", None, None, False),
            ("unexpected_status_rejected", 500, None, False),
        ]
    )
    def test_status_mapping(
        self, _name: str, probe_status: int | None, schema_name: str | None, expected_ok: bool
    ) -> None:
        answer = ConnectionError("connection failed") if probe_status is None else ScriptedResponse(status=probe_status)
        with scripted_network(always(answer)) as network:
            ok, error = FolkSource().validate_credentials(
                FolkSourceConfig(api_key="folk_test"), team_id=1, schema_name=schema_name
            )

        assert ok is expected_ok
        assert (error is None) is expected_ok
        expected_path = "/v1/people" if schema_name else "/v1/users/me"
        assert {request.path for request in network.requests_log} == {expected_path}
        if schema_name:
            assert {request.param("limit") for request in network.requests_log} == {"1"}


class TestFolkResumableAndPipeline:
    @parameterized.expand(
        [
            # (endpoint, partition keys, partition mode)
            ("people", ["createdAt"], "datetime"),
            ("companies", ["createdAt"], "datetime"),
            ("notes", ["createdAt"], "datetime"),
            ("tasks", ["createdAt"], "datetime"),
            ("reminders", ["createdAt"], "datetime"),
            # Groups and users carry no timestamp to partition by.
            ("groups", None, None),
            ("users", None, None),
        ]
    )
    def test_source_for_pipeline_per_endpoint(
        self,
        endpoint: str,
        expected_keys: list[str] | None,
        expected_mode: str | None,
    ) -> None:
        result = SourceDriver(FolkSource(), FolkSourceConfig(api_key="folk_test")).run(
            endpoint, [ScriptedResponse(json={"data": {"items": [], "pagination": {}}})]
        )

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == ["id"]
        assert result.response.partition_keys == expected_keys
        assert result.response.partition_mode == expected_mode
