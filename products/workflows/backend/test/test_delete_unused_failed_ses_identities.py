from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings

from parameterized import parameterized

from posthog.models.integration import Integration

from products.workflows.backend.providers import SESProvider
from products.workflows.backend.tests.fakes.world import EmailDomainWorld


@override_settings(SES_REGION="us-east-1")
class TestDeleteUnusedFailedSesIdentities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.world = self.enterContext(EmailDomainWorld().installed())
        self.world.ses.add_identity("orphan.com", forced_verification_status="Failed")
        self.world.ses.associate("orphan.com", "team-1")
        self.world.ses.add_identity("used.com", forced_verification_status="Failed")
        self.world.ses.add_identity("waiting.com")
        Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id="sender@used.com",
            config={"domain": "used.com", "provider": "ses", "verified": False},
        )

    @parameterized.expand(
        [
            ("dry_run", [], {"orphan.com", "used.com", "waiting.com"}),
            ("apply", ["--apply"], {"used.com", "waiting.com"}),
        ]
    )
    def test_deletes_only_failed_identities_that_no_sender_uses(
        self, _name: str, args: list[str], remaining: set[str]
    ) -> None:
        out = StringIO()

        call_command("delete_unused_failed_ses_identities", *args, "--pace-seconds", "0", stdout=out)

        assert set(self.world.ses.identities) == remaining
        assert "orphan.com" in out.getvalue()
        assert "used.com" not in out.getvalue()

    def test_keeps_an_identity_whose_domain_gets_a_sender_after_the_listing(self) -> None:
        list_failed = SESProvider.list_failed_domain_identities

        def list_then_add_sender(provider: SESProvider) -> list[str]:
            failed = list_failed(provider)
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id="new@orphan.com",
                config={"domain": "orphan.com", "provider": "ses", "verified": False},
            )
            return failed

        with patch.object(SESProvider, "list_failed_domain_identities", list_then_add_sender):
            call_command("delete_unused_failed_ses_identities", "--apply", "--pace-seconds", "0", stdout=StringIO())

        assert "orphan.com" in self.world.ses.identities
