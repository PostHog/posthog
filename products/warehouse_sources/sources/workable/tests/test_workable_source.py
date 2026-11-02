from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workable import (
    WorkableSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workable import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.source import WorkableSource


def _config() -> WorkableSourceConfig:
    return WorkableSourceConfig(subdomain="acme", api_token="tok")


class TestSourceConfig:
    def test_subdomain_is_a_connection_host_field(self) -> None:
        # Retargeting the subdomain must re-require the token (it's where the token is sent).
        assert WorkableSource().connection_host_fields == ["subdomain"]


class TestValidateCredentials:
    @parameterized.expand(
        [
            # (status, ok, schema_name, expected_valid)
            ("ok_create", 200, True, None, True),
            ("ok_schema", 200, True, "candidates", True),
            ("unauthorized_create", 401, False, None, False),
            ("unauthorized_schema", 401, False, "candidates", False),
            # 403 = valid token missing a scope: accepted at create, rejected for a specific schema.
            ("forbidden_create_accepted", 403, False, None, True),
            ("forbidden_schema_rejected", 403, False, "candidates", False),
        ]
    )
    def test_credential_status_mapping(
        self, _name: str, status: int, ok: bool, schema_name: str | None, expected_valid: bool
    ) -> None:
        with mock.patch.object(source_module, "validate_workable_credentials", lambda *_a, **_k: (status, ok)):
            valid, _msg = WorkableSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert valid is expected_valid

    @parameterized.expand(
        [
            ("default", None, "/spi/v3/jobs"),
            ("top_level_endpoint", "departments", "/spi/v3/departments"),
            # A fan-out endpoint has no bare list path; probing its literal template would 404.
            ("fanout_probes_parent", "candidate_activities", "/spi/v3/candidates"),
        ]
    )
    def test_probe_path(self, _name: str, schema_name: str | None, expected_path: str) -> None:
        with scripted_network(always(ScriptedResponse(json={}))) as network:
            valid, _msg = WorkableSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)

        assert valid is True
        assert [r.path for r in network.requests_log] == [expected_path]

    def test_invalid_subdomain_is_a_failure(self) -> None:
        def _raise(*_a: Any, **_k: Any) -> Any:
            raise ValueError("Invalid Workable subdomain")

        with mock.patch.object(source_module, "validate_workable_credentials", _raise):
            valid, msg = WorkableSource().validate_credentials(_config(), team_id=1)
        assert valid is False
        assert "subdomain" in (msg or "")


class TestMisc:
    def test_source_for_pipeline_plumbs_arguments(self) -> None:
        result = SourceDriver(WorkableSource(), _config()).run(
            "candidates",
            [ScriptedResponse(json={"candidates": [], "paging": {}})],
            incremental_field="updated_at",
            db_incremental_field_last_value="2026-01-01",
        )

        request = result.requests[0]
        assert request.url.startswith("https://acme.workable.com/spi/v3/candidates?")
        assert request.headers["authorization"] == "Bearer tok"
        assert request.param("updated_after") == "2026-01-01"

    def test_source_for_pipeline_omits_last_value_when_not_incremental(self) -> None:
        result = SourceDriver(WorkableSource(), _config()).run(
            "members",
            [ScriptedResponse(json={"members": [], "paging": {}})],
            db_incremental_field_last_value="2026-01-01",
        )

        assert "updated_after" not in result.requests[0].query
        assert "created_after" not in result.requests[0].query
