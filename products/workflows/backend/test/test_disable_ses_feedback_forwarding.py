import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from botocore.exceptions import ClientError

from posthog.models.integration import Integration


class TestDisableSesFeedbackForwarding(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        for domain, provider in [("ses.com", "ses"), ("gone.com", "ses"), ("broken.com", "ses"), ("mj.com", "mailjet")]:
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=f"a@{domain}",
                config={"domain": domain, "provider": provider},
            )

    @patch("products.workflows.backend.management.commands.disable_ses_feedback_forwarding.SESProvider")
    def test_updates_ses_domains_and_reports_real_failures(self, mock_provider_cls: MagicMock) -> None:
        def put(domain: str) -> None:
            code = {"gone.com": "NotFoundException", "broken.com": "TooManyRequestsException"}.get(domain)
            if code:
                raise ClientError({"Error": {"Code": code}}, "PutEmailIdentityFeedbackAttributes")

        mock_provider_cls.return_value.disable_feedback_forwarding.side_effect = put

        with pytest.raises(CommandError, match="broken.com"):
            call_command("disable_ses_feedback_forwarding")

        called = [c.args[0] for c in mock_provider_cls.return_value.disable_feedback_forwarding.call_args_list]
        assert called == ["broken.com", "gone.com", "ses.com"]
