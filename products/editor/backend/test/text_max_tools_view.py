from unittest.mock import patch
from rest_framework import status
from ee.hogai.utils.types import AssistantMode, PartialAssistantState
from posthog.schema import HumanMessage
from posthog.test.base import APIBaseTest
from posthog.auth import PersonalAPIKeyAuthentication
from ee.models.assistant import Conversation


class TestMaxToolsViewSet(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.patcher = patch.object(PersonalAPIKeyAuthentication, "authenticate")
        self.mock_auth = self.patcher.start()
        self.mock_auth.return_value = (self.user, None)
        self.client.force_login(self.user)

    def tearDown(self):
        super().tearDown()
        self.patcher.stop()

    @patch("products.editor.backend.api.max_tools.Assistant")
    def test_insights_tool_call_success(self, mock_assistant):
        data = {
            "project_id": self.team.id,
            "query_description": "Show me user signups over time",
            "query_type": "trends",
        }

        # Mock the stream method to return an iterable
        mock_assistant.return_value.stream.return_value = iter(["test response"])

        response = self.client.post("/api/max_tools/insights", data=data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/event-stream")

        # Verify Assistant was called with correct params
        mock_assistant.assert_called_once()
        call_args = mock_assistant.call_args[0]
        self.assertEqual(call_args[0], self.team)  # team
        self.assertIsInstance(call_args[1], Conversation)  # conversation
        call_kwargs = mock_assistant.call_args[1]
        self.assertEqual(call_kwargs["new_message"], HumanMessage(content="Show me user signups over time"))  # message
        self.assertEqual(call_kwargs["user"], self.user)  # user
        self.assertEqual(call_kwargs["is_new_conversation"], False)  # is_new_conversation
        self.assertEqual(call_kwargs["mode"], AssistantMode.INSIGHTS_TOOL)  # mode
        self.assertIsInstance(call_kwargs["tool_call_partial_state"], PartialAssistantState)
        self.assertEqual(
            call_kwargs["tool_call_partial_state"].root_tool_insight_plan, "Show me user signups over time"
        )
        self.assertEqual(call_kwargs["tool_call_partial_state"].root_tool_insight_type, "trends")
        mock_assistant.return_value.stream.assert_called_once()

    def test_insights_tool_call_invalid_query_type(self):
        data = {
            "project_id": self.team.id,
            "query_description": "Show me user signups over time",
            "query_type": "invalid_type",  # Invalid query type
        }

        response = self.client.post("/api/max_tools/insights", data=data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
