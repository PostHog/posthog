from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.posthog_ai.backend.sandbox_followup import lock_conversation_for_followup

from ee.models.assistant import Conversation


class TestSandboxFollowup(APIBaseTest):
    def test_lock_acquires_select_for_update_on_conversation(self):
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with patch("products.posthog_ai.backend.sandbox_followup.Conversation.objects") as mock_objects:
            mock_sfu = mock_objects.select_for_update.return_value
            mock_sfu.get.return_value = conversation

            with lock_conversation_for_followup(str(conversation.id), self.team.id) as locked:
                self.assertEqual(locked, conversation)

        mock_objects.select_for_update.assert_called_once_with()
        mock_sfu.get.assert_called_once_with(id=str(conversation.id), team_id=self.team.id)

    def test_lock_yields_the_conversation_row(self):
        conversation = Conversation.objects.create(user=self.user, team=self.team)

        with lock_conversation_for_followup(str(conversation.id), self.team.id) as locked:
            self.assertEqual(locked.id, conversation.id)
