import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leexi import LeexiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source import LeexiSource

PROBE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source.probe_endpoint"


class TestLeexiSource:
    def setup_method(self):
        self.source = LeexiSource()
        self.team_id = 123
        self.config = LeexiSourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    @pytest.mark.parametrize(
        "status, schema_name, expected_valid",
        [
            (200, None, True),
            (401, None, False),
            (402, None, False),
            # A key that authenticates but lacks the probe scope must not block source creation.
            (403, None, True),
            (403, "users", False),
            (200, "calls", True),
            (None, None, False),
        ],
    )
    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_status_mapping(self, mock_probe, status, schema_name, expected_valid):
        mock_probe.return_value = status

        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert (message is None) is expected_valid

    @mock.patch(PROBE_PATCH)
    def test_validate_credentials_probes_schema_specific_path(self, mock_probe):
        mock_probe.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, "call_notes")
        assert mock_probe.call_args.args[2] == "/calls"

    @mock.patch(PROBE_PATCH)
    def test_endpoint_permissions_marks_missing_scope_and_dedupes_probes(self, mock_probe):
        mock_probe.side_effect = lambda _id, _secret, path: 403 if path == "/calls" else 200

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        assert permissions["calls"] == "API key is missing the `read_calls` permission scope"
        assert permissions["call_notes"] == "API key is missing the `read_calls` permission scope"
        assert permissions["users"] is None
        assert permissions["teams"] is None
        assert permissions["meeting_events"] is None
        # calls and call_notes share the /calls probe: 4 unique paths, not 5 requests.
        assert mock_probe.call_count == 4

    @pytest.mark.parametrize("status", [429, 500, None])
    @mock.patch(PROBE_PATCH)
    def test_endpoint_permissions_ignores_transient_failures(self, mock_probe, status):
        mock_probe.return_value = status
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["calls"])
        assert permissions["calls"] is None
