import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.source import CodemagicSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codemagic import (
    CodemagicSourceConfig,
)


class TestCodemagicSource:
    def setup_method(self) -> None:
        self.source = CodemagicSource()
        self.team_id = 123
        self.config = CodemagicSourceConfig(api_token="test-token")

    @pytest.mark.parametrize(
        ("pinned_version", "expected_version"),
        [
            (None, "v3"),
            ("v1", "v1"),
            ("v3", "v3"),
        ],
    )
    def test_pinned_version_reaches_request_layer(self, pinned_version: str | None, expected_version: str) -> None:
        expected_path = "/apps" if expected_version == "v1" else "/api/v3/user/apps"
        body = {"applications": []} if expected_version == "v1" else {"data": [], "total_pages": 1}

        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert self.source.validate_credentials(self.config, self.team_id, api_version=pinned_version) == (
                True,
                None,
            )

        result = SourceDriver(self.source, self.config).run(
            "Applications", [ScriptedResponse(json=body)], api_version=pinned_version
        )

        assert [request.path for request in network.requests_log] == [expected_path]
        assert result.paths == [expected_path]
        assert result.raised is None
