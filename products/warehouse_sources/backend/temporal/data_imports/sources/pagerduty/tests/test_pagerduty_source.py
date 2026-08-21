from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.source import PagerDutySource

PAGERDUTY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty"


class TestPagerDutySource:
    def setup_method(self) -> None:
        self.source = PagerDutySource()
        self.config = MagicMock(api_token="tok_123")

    def test_validate_credentials_success(self) -> None:
        with patch(f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials", return_value=(True, 200, None)):
            assert self.source.validate_credentials(self.config, team_id=1) == (True, None)

    def test_validate_credentials_invalid_token(self) -> None:
        with patch(
            f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials",
            return_value=(False, 401, "Invalid PagerDuty API key"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1)
            assert ok is False
            assert error == "Invalid PagerDuty API key"

    def test_validate_credentials_accepts_403_at_source_create(self) -> None:
        # A valid token may only be scoped to a subset of resources; don't block connection.
        with patch(
            f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials",
            return_value=(False, 403, "Your PagerDuty API key does not have access to this resource"),
        ):
            assert self.source.validate_credentials(self.config, team_id=1, schema_name=None) == (True, None)

    def test_validate_credentials_rejects_403_for_specific_schema(self) -> None:
        with patch(
            f"{PAGERDUTY_MODULE}.source.validate_pagerduty_credentials",
            return_value=(False, 403, "Your PagerDuty API key does not have access to this resource"),
        ):
            ok, error = self.source.validate_credentials(self.config, team_id=1, schema_name="incidents")
            assert ok is False
            assert error == "Your PagerDuty API key does not have access to this resource"
