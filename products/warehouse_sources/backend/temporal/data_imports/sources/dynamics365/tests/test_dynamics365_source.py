import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.dynamics365 import (
    INVALID_ORGANIZATION_URL_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.settings import (
    DYNAMICS365_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source import (
    CREDENTIALS_REJECTED_ERROR,
    PERMISSION_ERROR,
    TABLE_MISSING_ERROR,
    UNREACHABLE_ERROR,
    Dynamics365Source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365 import (
    Dynamics365SourceConfig,
)

PROBE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source.probe_credentials"
SOURCE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.dynamics365.source.dynamics365_source"


class TestDynamics365Source:
    def setup_method(self) -> None:
        self.source = Dynamics365Source()
        self.team_id = 123
        self.config = Dynamics365SourceConfig(
            organization_url="https://contoso.crm.dynamics.com",
            tenant_id="72f988bf-86f1-41af-91ab-2d7cd011db47",
            client_id="cid",
            client_secret="sec",
        )

    def test_api_version_is_pinned_to_the_path_the_code_calls(self) -> None:
        assert self.source.supported_versions == ("v9.2",)
        assert self.source.default_version == "v9.2"
        assert self.source.resolve_api_version(None) == "v9.2"

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()

        assert set(descriptions) == set(ENDPOINTS)
        for name, entry in descriptions.items():
            columns = entry.get("columns") or {}
            # The GUID primary key and both tracking columns are always documented.
            assert DYNAMICS365_ENDPOINTS[name].primary_keys[0] in columns
            assert {"createdon", "modifiedon"} <= set(columns)

    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_accepts_a_working_probe(self, mock_probe: mock.MagicMock) -> None:
        mock_probe.return_value = (True, 200)

        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_probe.call_args.args[4] == "v9.2"

    @pytest.mark.parametrize(
        "status, expected_message",
        [
            (401, CREDENTIALS_REJECTED_ERROR),
            (403, PERMISSION_ERROR),
            (404, TABLE_MISSING_ERROR),
            (500, UNREACHABLE_ERROR),
            (None, UNREACHABLE_ERROR),
        ],
    )
    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_explains_the_failure(
        self, mock_probe: mock.MagicMock, status: int | None, expected_message: str
    ) -> None:
        mock_probe.return_value = (False, status)

        is_valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert message == expected_message

    @pytest.mark.parametrize(
        "schema_name, expected_ok_statuses",
        [
            # At source-create a valid token that can't read accounts must not block setup.
            (None, (200, 403)),
            # Checking one table must surface a missing grant for that table.
            ("Cases", (200,)),
        ],
    )
    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_tolerates_403_only_at_source_create(
        self, mock_probe: mock.MagicMock, schema_name: str | None, expected_ok_statuses: tuple[int, ...]
    ) -> None:
        mock_probe.return_value = (True, 200)

        self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert mock_probe.call_args.kwargs["ok_statuses"] == expected_ok_statuses
        assert mock_probe.call_args.args[5] == schema_name

    def test_validate_credentials_rejects_a_non_dataverse_environment_url(self) -> None:
        config = Dynamics365SourceConfig(
            organization_url="https://evil.test",
            tenant_id="72f988bf-86f1-41af-91ab-2d7cd011db47",
            client_id="cid",
            client_secret="sec",
        )

        is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message == INVALID_ORGANIZATION_URL_ERROR
