from __future__ import annotations

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog import domain_connect
from posthog.models.organization import OrganizationMembership

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.workflows.backend import providers
from products.workflows.evals.scorers import APPLY_URL_PATH
from products.workflows.evals.seeders import DOMAIN_CONNECT_SENDER, seed_domain_connect_support
from products.workflows.evals.simulated_email_domains import (
    DOMAIN_CONNECT_ROOT_DOMAIN,
    SimulatedEmailDomains,
    publish_domain_connect_support,
    ses_records,
    simulated_email_domains,
)

DOMAIN = "mail.unit.example.com"
TEAM_ID = 101


def _records_by_name(records: list) -> dict[tuple[str, str], str]:
    return {(record["recordHostname"], record["recordType"]): record["status"] for record in records}


@pytest.mark.parametrize(
    "published_label,expected_status",
    [
        (None, "pending"),
        ("feedback", "success"),
        ("bounce", "pending"),
    ],
)
def test_verify_status_follows_published_records(published_label: str | None, expected_status: str) -> None:
    domains = SimulatedEmailDomains()
    if published_label:
        domains.publish(ses_records(DOMAIN, published_label))
    domains.associate(TEAM_ID, DOMAIN)

    with simulated_email_domains(domains):
        result = providers.SESProvider().verify_email_domain(DOMAIN, mail_from_subdomain="feedback", team_id=TEAM_ID)

    assert result["status"] == expected_status
    issued = {(record.name if record.name != DOMAIN else "@", record.record_type) for record in ses_records(DOMAIN)}
    assert set(_records_by_name(result["dnsRecords"])) == issued


def test_create_refuses_a_domain_another_organization_uses_but_not_another_trial() -> None:
    domains = SimulatedEmailDomains()
    with simulated_email_domains(domains):
        providers.SESProvider().create_email_domain(DOMAIN, mail_from_subdomain="feedback", team_id=TEAM_ID)
        providers.SESProvider().create_email_domain(DOMAIN, mail_from_subdomain="feedback", team_id=TEAM_ID + 1)

        domains.claim_for_other_organization(DOMAIN)
        with pytest.raises(ValidationError, match="another organization"):
            providers.SESProvider().create_email_domain(DOMAIN, mail_from_subdomain="feedback", team_id=TEAM_ID)


@pytest.mark.parametrize(
    "root_domain,supported",
    [
        (DOMAIN_CONNECT_ROOT_DOMAIN, True),
        ("example.com", False),
    ],
)
def test_domain_connect_is_supported_only_where_published(root_domain: str, supported: bool) -> None:
    domains = SimulatedEmailDomains()
    publish_domain_connect_support(domains)

    with simulated_email_domains(domains):
        discovery = domain_connect.discover_domain_connect(root_domain)

    assert (discovery is not None) is supported


class TestEvalCasesThroughTheApi(APIBaseTest):
    def _create_sender(self, address: str, **config: str) -> int:
        response = self.client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "email", "config": {"email": address, "name": "Hedgebox", "provider": "ses", **config}},
            format="json",
        )
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _verify(self, integration_id: int) -> str:
        response = self.client.post(f"/api/environments/{self.team.pk}/integrations/{integration_id}/email/verify")
        assert response.status_code == 200, response.json()
        return response.json()["status"]

    def _context(self) -> CustomPromptSandboxContext:
        return CustomPromptSandboxContext(team_id=self.team.pk, user_id=self.user.pk)

    def test_domain_connect_case_hands_back_an_apply_url(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        seed_domain_connect_support(self._context())
        with simulated_email_domains(), patch("posthoganalytics.feature_enabled", return_value=True):
            integration_id = self._create_sender(DOMAIN_CONNECT_SENDER)
            assert self._verify(integration_id) == "pending"
            check = self.client.get(
                f"/api/environments/{self.team.pk}/integrations/domain-connect/check",
                {"domain": DOMAIN_CONNECT_SENDER.split("@")[1]},
            )
            apply_url = self.client.post(
                f"/api/environments/{self.team.pk}/integrations/domain-connect/apply-url",
                {"context": "email", "integration_id": integration_id},
                format="json",
            )

        assert check.json()["supported"] is True
        assert apply_url.status_code == 200, apply_url.json()
        assert apply_url.json()["url"].startswith(APPLY_URL_PATH)
