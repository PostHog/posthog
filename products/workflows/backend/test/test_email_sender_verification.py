from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

import dns.resolver
from botocore.exceptions import EndpointConnectionError
from parameterized import parameterized

from posthog.models.integration import Integration

from products.workflows.backend.facade.tasks import refresh_pending_email_senders


class TestEmailSenderVerification(APIBaseTest):
    @parameterized.expand(
        [
            ("verified", "Success", True, True, "feedback.example.com", False, False, True),
            ("dkim_pending", "Pending", True, True, "feedback.example.com", False, False, False),
            ("dmarc_missing", "Success", False, True, "feedback.example.com", False, False, False),
            ("tenant_missing", "Success", True, False, "feedback.example.com", False, False, False),
            ("mail_from_changed", "Success", True, True, "other.example.com", False, False, False),
            ("sender_edited_during_check", "Success", True, True, "feedback.example.com", True, False, False),
            ("overlapping_sweeps", "Success", True, True, "feedback.example.com", False, True, True),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_background_verification_updates_sender_status_without_ui(
        self,
        _name: str,
        dkim_status: str,
        has_dmarc: bool,
        has_tenant: bool,
        mail_from_domain: str,
        edit_during_check: bool,
        reenter_during_check: bool,
        expected_verified: bool,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
    ) -> None:
        integration = Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="sender@example.com",
            config={
                "email": "sender@example.com",
                "domain": "example.com",
                "name": "Example sender",
                "provider": "ses",
                "mail_from_subdomain": "feedback",
                "verified": False,
            },
        )
        ses = mock_boto_client.return_value
        ses.verify_domain_identity.return_value = {"VerificationToken": "example-token"}
        ses.verify_domain_dkim.return_value = {"DkimTokens": ["example-dkim"]}
        ses.get_identity_verification_attributes.return_value = {
            "VerificationAttributes": {"example.com": {"VerificationStatus": "Success"}}
        }
        if reenter_during_check:
            entered = False

            def reenter_sweep(**kwargs: list[str]) -> dict[str, dict[str, dict[str, str]]]:
                nonlocal entered
                if not entered:
                    entered = True
                    refresh_pending_email_senders()
                return {"VerificationAttributes": {"example.com": {"VerificationStatus": "Success"}}}

            ses.get_identity_verification_attributes.side_effect = reenter_sweep
        ses.get_identity_dkim_attributes.return_value = {
            "DkimAttributes": {"example.com": {"DkimVerificationStatus": dkim_status}}
        }
        ses.get_identity_mail_from_domain_attributes.return_value = {
            "MailFromDomainAttributes": {
                "example.com": {"MailFromDomainStatus": "Success", "MailFromDomain": mail_from_domain}
            }
        }
        ses.get_caller_identity.return_value = {"Account": "123456789012"}
        ses.list_resource_tenants.return_value = {
            "ResourceTenants": [{"TenantName": f"team-{self.team.id}"}] if has_tenant else []
        }
        if edit_during_check:

            def edit_sender(**kwargs: str) -> dict[str, list[dict[str, str]]]:
                Integration.objects.filter(id=integration.id).update(
                    config={**integration.config, "mail_from_subdomain": "updated"}
                )
                return {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]}

            ses.list_resource_tenants.side_effect = edit_sender
        mock_resolver.return_value.resolve.return_value = [SimpleNamespace(strings=[b"v=DMARC1; p=none;"])]
        if not has_dmarc:
            mock_resolver.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()
        ses.verify_domain_identity.side_effect = RuntimeError("Background checks must not create SES identities")
        ses.verify_domain_dkim.side_effect = RuntimeError("Background checks must not change DKIM")
        ses.set_identity_mail_from_domain.side_effect = RuntimeError("Background checks must not change MAIL FROM")

        url = f"/api/projects/{self.team.id}/integrations/{integration.id}/"
        assert self.client.get(url).json()["config"]["verified"] is False

        refresh_pending_email_senders()

        response = self.client.get(url)
        assert response.status_code == 200
        assert response.json()["config"]["verified"] is expected_verified
        ses.get_identity_verification_attributes.assert_called_once_with(Identities=["example.com"])

        if expected_verified:
            mock_boto_client.reset_mock()
            refresh_pending_email_senders()
            mock_boto_client.assert_not_called()

    @parameterized.expand(
        [
            ("provider_failure", False, [False, True], [True, True]),
            ("budget_exhausted", True, [False, False], [False, True]),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_provider_failure_does_not_block_other_senders_and_recovers_on_next_sweep(
        self,
        _name: str,
        interrupt_sweep: bool,
        first_sweep_statuses: list[bool],
        second_sweep_statuses: list[bool],
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
    ) -> None:
        senders = [
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=f"sender@{domain}",
                config={
                    "email": f"sender@{domain}",
                    "domain": domain,
                    "provider": "ses",
                    "mail_from_subdomain": "feedback",
                    "verified": False,
                },
            )
            for domain in ["first.example.com", "second.example.com"]
        ]
        ses = mock_boto_client.return_value
        identity_attributes = {
            "VerificationAttributes": {sender.config["domain"]: {"VerificationStatus": "Success"} for sender in senders}
        }

        def get_identity_attributes(**kwargs: list[str]) -> dict[str, dict[str, dict[str, str]]]:
            if kwargs["Identities"] == ["first.example.com"]:
                raise EndpointConnectionError(endpoint_url="https://ses.example.com")
            return identity_attributes

        ses.get_identity_verification_attributes.side_effect = get_identity_attributes
        ses.get_identity_dkim_attributes.return_value = {
            "DkimAttributes": {sender.config["domain"]: {"DkimVerificationStatus": "Success"} for sender in senders}
        }
        ses.get_identity_mail_from_domain_attributes.return_value = {
            "MailFromDomainAttributes": {
                sender.config["domain"]: {
                    "MailFromDomainStatus": "Success",
                    "MailFromDomain": f"feedback.{sender.config['domain']}",
                }
                for sender in senders
            }
        }
        ses.get_caller_identity.return_value = {"Account": "123456789012"}
        ses.list_resource_tenants.return_value = {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]}
        mock_resolver.return_value.resolve.return_value = [SimpleNamespace(strings=[b"v=DMARC1; p=none;"])]

        if interrupt_sweep:
            with patch(
                "products.workflows.backend.services.email_sender_verification.monotonic",
                side_effect=[0.0, 0.0, 241.0],
            ):
                refresh_pending_email_senders()
        else:
            refresh_pending_email_senders()

        urls = [f"/api/projects/{self.team.id}/integrations/{sender.id}/" for sender in senders]
        assert [self.client.get(url).json()["config"]["verified"] for url in urls] == first_sweep_statuses

        ses.get_identity_verification_attributes.side_effect = None
        ses.get_identity_verification_attributes.return_value = identity_attributes
        refresh_pending_email_senders()

        assert [self.client.get(url).json()["config"]["verified"] for url in urls] == second_sweep_statuses

        refresh_pending_email_senders()
        assert [self.client.get(url).json()["config"]["verified"] for url in urls] == [True, True]
