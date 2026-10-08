import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.incidentio import (
    IncidentIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source import IncidentIoSource

INCIDENT_IO_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.incident_io.make_tracked_session"
)
INCIDENT_IO_SOURCE_FN_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.source.incident_io_source"
)


class TestIncidentIoSource:
    def setup_method(self):
        self.source = IncidentIoSource()
        self.team_id = 123
        self.config = IncidentIoSourceConfig(api_key="api-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.incident.io/v2/incidents?page_size=250",
            "403 Client Error: Forbidden for url: https://api.incident.io/v2/alerts",
            "404 Client Error: Not Found for url: https://api.incident.io/v2/follow_ups?page_size=250",
            "410 Client Error: Gone for url: https://api.incident.io/v2/follow_ups?page_size=250",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.incident.io/v2/incidents",
            "404 Client Error: Not Found for url: https://api.incident.io/v3/follow_ups?page_size=250",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the incidents list exposes server-side timestamp filters with a sortable order.
        assert incremental == {"incidents"}

    @pytest.mark.parametrize(
        "pinned, expected_url",
        [
            (None, "https://api.incident.io/v3/follow_ups?page_size=1"),
            ("v3", "https://api.incident.io/v3/follow_ups?page_size=1"),
            ("v1", "https://api.incident.io/v2/follow_ups?page_size=1"),
        ],
    )
    @mock.patch(INCIDENT_IO_SESSION_PATCH)
    def test_validate_credentials_probes_the_pinned_version(self, mock_session, pinned, expected_url):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)

        self.source.validate_credentials(self.config, self.team_id, schema_name="follow_ups", api_version=pinned)

        assert mock_session.return_value.get.call_args.args[0] == expected_url

    @pytest.mark.parametrize("pinned", ["v1", "v3"])
    @mock.patch(INCIDENT_IO_SOURCE_FN_PATCH)
    def test_source_for_pipeline_passes_the_pinned_version(self, mock_source_fn, pinned):
        inputs = mock.MagicMock(api_version=pinned, schema_name="follow_ups")

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source_fn.call_args.kwargs["api_version"] == pinned
