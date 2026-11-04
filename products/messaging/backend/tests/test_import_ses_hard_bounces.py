from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.utils import timezone

from products.messaging.backend.models.email_hard_bounce import EmailHardBounce


class TestImportSesHardBounces(BaseTest):
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_imports_every_page_and_keeps_existing_entries(self, client_factory: MagicMock) -> None:
        bounced_at = timezone.now() - timezone.timedelta(days=3)
        EmailHardBounce.objects.create(
            email="known@example.com", first_bounced_at=bounced_at, last_bounced_at=bounced_at
        )
        client_factory.return_value.list_suppressed_destinations.side_effect = [
            {
                "SuppressedDestinationSummaries": [
                    {"EmailAddress": "First@Example.com"},
                    {"EmailAddress": "known@example.com"},
                ],
                "NextToken": "page-2",
            },
            {"SuppressedDestinationSummaries": [{"EmailAddress": "second@example.com"}]},
        ]

        call_command("import_ses_hard_bounces")

        rows = {row.email: row.first_bounced_at for row in EmailHardBounce.objects.all()}
        assert sorted(rows) == ["first@example.com", "known@example.com", "second@example.com"]
        assert rows["known@example.com"] == bounced_at
        calls = client_factory.return_value.list_suppressed_destinations.call_args_list
        assert [call.kwargs for call in calls] == [
            {"Reasons": ["BOUNCE"], "PageSize": 1000},
            {"Reasons": ["BOUNCE"], "PageSize": 1000, "NextToken": "page-2"},
        ]
