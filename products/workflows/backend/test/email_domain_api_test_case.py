from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team

from products.workflows.backend.test.fakes.world import EmailDomainWorld

DOMAIN = "mail.example.com"
ROOT_DOMAIN = "example.com"
ZONE_NAMESERVERS = {"ns1.example-dns.net": "34.120.0.1", "ns2.example-dns.net": "34.120.0.2"}
ALL_KINDS = ("verification", "dkim", "spf", "mail_from_mx", "mail_from_spf", "dmarc")


@override_settings(SES_REGION="us-east-1", SES_TENANT_CONFIGURATION_SETS=[])
class EmailDomainApiTestCase(APIBaseTest):
    zone_nameservers: dict[str, str] = ZONE_NAMESERVERS

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.world = self.enterContext(EmailDomainWorld().installed())
        self.world.dns.add_zone(ROOT_DOMAIN, nameservers=self.zone_nameservers)
        self.reload_workers = self.enterContext(
            patch("posthog.models.integration.email.reload_integrations_on_workers")
        )
        self.report_user_action = self.enterContext(patch("posthog.api.integration.report_user_action"))

    def create_sender(self, email: str, *, team: Team | None = None) -> int:
        response = self.client.post(
            f"/api/projects/{(team or self.team).id}/integrations",
            {"kind": "email", "config": {"email": email, "name": "Example", "provider": "ses"}},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def get_status(self, integration_id: int, *, refresh: bool = True) -> Any:
        return self.client.get(
            f"/api/projects/{self.team.id}/integrations/{integration_id}/email/status",
            {"refresh": str(refresh).lower()},
        )

    def status_body(self, integration_id: int, *, refresh: bool = True) -> dict[str, Any]:
        response = self.get_status(integration_id, refresh=refresh)
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def records_to_publish(self, integration_id: int, *, domain: str = DOMAIN) -> list[dict[str, Any]]:
        identity = self.world.ses.identities[domain]
        identity.checks_paused = True
        records = self.status_body(integration_id)["records"]
        identity.checks_paused = False
        return records

    def publish(self, records: list[dict[str, Any]], *kinds: str) -> None:
        for record in records:
            if record["kind"] in kinds:
                self.world.publish_record(record)

    def is_verified(self, integration_id: int) -> bool:
        return Integration.objects.get(id=integration_id).config["verified"]

    def verified_events(self) -> list[Any]:
        return [call for call in self.report_user_action.call_args_list if call.args[1] == "email domain verified"]

    def verified_event_methods(self) -> list[str]:
        return [call.args[2]["method"] for call in self.verified_events()]


def record_statuses(body: dict[str, Any]) -> dict[str, list[str]]:
    statuses: dict[str, list[str]] = {}
    for record in body["records"]:
        statuses.setdefault(record["kind"], []).append(record["status"])
    return statuses


def step_states(body: dict[str, Any]) -> list[str]:
    return [step["state"] for step in body["steps"]]
