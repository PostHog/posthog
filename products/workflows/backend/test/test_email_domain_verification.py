from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import EmailIntegration, Integration
from posthog.models.team.team import Team

from products.workflows.backend.providers import SESProvider
from products.workflows.backend.services.email_domain_verification import revoke_lost_email_domain_verifications


@patch("posthog.models.integration.email.reload_integrations_on_workers")
class TestRevokeLostEmailDomainVerifications(BaseTest):
    def _sender(self, email: str, team: Team | None = None) -> Integration:
        return Integration.objects.create(
            team=team or self.team,
            kind="email",
            integration_id=email,
            config={"email": email, "domain": email.split("@")[1], "provider": "ses", "verified": True},
        )

    def _provider(self, statuses: dict[str, tuple[str, str]]) -> SESProvider:
        with patch("products.workflows.backend.providers.ses.boto3.client"):
            provider = SESProvider()
        provider.ses_status_client = MagicMock()
        provider.ses_status_client.get_identity_verification_attributes.side_effect = lambda Identities: {
            "VerificationAttributes": {
                domain: {"VerificationStatus": statuses[domain][0]} for domain in Identities if domain in statuses
            }
        }
        provider.ses_status_client.get_identity_dkim_attributes.side_effect = lambda Identities: {
            "DkimAttributes": {
                domain: {"DkimVerificationStatus": statuses[domain][1]} for domain in Identities if domain in statuses
            }
        }
        return provider

    def _verified(self, sender: Integration) -> bool:
        sender.refresh_from_db()
        return sender.config["verified"]

    @parameterized.expand(
        [
            ("ses_failed_both_checks", "Failed", "Failed", False),
            ("dkim_still_succeeds", "Failed", "Success", True),
            ("verification_pending", "Pending", "Pending", True),
            ("still_verified", "Success", "Success", True),
        ]
    )
    def test_only_a_domain_ses_failed_stops_sending(self, _reload, _name, verification, dkim, still_verified):
        sender = self._sender("hello@lost.example.com")
        other_sender = self._sender("hello@kept.example.com")

        revoke_lost_email_domain_verifications(
            self._provider({"lost.example.com": (verification, dkim), "kept.example.com": ("Success", "Success")})
        )

        assert self._verified(sender) is still_verified
        assert self._verified(other_sender) is True

    def test_revokes_every_sender_of_the_domain_in_every_team(self, _reload):
        other_team = Team.objects.create(organization=self.organization, name="other team")
        senders = [
            self._sender("hello@lost.example.com"),
            self._sender("billing@lost.example.com"),
            self._sender("hello@lost.example.com", team=other_team),
        ]

        revoked = revoke_lost_email_domain_verifications(self._provider({"lost.example.com": ("Failed", "Failed")}))

        assert revoked == 3
        assert [self._verified(sender) for sender in senders] == [False, False, False]

    @patch("products.workflows.backend.facade.api.verify_ses_email_domain", return_value={"status": "success"})
    def test_verifying_the_domain_again_restarts_sending(self, _reload, _verify):
        sender = self._sender("hello@lost.example.com")
        revoke_lost_email_domain_verifications(self._provider({"lost.example.com": ("Failed", "Failed")}))
        assert self._verified(sender) is False

        EmailIntegration(sender).verify()

        assert self._verified(sender) is True
