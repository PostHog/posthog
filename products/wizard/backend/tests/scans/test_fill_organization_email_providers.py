from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.utils import timezone

import posthoganalytics

from posthog.models import Organization, Team

from products.wizard.backend.models import WizardDetectedTool

COMMAND = "fill_organization_email_providers"


class FakeClient:
    sent: dict[str, list[str]] = {}
    failing_from: int | None = None

    def __init__(self, *args: Any, on_error: Callable[[Exception, list], None], **kwargs: Any) -> None:
        self.on_error = on_error
        self.queued: dict[str, list[str]] = {}

    def group_identify(self, group_type: str, group_key: str, properties: dict[str, Any]) -> str:
        assert group_type == "organization"
        self.queued[group_key] = properties["email_providers"]
        return "event-uuid"

    def flush(self, timeout_seconds: float | None) -> None:
        if self.failing_from is not None and len(self.sent) >= self.failing_from:
            self.on_error(Exception("capture is down"), [])
            return
        self.sent.update(self.queued)
        self.queued = {}

    def shutdown(self) -> None:
        pass


@pytest.fixture
def organizations() -> dict[str, list[str]]:
    now = timezone.now()
    expected = {}
    for index, kinds in enumerate([["Resend", "SendGrid"], ["Postmark"], ["Loops"], ["Stripe"]]):
        organization = Organization.objects.create(name=f"organization {index}")
        for kind in kinds:
            team = Team.objects.create_with_data(initiating_user=None, organization=organization)
            WizardDetectedTool.objects.for_team(team.id).create(
                team=team, workspace_fingerprint="w", kind=kind, first_seen_at=now, last_seen_at=now, removed_at=now
            )
        if kinds != ["Stripe"]:
            expected[str(organization.id)] = kinds
    return expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "arguments, sent, failing_from, error",
    [
        ([], 0, None, None),
        (["--apply"], 3, None, None),
        (["--apply", "--limit", "2"], 2, None, None),
        (["--apply"], 1, 1, "capture is down"),
    ],
    ids=["dry_run", "apply", "limit", "failed_send"],
)
def test_sends_the_stored_email_providers_of_each_organization(
    organizations: dict[str, list[str]], arguments: list[str], sent: int, failing_from: int | None, error: str | None
) -> None:
    with (
        patch.object(posthoganalytics, "Client", FakeClient),
        patch.object(posthoganalytics, "disabled", False),
        patch.object(FakeClient, "sent", {}),
        patch.object(FakeClient, "failing_from", failing_from),
        patch(f"products.wizard.backend.management.commands.{COMMAND}.BATCH_SIZE", 1),
    ):
        if error:
            with pytest.raises(CommandError, match=error):
                call_command(COMMAND, *arguments)
        else:
            call_command(COMMAND, *arguments)

        # Organizations are sent in id order.
        assert FakeClient.sent == {key: organizations[key] for key in sorted(organizations)[:sent]}
