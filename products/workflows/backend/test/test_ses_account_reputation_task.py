from unittest import TestCase
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from parameterized import parameterized
from prometheus_client import CollectorRegistry

from products.workflows.backend.tasks.ses_account_reputation import poll_ses_account_reputation


class TestPollSesAccountReputation(TestCase):
    def setUp(self):
        self.registry = CollectorRegistry()
        registry_context = MagicMock()
        registry_context.__enter__ = MagicMock(return_value=self.registry)
        registry_context.__exit__ = MagicMock(return_value=False)
        self.registry_patcher = patch(
            "products.workflows.backend.tasks.ses_account_reputation.pushed_metrics_registry",
            return_value=registry_context,
        )
        self.mock_registry_factory = self.registry_patcher.start()
        self.addCleanup(self.registry_patcher.stop)

        provider_patcher = patch("products.workflows.backend.tasks.ses_account_reputation.SESProvider")
        self.mock_provider = provider_patcher.start().return_value
        self.addCleanup(provider_patcher.stop)

    @parameterized.expand(
        [
            ("HEALTHY", 1.0),
            ("PROBATION", 0.0),
            ("SHUTDOWN", 0.0),
        ]
    )
    def test_exports_enforcement_health_gauge(self, status, expected):
        self.mock_provider.get_account_reputation.return_value = {"enforcement_status": status, "findings": []}

        poll_ses_account_reputation()

        assert self.registry.get_sample_value("posthog_ses_account_enforcement_healthy") == expected

    @patch("products.workflows.backend.tasks.ses_account_reputation.time.time", return_value=1700000000.0)
    def test_exports_finding_counts_and_poll_timestamp(self, _mock_time):
        self.mock_provider.get_account_reputation.return_value = {
            "enforcement_status": "HEALTHY",
            "findings": [
                {"finding_type": "BOUNCE", "impact": "LOW", "scope": "tenant"},
                {"finding_type": "BOUNCE", "impact": "LOW", "scope": "tenant"},
                {"finding_type": "COMPLAINT", "impact": "HIGH", "scope": "account"},
            ],
        }

        poll_ses_account_reputation()

        def finding_count(scope, finding_type, impact):
            return self.registry.get_sample_value(
                "posthog_ses_open_reputation_findings",
                {"scope": scope, "finding_type": finding_type, "impact": impact},
            )

        assert finding_count("tenant", "BOUNCE", "LOW") == 2
        assert finding_count("account", "COMPLAINT", "HIGH") == 1
        assert (
            self.registry.get_sample_value("posthog_ses_account_reputation_last_poll_timestamp_seconds") == 1700000000.0
        )

    def test_provider_failure_does_not_raise_and_pushes_nothing(self):
        self.mock_provider.get_account_reputation.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "GetAccount"
        )

        poll_ses_account_reputation()

        self.mock_registry_factory.assert_not_called()
