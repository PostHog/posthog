import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.leexi import LeexiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.leexi.source import LeexiSource


class TestLeexiSource:
    def setup_method(self) -> None:
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
    def test_validate_credentials_status_mapping(
        self, status: int | None, schema_name: str | None, expected_valid: bool
    ) -> None:
        script = always(ConnectionError("connection failed") if status is None else ScriptedResponse(status=status))
        with scripted_network(script) as network:
            is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name)

        assert is_valid is expected_valid
        assert (message is None) is expected_valid
        expected_path = "/v1/calls" if schema_name == "calls" else "/v1/users"
        assert {request.path for request in network.requests_log} == {expected_path}

    def test_endpoint_permissions_marks_missing_scope_and_dedupes_probes(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(status=403 if request.path == "/v1/calls" else 200)

        with scripted_network(respond) as network:
            permissions = self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        assert permissions["calls"] == "API key is missing the `read_calls` permission scope"
        assert permissions["call_notes"] == "API key is missing the `read_calls` permission scope"
        assert permissions["users"] is None
        assert permissions["teams"] is None
        assert permissions["meeting_events"] is None
        # calls and call_notes share the /calls probe: 4 unique paths, not 5 requests.
        assert len(network.requests_log) == 4
        assert {request.path for request in network.requests_log} == {
            "/v1/calls",
            "/v1/meeting_events",
            "/v1/users",
            "/v1/teams",
        }
