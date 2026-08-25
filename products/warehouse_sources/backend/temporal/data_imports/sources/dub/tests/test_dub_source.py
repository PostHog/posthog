import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.dub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dub.source import DubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dub import DubSourceConfig

EVENT_ENDPOINTS = ("click_events", "lead_events", "sale_events")


class TestDubSource:
    def setup_method(self):
        self.source = DubSource()
        self.config = DubSourceConfig(api_key="dub_test_key")

    def test_source_is_released(self) -> None:
        # unreleasedSource=True hides the connector from every user; a finished source
        # must never regain it.
        assert not self.source.get_source_config.unreleasedSource

    @pytest.mark.parametrize(
        ("valid", "message"),
        [
            (True, None),
            (False, "Invalid Dub API key. Please check your key and try again."),
        ],
    )
    def test_validate_credentials_probes_token(self, valid: bool, message: str | None) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.validate_dub_credentials",
            return_value=(valid, message),
        ) as mock_validate:
            assert self.source.validate_credentials(self.config, team_id=1) == (valid, message)

        mock_validate.assert_called_once_with("dub_test_key")

    @pytest.mark.parametrize(
        ("reason", "expected"),
        [
            (None, (True, None)),
            ("Requires a Business plan or higher.", (False, "Requires a Business plan or higher.")),
        ],
    )
    def test_validate_credentials_with_schema_name_checks_endpoint_access(
        self, reason: str | None, expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.check_endpoint_access",
            return_value=reason,
        ) as mock_check:
            assert self.source.validate_credentials(self.config, team_id=1, schema_name="click_events") == expected

        mock_check.assert_called_once_with("dub_test_key", "click_events")

    def test_get_endpoint_permissions_probes_events_once(self) -> None:
        # All three event tables share /events, so one probe must cover them; ungated
        # endpoints are reported reachable without any request.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.dub.source.check_endpoint_access",
            return_value="Business plan required",
        ) as mock_check:
            permissions = self.source.get_endpoint_permissions(self.config, team_id=1, endpoints=list(ENDPOINTS))

        probed = [call.args[1] for call in mock_check.call_args_list]
        assert len([e for e in probed if e in EVENT_ENDPOINTS]) == 1
        assert set(probed) - set(EVENT_ENDPOINTS) == {"partners", "commissions", "payouts"}
        for endpoint in EVENT_ENDPOINTS:
            assert permissions[endpoint] == "Business plan required"
        assert permissions["links"] is None
        assert permissions["tags"] is None
