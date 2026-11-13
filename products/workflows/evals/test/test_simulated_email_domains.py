from __future__ import annotations

from collections.abc import Callable
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership

from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.workflows.evals.scorers import APPLY_URL_PATH
from products.workflows.evals.seeders import (
    CLAIMED_DOMAIN_SENDER,
    DOMAIN_CONNECT_SENDER,
    MANUAL_SENDER,
    MEMBER_SENDER,
    SHARED_DOMAIN_SENDER,
    VERIFIED_SENDER,
    domain_of,
    seed_claimed_domain,
    seed_member_without_admin,
    seed_shared_domain_sender,
    seed_verified_sender,
)
from products.workflows.evals.simulated_email_domains import ses_records, simulated_email_domains


class TestEvalCasesThroughTheApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(simulated_email_domains())
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))

    def _post_sender(self, address: str) -> Any:
        return self.client.post(
            f"/api/environments/{self.team.pk}/integrations",
            {"kind": "email", "config": {"email": address, "name": "Hedgebox", "provider": "ses"}},
            format="json",
        )

    def _create_sender(self, address: str) -> int:
        response = self._post_sender(address)
        assert response.status_code == 201, response.json()
        return response.json()["id"]

    def _status(self, integration_id: int) -> dict:
        response = self.client.get(
            f"/api/environments/{self.team.pk}/integrations/{integration_id}/email/status", {"refresh": "true"}
        )
        assert response.status_code == 200, response.json()
        return response.json()

    def _context(self) -> CustomPromptSandboxContext:
        return CustomPromptSandboxContext(team_id=self.team.pk, user_id=self.user.pk)

    def test_domain_connect_case_hands_back_an_apply_url(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        integration_id = self._create_sender(DOMAIN_CONNECT_SENDER)
        verify = self.client.post(f"/api/environments/{self.team.pk}/integrations/{integration_id}/email/verify")
        check = self.client.get(
            f"/api/environments/{self.team.pk}/integrations/domain-connect/check",
            {"domain": domain_of(DOMAIN_CONNECT_SENDER)},
        )
        apply_url = self.client.post(
            f"/api/environments/{self.team.pk}/integrations/domain-connect/apply-url",
            {"context": "email", "integration_id": integration_id},
            format="json",
        )

        assert verify.json()["status"] == "pending"
        assert check.json()["supported"] is True
        assert apply_url.status_code == 200, apply_url.json()
        assert apply_url.json()["url"].startswith(APPLY_URL_PATH)

    def test_a_new_sender_reads_the_records_the_case_expects(self) -> None:
        status = self._status(self._create_sender(MANUAL_SENDER))

        assert status["status"] == "pending"
        assert {(record["hostname"], record["type"], record["value"]) for record in status["records"]} == {
            (record.name, record.record_type, record.value) for record in ses_records(domain_of(MANUAL_SENDER))
        }

    @parameterized.expand(
        [
            ("feedback_mail_from", seed_verified_sender, VERIFIED_SENDER),
            ("custom_mail_from", seed_shared_domain_sender, SHARED_DOMAIN_SENDER),
        ]
    )
    def test_a_seeded_verified_sender_reads_as_verified(
        self, _name: str, seed: Callable[[CustomPromptSandboxContext], dict[str, Any]], sender: str
    ) -> None:
        status = self._status(seed(self._context())["integration_id"])

        assert status["status"] == "verified", status
        assert domain_of(sender) in {record["hostname"] for record in status["records"]}

    def test_a_member_reaches_verify_and_is_refused(self) -> None:
        seed_member_without_admin(self._context())
        integration_id = self._create_sender(MEMBER_SENDER)
        status = self._status(integration_id)
        verify = self.client.post(f"/api/environments/{self.team.pk}/integrations/{integration_id}/email/verify")

        assert status["status"] == "verified", status
        assert verify.status_code == 403, verify.json()

    def test_a_domain_claimed_by_another_organization_is_refused(self) -> None:
        seed_claimed_domain(self._context())
        response = self._post_sender(CLAIMED_DOMAIN_SENDER)

        assert response.status_code == 400
        assert "another organization" in str(response.json())
