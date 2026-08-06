import json
from collections.abc import Iterable
from typing import Any, cast

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus, SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.glassfrog import (
    GlassfrogSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog import (
    glassfrog,
    source as source_module,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.glassfrog.source import GlassfrogSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> GlassfrogSourceConfig:
    return GlassfrogSourceConfig(api_key="gf_test_key")


class TestGlassfrogSourceConfig:
    def test_source_type(self) -> None:
        assert GlassfrogSource().source_type == ExternalDataSourceType.GLASSFROG

    def test_source_config_basics(self) -> None:
        config = GlassfrogSource().get_source_config

        assert config.name == "Glassfrog"
        assert config.category == DataWarehouseSourceCategory.PRODUCTIVITY
        # Alpha, and visible (no unreleasedSource) — a finished source ships connectable.
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath.endswith(".png")

    def test_single_required_api_key_field(self) -> None:
        fields = GlassfrogSource().get_source_config.fields

        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.required is True
        # API keys are secrets — must never be echoed back to the client.
        assert field.secret is True


class TestGlassfrogSchemas:
    def test_lists_expected_endpoints(self) -> None:
        names = {s.name for s in GlassfrogSource().get_schemas(_config(), team_id=1)}

        assert names == {
            "assignments",
            "checklist_items",
            "circles",
            "custom_fields",
            "metrics",
            "people",
            "projects",
            "roles",
        }

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_every_endpoint_is_full_refresh_only(self, endpoint: str) -> None:
        # No GlassFrog v3 endpoint exposes a server-side timestamp or cursor filter, so nothing can
        # sync incrementally — guarding against a future edit flipping this on without a real filter.
        schema = next(s for s in GlassfrogSource().get_schemas(_config(), team_id=1) if s.name == endpoint)

        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_names_filter(self) -> None:
        schemas = GlassfrogSource().get_schemas(_config(), team_id=1, names=["circles"])

        assert [s.name for s in schemas] == ["circles"]

    def test_documented_tables_render_for_public_docs(self) -> None:
        # lists_tables_without_credentials=True means the public docs <SourceTables /> is fed here.
        tables = GlassfrogSource().get_documented_tables()

        by_name = {t["name"]: t for t in tables}
        assert set(by_name) == set(ENDPOINTS)
        assert by_name["circles"]["description"]
        assert by_name["circles"]["sync_methods"] == ["Full refresh"]


class TestGlassfrogCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch.object(source_module, "validate_glassfrog_credentials")
    def test_validate_credentials(
        self, _name: str, probe_result: bool, expected_ok: bool, mock_validate: MagicMock
    ) -> None:
        mock_validate.return_value = probe_result

        ok, error = GlassfrogSource().validate_credentials(_config(), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = GlassfrogSource().get_non_retryable_errors()

        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)


class TestGlassfrogPipelineHandoff:
    @patch.object(glassfrog, "make_tracked_session")
    def test_source_for_pipeline_plumbs_endpoint_and_key(self, mock_session_factory: MagicMock) -> None:
        session = MagicMock()
        session.headers = {}
        prepared_requests: list[requests.PreparedRequest] = []

        def _prepare(request: requests.Request) -> requests.PreparedRequest:
            prepared = request.prepare()
            prepared_requests.append(prepared)
            return prepared

        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"circles": [{"id": 1, "name": "General Company Circle"}]}).encode()
        session.prepare_request.side_effect = _prepare
        session.send.return_value = response
        mock_session_factory.return_value = session

        inputs = MagicMock()
        inputs.schema_name = "circles"
        inputs.team_id = 1
        inputs.job_id = "job_1"

        source_response = GlassfrogSource().source_for_pipeline(_config(), inputs)

        assert source_response.name == "circles"
        assert source_response.primary_keys == ["id"]

        # The items thunk should actually pull rows using the configured key/endpoint.
        rows = list(cast(Iterable[Any], source_response.items()))
        assert rows == [[{"id": 1, "name": "General Company Circle"}]]
        assert prepared_requests[0].headers["X-Auth-Token"] == "gf_test_key"
