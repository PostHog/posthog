from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from botocore.exceptions import ClientError
from parameterized import parameterized
from prometheus_client import CollectorRegistry

from products.workflows.backend.tasks.ses_account_reputation import (
    poll_ses_account_enforcement,
    poll_ses_reputation_findings,
)


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

        time_patcher = patch(
            "products.workflows.backend.tasks.ses_account_reputation.time.time", return_value=1700000000.0
        )
        time_patcher.start()
        self.addCleanup(time_patcher.stop)

    @parameterized.expand(
        [
            ("HEALTHY", 1.0),
            ("PROBATION", 0.0),
            ("SHUTDOWN", 0.0),
        ]
    )
    def test_enforcement_poll_exports_health_gauge_and_timestamp(self, status, expected):
        self.mock_provider.get_account_enforcement_status.return_value = status

        poll_ses_account_enforcement()

        assert self.registry.get_sample_value("posthog_ses_account_enforcement_healthy") == expected
        assert (
            self.registry.get_sample_value("posthog_ses_account_reputation_last_poll_timestamp_seconds") == 1700000000.0
        )
        self.mock_registry_factory.assert_called_once_with("ses_account_reputation")
        self.mock_provider.get_account_reputation_findings.assert_not_called()

    def test_findings_poll_exports_counts_and_its_own_timestamp(self):
        self.mock_provider.get_account_reputation_findings.return_value = [
            {"finding_type": "BOUNCE", "impact": "LOW", "scope": "tenant"},
            {"finding_type": "BOUNCE", "impact": "LOW", "scope": "tenant"},
            {"finding_type": "COMPLAINT", "impact": "HIGH", "scope": "account"},
        ]

        poll_ses_reputation_findings()

        def finding_count(scope, finding_type, impact):
            return self.registry.get_sample_value(
                "posthog_ses_open_reputation_findings",
                {"scope": scope, "finding_type": finding_type, "impact": impact},
            )

        assert finding_count("tenant", "BOUNCE", "LOW") == 2
        assert finding_count("account", "COMPLAINT", "HIGH") == 1
        assert (
            self.registry.get_sample_value("posthog_ses_reputation_findings_last_poll_timestamp_seconds")
            == 1700000000.0
        )
        assert self.registry.get_sample_value("posthog_ses_account_reputation_last_poll_timestamp_seconds") is None
        self.mock_registry_factory.assert_called_once_with("ses_reputation_findings")

    @parameterized.expand(
        [
            (
                "enforcement_throttled",
                poll_ses_account_enforcement,
                "get_account_enforcement_status",
                ClientError({"Error": {"Code": "TooManyRequestsException"}}, "ListRecommendations"),
                "enforcement",
                "throttled",
                "ses_account_reputation_failure",
            ),
            (
                "enforcement_access_denied",
                poll_ses_account_enforcement,
                "get_account_enforcement_status",
                ClientError({"Error": {"Code": "AccessDenied"}}, "GetAccount"),
                "enforcement",
                "error",
                "ses_account_reputation_failure",
            ),
            (
                "enforcement_missing_status_field",
                poll_ses_account_enforcement,
                "get_account_enforcement_status",
                KeyError("EnforcementStatus"),
                "enforcement",
                "error",
                "ses_account_reputation_failure",
            ),
            (
                "findings_throttled",
                poll_ses_reputation_findings,
                "get_account_reputation_findings",
                ClientError({"Error": {"Code": "TooManyRequestsException"}}, "ListRecommendations"),
                "findings",
                "throttled",
                "ses_reputation_findings_failure",
            ),
            (
                "findings_access_denied",
                poll_ses_reputation_findings,
                "get_account_reputation_findings",
                ClientError({"Error": {"Code": "AccessDenied"}}, "GetAccount"),
                "findings",
                "error",
                "ses_reputation_findings_failure",
            ),
        ]
    )
    def test_poll_failure_pushes_only_a_failure_marker(
        self, _name, task, provider_method, error, poll, reason, failure_job
    ):
        getattr(self.mock_provider, provider_method).side_effect = error

        task()

        assert self.mock_registry_factory.call_args_list == [call(failure_job)]
        assert (
            self.registry.get_sample_value(
                "posthog_ses_reputation_poll_last_failure_timestamp_seconds", {"poll": poll, "reason": reason}
            )
            == 1700000000.0
        )
