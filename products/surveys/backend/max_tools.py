"""
MaxTool for AI-powered survey creation.
"""

from typing import Any

import django.utils.timezone

from asgiref.sync import async_to_sync
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import SurveyCreationSchema

from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, Survey, Team, User

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.tool import MaxTool

from .prompts import SURVEY_CREATION_SYSTEM_PROMPT


class SurveyCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the survey to create")


def get_team_survey_config(team: Team) -> dict[str, Any]:
    """Get team survey configuration for context."""
    survey_config = getattr(team, "survey_config", {}) or {}
    return {
        "appearance": survey_config.get("appearance", {}),
        "default_settings": {"type": "popover", "enable_partial_responses": True},
    }


class CreateSurveyTool(MaxTool):
    name: str = "create_survey"
    description: str = "Create and optionally launch a survey based on natural language instructions"
    thinking_message: str = "Creating your survey"

    args_schema: type[BaseModel] = SurveyCreatorArgs

    async def _create_survey_from_instructions(self, instructions: str) -> SurveyCreationSchema:
        """
        Create a survey from natural language instructions.
        """

        graph = FeatureFlagLookupGraph(team=self._team, user=self._user)

        graph_context = {
            "change": f"Create a survey based on these instructions: {instructions}",
            "output": None,
            "tool_progress_messages": [],
            **self.context,
        }

        result = await graph.compile_full_graph().ainvoke(graph_context)

        if isinstance(result["output"], SurveyCreationSchema):
            return result["output"]
        else:
            survey_creation_schema = SurveyCreationSchema(
                questions=[], should_launch=False, name="", description="", type="popover"
            )
            capture_exception(
                Exception(f"Survey creation graph returned unexpected output type: {type(result.get('output'))}"),
                {"team_id": self._team.id, "user_id": self._user.id, "result": str(result)},
            )
            return survey_creation_schema

    async def _arun_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """
        Generate survey configuration from natural language instructions.
        """
        try:
            user = self._user
            team = self._team

            result = await self._create_survey_from_instructions(instructions)

            try:
                if not result.questions:
                    return "❌ Survey must have at least one question", {
                        "error": "validation_failed",
                        "details": "No questions provided",
                    }

                # Apply appearance defaults and prepare survey data
                survey_data = self._prepare_survey_data(result, team)

                # Set launch date if requested
                if result.should_launch:
                    survey_data["start_date"] = django.utils.timezone.now()

                # Create the survey directly using Django ORM
                survey = await Survey.objects.acreate(team=team, created_by=user, **survey_data)

                launch_msg = " and launched" if result.should_launch else ""
                return f"✅ Survey '{survey.name}' created{launch_msg} successfully!", {
                    "survey_id": survey.id,
                    "survey_name": survey.name,
                }

            except Exception as validation_error:
                return f"❌ Survey validation failed: {str(validation_error)}", {
                    "error": "validation_failed",
                    "details": str(validation_error),
                }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to create survey", {"error": "creation_failed", "details": str(e)}

    def _prepare_survey_data(self, survey_schema: SurveyCreationSchema, team: Team) -> dict[str, Any]:
        """Prepare survey data with appearance defaults applied."""
        # Convert schema to dict, removing should_launch field
        if hasattr(survey_schema, "model_dump"):
            survey_data = survey_schema.model_dump(exclude_unset=True, exclude={"should_launch"})
        else:
            survey_data = survey_schema.__dict__.copy()
            survey_data.pop("should_launch", None)

        # Ensure required fields have defaults
        survey_data.setdefault("archived", False)
        survey_data.setdefault("description", "")
        survey_data.setdefault("enable_partial_responses", True)

        # Apply appearance defaults
        appearance = DEFAULT_SURVEY_APPEARANCE.copy()

        # Override with team-specific defaults if they exist
        team_appearance = get_team_survey_config(team).get("appearance", {})
        if team_appearance:
            appearance.update(team_appearance)

        # Finally, override with survey-specified appearance settings
        if survey_data.get("appearance"):
            survey_appearance = survey_data["appearance"]
            # Convert to dict if needed
            if hasattr(survey_appearance, "model_dump"):
                survey_appearance = survey_appearance.model_dump(exclude_unset=True)
            elif hasattr(survey_appearance, "__dict__"):
                survey_appearance = survey_appearance.__dict__
            # Only update fields that are actually set (not None)
            appearance.update({k: v for k, v in survey_appearance.items() if v is not None})

        # Always set appearance to ensure surveys have consistent defaults
        survey_data["appearance"] = appearance

        return survey_data


class SurveyToolkit(TaxonomyAgentToolkit):
    """Toolkit for survey creation and feature flag lookup operations."""

    def __init__(self, team: Team):
        super().__init__(team)

    def get_tools(self) -> list:
        """Get all tools (default + custom). Override in subclasses to add custom tools."""
        return self._get_custom_tools()

    def _get_custom_tools(self) -> list:
        """Get custom tools for feature flag lookup."""

        class lookup_feature_flag(BaseModel):
            """
            Use this tool to lookup a feature flag by its key/name to get detailed information including ID and variants.
            Returns a message with the flag ID and the variants if the flag is found and the variants are available.
            """

            flag_key: str = Field(description="The key/name of the feature flag to look up")

        class final_answer(base_final_answer[SurveyCreationSchema]):
            __doc__ = base_final_answer.__doc__

        return [lookup_feature_flag, final_answer]

    def handle_tools(self, tool_name: str, tool_input) -> tuple[str, str]:
        """Handle custom tool execution."""
        if tool_name == "lookup_feature_flag":
            result = self._lookup_feature_flag(tool_input.arguments.flag_key)
            return tool_name, result
        return super().handle_tools(tool_name, tool_input)

    def _lookup_feature_flag(self, flag_key: str) -> str:
        """Look up feature flag information by key."""
        try:
            # Look up the feature flag by key for the current team
            feature_flag = FeatureFlag.objects.get(key=flag_key, team_id=self._team.id)

            # Get available variants
            variants = [variant["key"] for variant in feature_flag.variants]

            message = f"Found feature flag '{flag_key}' (ID: {feature_flag.id})"
            if variants:
                message += f" with variants: {', '.join(variants)}"
            else:
                message += " (no variants)"

            return message

        except FeatureFlag.DoesNotExist:
            return f"Feature flag '{flag_key}' not found in the team's feature flags."
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id})
            return f"Error looking up feature flag: '{flag_key}'"


class SurveyLoopNode(TaxonomyAgentNode[TaxonomyAgentState, TaxonomyAgentState[SurveyCreationSchema]]):
    """Node for feature flag lookup operations."""

    def __init__(self, team: Team, user: User, toolkit_class: type[SurveyToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)

    async def _get_existing_surveys_summary(self) -> str:
        """Get summary of existing surveys for context."""
        try:
            surveys = [survey async for survey in Survey.objects.filter(team_id=self._team.id, archived=False)[:5]]

            if not surveys:
                return "No existing surveys"

            summaries = []
            for survey in surveys:
                status = "active" if survey.start_date and not survey.end_date else "draft"
                summaries.append(f"- '{survey.name}' ({survey.type}, {status})")

            return "\n".join(summaries)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return "Unable to load existing surveys"

    def _get_system_prompt(self) -> ChatPromptTemplate:
        """Get system prompts for feature flag lookup."""
        existing_surveys = async_to_sync(self._get_existing_surveys_summary)()

        prompt = ChatPromptTemplate([("system", SURVEY_CREATION_SYSTEM_PROMPT)], template_format="mustache").format(
            existing_surveys=existing_surveys,
            team_survey_config=get_team_survey_config(self._team),
        )

        return ChatPromptTemplate([("system", prompt)], template_format="mustache")

    def _construct_messages(self, state: TaxonomyAgentState) -> ChatPromptTemplate:
        """
        Construct the conversation thread for the agent. Handles both initial conversation setup
        and continuation with intermediate steps.
        """
        system_prompt = self._get_system_prompt()
        conversation = list(system_prompt.messages)
        human_content = state.change or ""
        all_messages = [*conversation, ("human", human_content)]

        progress_messages = state.tool_progress_messages or []
        all_messages.extend(progress_messages)

        return ChatPromptTemplate(all_messages, template_format="mustache")


class SurveyLookupToolsNode(TaxonomyAgentToolsNode[TaxonomyAgentState, TaxonomyAgentState[SurveyCreationSchema]]):
    """Tools node for feature flag lookup operations."""

    def __init__(self, team: Team, user: User, toolkit_class: type[SurveyToolkit]):
        super().__init__(team, user, toolkit_class=toolkit_class)


class FeatureFlagLookupGraph(TaxonomyAgent[TaxonomyAgentState, TaxonomyAgentState[SurveyCreationSchema]]):
    """Graph for feature flag lookup operations."""

    def __init__(self, team: Team, user: User):
        super().__init__(
            team,
            user,
            loop_node_class=SurveyLoopNode,
            tools_node_class=SurveyLookupToolsNode,
            toolkit_class=SurveyToolkit,
        )


class SurveyAnalysisArgs(BaseModel):
    """
    Analyze survey responses to extract themes, sentiment, and actionable insights from open-ended questions.
    All survey data and responses are automatically provided from context.
    """


class SurveyAnalysisOutput(BaseModel):
    themes: list[str] = Field(description="Key themes identified from responses")
    sentiment: str = Field(description="Overall sentiment analysis (positive/negative/neutral)")
    insights: list[str] = Field(description="Actionable insights derived from the data")
    recommendations: list[str] = Field(description="Specific recommendations based on analysis")
    response_count: int = Field(description="Total number of open-ended responses analyzed")
    question_breakdown: dict[str, dict[str, Any]] = Field(
        description="Analysis breakdown by question ID", default_factory=dict
    )


class SurveyAnalysisTool(MaxTool):
    name: str = "analyze_survey_responses"
    description: str = (
        "Analyze survey responses to extract themes, sentiment, and actionable insights from open-ended questions"
    )
    thinking_message: str = "Analyzing your survey responses"

    args_schema: type[BaseModel] = SurveyAnalysisArgs

    async def _extract_open_ended_responses(self, survey: Survey) -> list[dict[str, Any]]:
        """
        Extract all open-ended text responses from the context data provided by frontend.

        The frontend provides responses grouped by question in this format:
        [
          {
            questionName: "What do you think?",
            questionId: "123",
            responses: [
              {responseText: "Great!", userDistinctId: "user1", email: "user@example.com", isOpenEnded: true},
              {responseText: "Good", userDistinctId: "user2", email: null, isOpenEnded: true}
            ]
          }
        ]
        """
        try:
            return self.context.get("formatted_responses", [])
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return []

    async def _analyze_responses(
        self, question_groups: list[dict[str, Any]], analysis_focus: str
    ) -> SurveyAnalysisOutput:
        """
        Analyze the extracted responses to generate themes, sentiment, and insights.

        Expected format:
        [
          {
            questionName: "What do you think?",
            questionId: "123",
            responses: [
              {responseText: "Great!", userDistinctId: "user1", email: "user@example.com", isOpenEnded: true},
              {responseText: "Good", userDistinctId: "user2", email: null, isOpenEnded: true}
            ]
          }
        ]
        """
        if not question_groups:
            return SurveyAnalysisOutput(
                themes=[],
                sentiment="neutral",
                insights=["No open-ended responses found to analyze."],
                recommendations=["Consider adding open-ended questions to gather more detailed feedback."],
                response_count=0,
                question_breakdown={},
            )

        # Count total responses across all questions
        total_response_count = sum(len(group.get("responses", [])) for group in question_groups)

        # For now, return enhanced placeholder analysis with real data insights
        themes = []
        insights = []
        recommendations = []

        # Extract some basic insights from the grouped data
        for group in question_groups:
            question_name = group.get("questionName", "Unknown question")
            response_count = len(group.get("responses", []))

            themes.append(f"Responses to: {question_name}")
            insights.append(f"Received {response_count} responses for '{question_name}'")

            # Add some sample response texts for debugging
            if response_count > 0:
                sample_responses = group.get("responses", [])[:3]  # First 3 responses
                sample_texts = [r.get("responseText", "") for r in sample_responses]
                insights.append(f"Sample responses: {', '.join(sample_texts[:2])}")

        if total_response_count > 0:
            recommendations.append("The survey is receiving open-ended feedback successfully")
            recommendations.append("Consider implementing full LLM analysis for deeper insights")

        return SurveyAnalysisOutput(
            themes=themes,
            sentiment="neutral",
            insights=insights,
            recommendations=recommendations,
            response_count=total_response_count,
            question_breakdown={},
        )

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        """
        Analyze survey responses to extract actionable insights from open-ended questions.
        All survey data and responses come from the context provided by the frontend.
        """
        analysis_focus = "comprehensive"  # Default analysis type

        try:
            # Get survey info from context
            survey_id = self.context.get("survey_id")
            survey_name = self.context.get("survey_name", "Unknown Survey")

            if not survey_id:
                return "❌ No survey data provided", {
                    "error": "no_survey_data",
                    "details": "Survey information not found in context",
                }

            # Get the survey object for any additional metadata we might need
            try:
                survey = await Survey.objects.aget(id=survey_id, team=self._team)
            except Survey.DoesNotExist:
                return "❌ Survey not found", {
                    "error": "survey_not_found",
                    "details": f"Survey with ID {survey_id} not found",
                }

            # Extract open-ended responses from context
            responses = await self._extract_open_ended_responses(survey)

            # Analyze the responses
            analysis_result = await self._analyze_responses(responses, analysis_focus)

            success_message = (
                f"✅ Analyzed {analysis_result.response_count} open-ended responses from survey '{survey_name}'"
            )

            if analysis_result.response_count == 0:
                success_message = f"ℹ️ No open-ended responses found in survey '{survey_name}' to analyze"

            return success_message, {
                "survey_id": survey_id,
                "survey_name": survey_name,
                "analysis": analysis_result.model_dump(),
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to analyze survey responses", {"error": "analysis_failed", "details": str(e)}
