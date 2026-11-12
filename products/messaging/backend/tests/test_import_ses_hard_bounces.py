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
    def test_imports_every_page_and_renews_lapsed_entries(self, client_factory: MagicMock) -> None:
        lapsed_at = timezone.now() - timedelta(days=3)
        EmailHardBounce.objects.create(email="known@example.com", first_bounced_at=lapsed_at, last_bounced_at=lapsed_at)
        long_bouncing_since = timezone.now() - timedelta(days=60)
        EmailHardBounce.objects.create(
            email="old@example.com", first_bounced_at=long_bouncing_since, last_bounced_at=lapsed_at
        )
        client_factory.return_value = FakeSesSuppressionList(
            [
                ("First@Example.com", "BOUNCE"),
                ("complained@example.com", "COMPLAINT"),
                ("known@example.com", "BOUNCE"),
                ("old@example.com", "BOUNCE"),
                ("second@example.com", "BOUNCE"),
            ]
        )

        call_command("import_ses_hard_bounces")

        rows = {row.email: row for row in EmailHardBounce.objects.all()}
        assert sorted(rows) == ["first@example.com", "known@example.com", "old@example.com", "second@example.com"]
        for email in ("first@example.com", "known@example.com"):
            assert rows[email].last_bounced_at > lapsed_at
            assert rows[email].last_bounced_at - rows[email].first_bounced_at == GLOBAL_HARD_BOUNCE_MAX_HOLD
        assert rows["old@example.com"].first_bounced_at == long_bouncing_since
        assert rows["old@example.com"].last_bounced_at > lapsed_at
