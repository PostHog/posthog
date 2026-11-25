from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

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
