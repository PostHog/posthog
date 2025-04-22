from typing import Any
from uuid import uuid4

from ee.hogai.tool import MaxTool
from pydantic import BaseModel, Field

from posthog.models.dashboard import Dashboard, DashboardTile
from posthog.models.user import User
from django.utils.timezone import now

from ee.hogai.assistant import Assistant
from ee.hogai.utils.types import AssistantMode
from ee.models.assistant import Conversation

from posthog.api.insight import InsightSerializer
import structlog


# Define the arguments schema for the tool
class CreateInsightForDashboardArgs(BaseModel):
    description: str = Field(description="A natural language description of the insight you want to create")


# Custom request class for the serializer
class DummyRequest:
    def __init__(self, user):
        self.user = user
        self.headers = {}


logger = structlog.get_logger(__name__)


class CreateInsightForDashboardTool(MaxTool):
    name: str = "create_insight_for_dashboard"
    description: str = "Create and add a new insight to this dashboard based on your description"
    thinking_message: str = "Creating your insight"
    root_system_prompt_template: str = "Current dashboard ID: {dashboard_id}"
    args_schema: type[BaseModel] = CreateInsightForDashboardArgs

    def _run_impl(self, description: str) -> tuple[str, Any]:
        """Implements the tool functionality to create an insight and add it to a dashboard."""
        # Extract context
        if "dashboard_id" not in self.context:
            raise ValueError("Dashboard ID is required in the context")

        dashboard_id = self.context["dashboard_id"]

        # Get the current team and user
        team_id = self._team_id
        if not team_id:
            raise ValueError("Team ID is required")

        # Get the dashboard
        try:
            dashboard = Dashboard.objects.get(id=dashboard_id, team_id=team_id)
        except Dashboard.DoesNotExist:
            return "❌ Dashboard not found", None

        # Get the user
        user = User.objects.get(id=self.context.get("user_id")) if "user_id" in self.context else None

        if not user:
            # Try to get the first staff user as fallback
            user = User.objects.filter(is_staff=True).first()
            if not user:
                raise ValueError("No valid user found to create the insight")

        # Create a conversation
        conversation = Conversation.objects.create(user=user, team=dashboard.team, type=Conversation.Type.TOOL_CALL)

        # Create a human message
        human_message_content = f"Create an insight for my dashboard that shows {description}"

        # Create an assistant instance with the InsightsAssistantGraph
        assistant = Assistant(
            team=dashboard.team,
            conversation=conversation,
            new_message={"content": human_message_content, "id": str(uuid4())},
            user=user,
            mode=AssistantMode.INSIGHTS_TOOL,
            is_new_conversation=True,
            trace_id=str(uuid4()),
        )

        try:
            # Use invoke() instead of stream() to get the final result
            logger.debug("invoking_insights_assistant_graph", description=description, dashboard_id=dashboard_id)
            result = assistant.invoke()

            # Extract query data from the result
            query_data = {}
            insight_name = ""
            insight_description = ""

            # Process the results to find the query details
            if isinstance(result, dict) and "messages" in result:
                for message in result.get("messages", []):
                    if isinstance(message, dict) and "ui_payload" in message:
                        payload = message.get("ui_payload", {})
                        if "query" in payload:
                            query_data = payload["query"]
                        if "insight_name" in payload:
                            insight_name = payload["insight_name"]
                        if "description" in payload:
                            insight_description = payload["description"]

            # If we didn't get a name from the assistant, use a default
            if not insight_name:
                insight_name = f"Insight for: {description[:50]}"

            # Prepare the insight data
            insight_data = {
                "name": insight_name,
                "description": insight_description if insight_description else f"Generated insight for: {description}",
                "team_id": team_id,
                "created_by": user,
                "last_modified_by": user,
                "saved": True,
                "filters": query_data,
            }

            # Create a dummy request for the serializer
            dummy_request = DummyRequest(user)

            # Use the serializer context
            context = {"request": dummy_request, "team_id": team_id}
            serializer = InsightSerializer(data=insight_data, context=context)

            # Validate and save the insight
            serializer.is_valid(raise_exception=True)
            insight = serializer.create(serializer.validated_data)

            # Add the insight to the dashboard
            DashboardTile.objects.create(insight=insight, dashboard=dashboard, last_refresh=now())

            # Create a user-friendly response
            response = f"✅ Created '{insight.name}' and added it to the dashboard."

            # Return both the success message and the insight details for frontend handling
            return response, {
                "insight_id": insight.id,
                "short_id": insight.short_id,
                "name": insight.name,
                "description": insight.description,
                "dashboard_id": dashboard_id,
            }
        except Exception as e:
            logger.exception("error_creating_insight_from_graph", error=str(e), dashboard_id=dashboard_id)
            # If anything goes wrong with creating the insight, return an error
            return f"❌ Error creating insight: {str(e)}", None
