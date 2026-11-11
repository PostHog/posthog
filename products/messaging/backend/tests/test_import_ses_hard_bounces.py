from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.utils import timezone

from botocore.exceptions import ClientError

from products.messaging.backend.models.email_hard_bounce import GLOBAL_HARD_BOUNCE_MAX_HOLD, EmailHardBounce


class FakeSesSuppressionList:
    """The SESv2 account-level suppression list. Like SES, it may return fewer entries than PageSize, so a small
    list still spans pages. A client stuck on one page gets SES's throttling error rather than looping forever."""

    RESPONSE_PAGE_SIZE = 2
    STUCK_CLIENT_REQUEST_LIMIT = 20

    def __init__(self, entries: list[tuple[str, str]]) -> None:
        self._entries = entries
        self._requests = 0

    def list_suppressed_destinations(
        self, *, Reasons: list[str] | None = None, PageSize: int | None = None, NextToken: str | None = None
    ) -> dict[str, Any]:
        self._requests += 1
        if self._requests > self.STUCK_CLIENT_REQUEST_LIMIT:
            raise ClientError({"Error": {"Code": "TooManyRequestsException"}}, "ListSuppressedDestinations")
        matching = [(email, reason) for email, reason in self._entries if not Reasons or reason in Reasons]
        if NextToken is not None and not NextToken.startswith("offset-"):
            raise ClientError({"Error": {"Code": "InvalidNextTokenException"}}, "ListSuppressedDestinations")
        start = int(NextToken.removeprefix("offset-")) if NextToken else 0
        end = start + min(PageSize or self.RESPONSE_PAGE_SIZE, self.RESPONSE_PAGE_SIZE)
        response: dict[str, Any] = {
            "SuppressedDestinationSummaries": [
                {"EmailAddress": email, "Reason": reason} for email, reason in matching[start:end]
            ]
        }
        if end < len(matching):
            response["NextToken"] = f"offset-{end}"
        return response


class TestImportSesHardBounces(BaseTest):
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_imports_every_page_and_keeps_existing_entries(self, client_factory: MagicMock) -> None:
        bounced_at = timezone.now() - timedelta(days=3)
        EmailHardBounce.objects.create(
            email="known@example.com", first_bounced_at=bounced_at, last_bounced_at=bounced_at
        )
        client_factory.return_value = FakeSesSuppressionList(
            [
                ("First@Example.com", "BOUNCE"),
                ("complained@example.com", "COMPLAINT"),
                ("known@example.com", "BOUNCE"),
                ("second@example.com", "BOUNCE"),
            ]
        )

        call_command("import_ses_hard_bounces")

        rows = {row.email: row.first_bounced_at for row in EmailHardBounce.objects.all()}
        assert sorted(rows) == ["first@example.com", "known@example.com", "second@example.com"]
        assert rows["known@example.com"] == bounced_at
        imported = EmailHardBounce.objects.get(email="first@example.com")
        assert imported.last_bounced_at - imported.first_bounced_at == GLOBAL_HARD_BOUNCE_MAX_HOLD
