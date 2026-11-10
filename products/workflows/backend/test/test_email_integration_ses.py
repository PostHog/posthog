from typing import cast

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from posthog.api.integration import IntegrationViewSet
from posthog.models.integration import EmailIntegration, Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.workflows.backend.providers import SESProvider
from products.workflows.backend.providers.ses import AWS_ACCOUNT_ID_CACHE_KEY


class TestEmailIntegrationCrossTenantStaleVerification(BaseTest):
    def _build_ses_provider(self, tenants_for_domain: dict[str, list[str]] | None = None) -> SESProvider:
        patcher = patch("products.workflows.backend.providers.ses.boto3.client")
        patcher.start()
        self.addCleanup(patcher.stop)

        provider = SESProvider()
        provider.ses_client = MagicMock()
        provider.ses_v2_client = MagicMock()
        provider.sts_client = MagicMock()
        provider.sts_client.get_caller_identity.return_value = {"Account": "123456789012"}

        provider.ses_client.verify_domain_identity.return_value = {"VerificationToken": "tok"}
        provider.ses_client.verify_domain_dkim.return_value = {"DkimTokens": ["t1", "t2", "t3"]}
        provider.ses_client.set_identity_mail_from_domain.return_value = {}

        def _list_resource_tenants(ResourceArn: str) -> dict:
            domain = ResourceArn.split("/")[-1]
            return {"ResourceTenants": [{"TenantName": t} for t in (tenants_for_domain or {}).get(domain, [])]}

        provider.ses_v2_client.list_resource_tenants.side_effect = _list_resource_tenants
        return provider

    def _set_global_ses_success(self, provider, domain: str) -> None:
        provider.ses_client.get_identity_verification_attributes.return_value = {
            "VerificationAttributes": {domain: {"VerificationStatus": "Success"}}
        }
        provider.ses_client.get_identity_dkim_attributes.return_value = {
            "DkimAttributes": {domain: {"DkimVerificationStatus": "Success"}}
        }
        provider.ses_client.get_identity_mail_from_domain_attributes.return_value = {
            "MailFromDomainAttributes": {domain: {"MailFromDomainStatus": "Success"}}
        }

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_verify_email_domain_requires_team_tenant_association(self, mock_resolver_cls):
        provider = self._build_ses_provider(tenants_for_domain={"partner.com": ["team-1"]})
        self._set_global_ses_success(provider, "partner.com")
        dmarc_answer = MagicMock()
        dmarc_answer.strings = [b"v=DMARC1; p=none;"]
        mock_resolver_cls.return_value.resolve.return_value = [dmarc_answer]

        result_team_a = provider.verify_email_domain("partner.com", "feedback", team_id=1)
        result_team_b = provider.verify_email_domain("partner.com", "feedback", team_id=999)

        assert result_team_a["status"] == "success"
        assert result_team_b["status"] == "pending"

    @patch("products.workflows.backend.providers.SESProvider.delete_identity")
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_destroy_email_integration_deletes_ses_identity(self, mock_create_email_domain, mock_delete_identity):
        mock_create_email_domain.return_value = {"status": "success"}
        integration = EmailIntegration.create_native_integration(
            {"email": "owner@partner.com", "name": "Owner"},
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )

        with self.captureOnCommitCallbacks(execute=True):
            IntegrationViewSet().perform_destroy(integration)

        mock_delete_identity.assert_called_once_with("partner.com")
        assert not Integration.objects.filter(pk=integration.pk).exists()

    @patch("products.workflows.backend.providers.SESProvider.delete_identity")
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    @patch("products.workflows.backend.providers.SESProvider.get_mail_from_subdomain", return_value=None)
    def test_destroy_email_integration_skips_ses_delete_when_sibling_exists(
        self, _mock_get_mail_from, mock_create_email_domain, mock_delete_identity
    ):
        mock_create_email_domain.return_value = {"status": "success"}
        sibling_team = Team.objects.create(organization=self.organization, name="sibling team")
        EmailIntegration.create_native_integration(
            {"email": "sibling@partner.com", "name": "Sibling"},
            team_id=sibling_team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )
        integration = EmailIntegration.create_native_integration(
            {"email": "owner@partner.com", "name": "Owner"},
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )

        with self.captureOnCommitCallbacks(execute=True):
            IntegrationViewSet().perform_destroy(integration)

        assert mock_delete_identity.call_count == 0

    def test_create_email_domain_rejects_foreign_tenant_owner(self):
        provider = self._build_ses_provider(tenants_for_domain={"partner.com": ["team-1"]})

        with pytest.raises(Exception) as exc:
            provider.create_email_domain("partner.com", "feedback", team_id=999, org_team_ids=[999])
        assert "already associated with another organization" in str(exc.value)

    def test_create_email_domain_allows_sibling_team_in_same_org(self):
        provider = self._build_ses_provider(tenants_for_domain={"partner.com": ["team-1"]})

        provider.create_email_domain(
            "partner.com",
            "feedback",
            team_id=2,
            org_team_ids=[1, 2, 3, 4, 5],
        )

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.SESProvider.create_email_domain")
    def test_takeover_after_owner_deletes_integration_is_blocked(self, mock_create_email_domain, mock_resolver_cls):
        mock_create_email_domain.return_value = {"status": "success"}
        dmarc_answer = MagicMock()
        dmarc_answer.strings = [b"v=DMARC1; p=none;"]
        mock_resolver_cls.return_value.resolve.return_value = [dmarc_answer]

        org_a = Organization.objects.create(name="org a")
        team_a = Team.objects.create(organization=org_a, name="team a")
        org_b = Organization.objects.create(name="org b")
        team_b = Team.objects.create(organization=org_b, name="team b")

        integration_a = EmailIntegration.create_native_integration(
            {"email": "owner@partner.com", "name": "Owner A"},
            team_id=team_a.id,
            organization_id=str(org_a.id),
            created_by=self.user,
        )
        with patch("products.workflows.backend.providers.SESProvider.delete_identity") as mock_delete:
            with self.captureOnCommitCallbacks(execute=True):
                IntegrationViewSet().perform_destroy(integration_a)
            mock_delete.assert_called_once_with("partner.com")

        integration_b = EmailIntegration.create_native_integration(
            {"email": "attacker@partner.com", "name": "Attacker B"},
            team_id=team_b.id,
            organization_id=str(org_b.id),
            created_by=self.user,
        )

        provider = self._build_ses_provider(tenants_for_domain={"partner.com": []})
        self._set_global_ses_success(provider, "partner.com")

        email_b = EmailIntegration(integration_b)
        with patch("products.workflows.backend.providers.SESProvider", return_value=provider):
            result = email_b.verify()

        assert result["status"] == "pending"
        integration_b.refresh_from_db()
        assert integration_b.config.get("verified") is False

    def _build_ses_provider_that_keeps_mail_from_domains(self) -> tuple[SESProvider, dict[str, str]]:
        provider = self._build_ses_provider()
        mail_from_domains: dict[str, str] = {}

        def _set_mail_from(Identity: str, MailFromDomain: str, **_kwargs: object) -> dict:
            mail_from_domains[Identity] = MailFromDomain
            return {}

        def _get_mail_from(Identities: list[str]) -> dict:
            return {
                "MailFromDomainAttributes": {
                    identity: {"MailFromDomain": mail_from_domains[identity], "MailFromDomainStatus": "Pending"}
                    for identity in Identities
                    if identity in mail_from_domains
                }
            }

        ses_client = cast(MagicMock, provider.ses_client)
        ses_client.set_identity_mail_from_domain.side_effect = _set_mail_from
        ses_client.get_identity_mail_from_domain_attributes.side_effect = _get_mail_from
        return provider, mail_from_domains

    def _create_senders_in_two_teams(self) -> tuple[Integration, Integration]:
        other_team = Team.objects.create(organization=self.organization, name="other team")
        sender_a = EmailIntegration.create_native_integration(
            {"email": "a@partner.com", "name": "A"},
            team_id=self.team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )
        sender_b = EmailIntegration.create_native_integration(
            {"email": "b@partner.com", "name": "B"},
            team_id=other_team.id,
            organization_id=str(self.organization.id),
            created_by=self.user,
        )
        return sender_a, sender_b

    @patch("posthog.models.integration.email.reload_integrations_on_workers")
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_changing_the_mail_from_subdomain_moves_every_sender_on_the_domain(self, _mock_resolver_cls, _mock_reload):
        provider, mail_from_domains = self._build_ses_provider_that_keeps_mail_from_domains()

        with patch("products.workflows.backend.providers.SESProvider", return_value=provider):
            sender_a, sender_b = self._create_senders_in_two_teams()
            Integration.objects.filter(pk=sender_b.pk).update(config={**sender_b.config, "domain": "Partner.com"})
            EmailIntegration(sender_a).update_native_integration({"mail_from_subdomain": "bounces"}, self.team.id)

        assert mail_from_domains["partner.com"] == "bounces.partner.com"
        sender_b.refresh_from_db()
        assert sender_b.config["mail_from_subdomain"] == "bounces"

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    def test_verifying_a_sender_with_a_stale_mail_from_subdomain_keeps_the_one_ses_uses(self, _mock_resolver_cls):
        provider, mail_from_domains = self._build_ses_provider_that_keeps_mail_from_domains()

        with patch("products.workflows.backend.providers.SESProvider", return_value=provider):
            sender_a, sender_b = self._create_senders_in_two_teams()
            Integration.objects.filter(pk=sender_a.pk).update(
                config={**sender_a.config, "mail_from_subdomain": "bounces"}
            )
            mail_from_domains["partner.com"] = "bounces.partner.com"
            result = EmailIntegration(sender_b).verify()

        assert mail_from_domains["partner.com"] == "bounces.partner.com"
        assert {record["recordHostname"] for record in result["dnsRecords"] if record["type"] == "mail_from"} == {
            "bounces.partner.com"
        }
        sender_b.refresh_from_db()
        assert sender_b.config["mail_from_subdomain"] == "bounces"

    def test_aws_account_id_is_looked_up_once_across_providers(self):
        cache.delete(AWS_ACCOUNT_ID_CACHE_KEY)
        providers = [self._build_ses_provider(), self._build_ses_provider()]
        for provider in providers:
            provider.sts_client.get_caller_identity.reset_mock()

        for provider in providers:
            provider._identity_arn("partner.com")
            provider._identity_arn("other.com")

        assert sum(provider.sts_client.get_caller_identity.call_count for provider in providers) == 1
