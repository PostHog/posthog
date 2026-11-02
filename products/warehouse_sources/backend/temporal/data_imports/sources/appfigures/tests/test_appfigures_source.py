import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source import AppfiguresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfigures import (
    AppfiguresSourceConfig,
)


class TestAppfiguresSource:
    def setup_method(self):
        self.source = AppfiguresSource()
        self.team_id = 123
        self.config = AppfiguresSourceConfig(personal_access_token="pat_test")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_retryable_errors_match_transient_status_raise(self):
        observed_error = "Appfigures API error (retryable): status=503, url=https://api.appfigures.com/v2/products/mine"
        retryable_errors = self.source.get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)

    @pytest.mark.parametrize(
        "status,schema_name,expected_ok",
        [
            (200, None, True),
            (200, "reviews", True),
            (401, None, False),
            (401, "reviews", False),
            # 403 at source-create is a valid token missing an unrelated scope — accept it.
            (403, None, True),
            # 403 for a specific schema means the token can't sync that table — reject.
            (403, "reviews", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials(self, status: int | None, schema_name: str | None, expected_ok: bool) -> None:
        script = always(ScriptedResponse(status=status)) if status is not None else [ConnectionResetError("boom")]
        with scripted_network(script):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
            assert ok is expected_ok

    @pytest.mark.parametrize(
        "schema_name,expected_path",
        [
            ("reviews", "/reviews"),
            # /ranks takes product ids in its path, so it can't be requested as-is. It shares the
            # `public:read` grant with reviews, so reviews is what gets probed.
            ("ranks", "/reviews"),
        ],
    )
    def test_validate_credentials_probes_schema_specific_path(self, schema_name: str, expected_path: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == f"/v2{expected_path}"
        assert network.requests_log[0].headers["authorization"] == "Bearer pat_test"

    def test_validate_credentials_defaults_to_products_path(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            self.source.validate_credentials(self.config, self.team_id)
        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v2/products/mine"
        assert network.requests_log[0].headers["authorization"] == "Bearer pat_test"
