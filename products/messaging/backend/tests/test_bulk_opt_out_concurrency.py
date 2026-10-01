import time
import threading
from typing import Any

from posthog.test.base import NonAtomicAPIBaseTest

from django.db import connection, transaction

from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)

DEADLINE_SECONDS = 30


def another_backend_waits_on_a_lock() -> bool:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_locks WHERE NOT granted AND pid <> pg_backend_pid() "
                "AND (database IS NULL OR database = (SELECT oid FROM pg_database WHERE datname = current_database()))"
            )
            if cursor.fetchone()[0] > 0:
                return True
        time.sleep(0.05)
    return False


class TestBulkOptOutConcurrency(NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def test_bulk_opt_out_succeeds_when_another_request_creates_the_recipient_first(self) -> None:
        identifier = "user@example.com"
        inserted = threading.Event()
        commit_allowed = threading.Event()
        outcome: dict[str, Any] = {}

        def create_recipient_and_hold_the_commit() -> None:
            try:
                with transaction.atomic():
                    MessageRecipientPreference.objects.create(
                        team=self.team, identifier=identifier, preferences={"product": PreferenceStatus.OPTED_OUT}
                    )
                    inserted.set()
                    commit_allowed.wait(DEADLINE_SECONDS)
            finally:
                connection.close()

        def bulk_opt_out() -> None:
            try:
                outcome["response"] = self.client.post(
                    f"/api/environments/{self.team.id}/messaging_preferences/bulk_add_opt_outs/",
                    {"opt_outs": [{"identifier": identifier}]},
                    format="json",
                )
            except Exception as error:
                outcome["error"] = error
            finally:
                connection.close()

        creator = threading.Thread(target=create_recipient_and_hold_the_commit)
        creator.start()
        self.assertTrue(inserted.wait(DEADLINE_SECONDS))
        requester = threading.Thread(target=bulk_opt_out)
        requester.start()
        try:
            self.assertTrue(another_backend_waits_on_a_lock(), "the bulk request did not wait on the new recipient")
        finally:
            commit_allowed.set()
            creator.join(DEADLINE_SECONDS)
            requester.join(DEADLINE_SECONDS)

        self.assertNotIn("error", outcome)
        self.assertEqual(outcome["response"].status_code, 200, outcome["response"].content)
        preference = MessageRecipientPreference.objects.get(team=self.team, identifier=identifier)
        self.assertEqual(
            preference.preferences,
            {"product": PreferenceStatus.OPTED_OUT, ALL_MESSAGE_PREFERENCE_CATEGORY_ID: PreferenceStatus.OPTED_OUT},
        )
