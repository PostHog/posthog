from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models import Team

from products.messaging.backend.facade.preferences import (
    PreferenceLinkRevoked,
    erase_recipient,
    get_or_create_recipient,
)
from products.messaging.backend.facade.tasks import delete_expired_recipient_erasures
from products.messaging.backend.models.message_recipient_erasure import MessageRecipientErasure


class TestDeleteExpiredRecipientErasures(BaseTest):
    def test_deletes_only_erasures_older_than_every_link_they_revoke(self):
        now = timezone.now()
        for identifier_hash, age_days in (("expired", 62), ("live", 60.5)):
            MessageRecipientErasure.objects.for_team(self.team.id).create(
                team_id=self.team.id, identifier_hash=identifier_hash, erased_at=now - timedelta(days=age_days)
            )

        delete_expired_recipient_erasures()

        self.assertEqual(
            list(MessageRecipientErasure.objects.unscoped().values_list("identifier_hash", flat=True)), ["live"]
        )


class TestRecipientErasureInChildEnvironment(BaseTest):
    def test_repeated_erase_revokes_only_the_child_environments_links(self):
        child = Team.objects.create(organization=self.organization, name="Child", parent_team=self.team)
        minted_before = timezone.now() - timedelta(minutes=5)

        erase_recipient(child.id, "child@example.com", confirm_complaints=False)
        erase_recipient(child.id, "child@example.com", confirm_complaints=False)

        with self.assertRaises(PreferenceLinkRevoked):
            get_or_create_recipient(child.id, "child@example.com", link_issued_at=minted_before)
        get_or_create_recipient(self.team.id, "child@example.com", link_issued_at=minted_before)
