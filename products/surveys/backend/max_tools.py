"""
MaxTool for AI-powered survey creation.
"""

from typing import Any, Literal

import django.utils.timezone

from asgiref.sync import async_to_sync
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from posthog.schema import SurveyAnalysisQuestionGroup, SurveyCreationSchema

from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import FeatureFlag, Survey, Team, User
from posthog.sync import database_sync_to_async

from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.tools import TaxonomyTool, ask_user_for_help, base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import SURVEY_ANALYSIS_SYSTEM_PROMPT, SURVEY_CREATION_SYSTEM_PROMPT


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
    billable: bool = True

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
            "billable": self.billable,
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
                        "error_message": "No questions were created from the survey instructions.",
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
                    "error_message": str(validation_error),
                }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return "❌ Failed to create survey", {"error": "creation_failed", "details": str(e)}

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

    def __init__(self, team: Team, user: User):
        super().__init__(team, user)

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

        return [lookup_feature_flag, final_answer, ask_user_for_help]

    async def handle_tools(self, tool_metadata: dict[str, list[tuple[TaxonomyTool, str]]]) -> dict[str, str]:
        """Handle custom tool execution."""
        results = {}
        unhandled_tools = {}
        for tool_name, tool_inputs in tool_metadata.items():
            if tool_name == "lookup_feature_flag":
                if tool_inputs:
                    for tool_input, tool_call_id in tool_inputs:
                        result = await self._lookup_feature_flag(tool_input.arguments.flag_key)  # type: ignore
                        results[tool_call_id] = result
            else:
                unhandled_tools[tool_name] = tool_inputs

        if unhandled_tools:
            results.update(await super().handle_tools(unhandled_tools))
        return results

    @database_sync_to_async(thread_sensitive=False)
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


class QuestionBreakdown(BaseModel):
    """Analysis breakdown for a specific question"""

    theme: str = Field(description="Main theme for this question")
    sentiment: Literal["positive", "negative", "mixed", "neutral"] = Field(
        description="Sentiment for this question", default="neutral"
    )
    key_insights: list[str] = Field(description="Key insights for this question")


class ThemeWithExamples(BaseModel):
    """Theme with supporting response examples"""

    theme: str = Field(description="Main theme name")
    description: str = Field(description="Brief explanation of the theme")
    examples: list[str] = Field(description="1-2 actual response examples that illustrate this theme", max_length=2)


class SurveyAnalysisOutput(BaseModel):
    themes: list[ThemeWithExamples] = Field(description="Key themes with examples from actual responses")
    sentiment: Literal["positive", "negative", "mixed", "neutral"] = Field(
        description="Overall sentiment analysis", default="neutral"
    )
    insights: list[str] = Field(description="Actionable insights derived from the data")
    recommendations: list[str] = Field(description="Specific recommendations based on analysis")
    response_count: int = Field(description="Total number of open-ended responses analyzed", default=0)
    question_breakdown: dict[str, QuestionBreakdown] | None = Field(
        description="Analysis breakdown by question ID", default=None
    )


class SurveyAnalysisTool(MaxTool):
    name: str = "analyze_survey_responses"
    description: str = (
        "Analyze survey responses to extract themes, sentiment, and actionable insights from open-ended questions"
    )
    context_prompt_template: str = (
        "You have access to a survey analysis tool that can analyze open-ended responses to identify themes, sentiment, and actionable insights. "
        "When users ask about analyzing survey responses, summarizing feedback, finding patterns in responses, or extracting insights from survey data, "
        "use the analyze_survey_responses tool. Survey data includes: {formatted_responses}"
    )
    billable: bool = True

    args_schema: type[BaseModel] = SurveyAnalysisArgs

    def _extract_open_ended_responses(self) -> list[SurveyAnalysisQuestionGroup]:
        """
        Extract open-ended responses from context.
        Returns a list of validated SurveyAnalysisQuestionGroup objects.
        """
        if not hasattr(self, "context") or not self.context:
            return []

        raw_responses = self.context.get("formatted_responses", [])
        if not raw_responses:
            return []

        responses = []
        for group in raw_responses:
            try:
                # Apply response limit and validate with Pydantic
                validated_group = SurveyAnalysisQuestionGroup.model_validate(
                    {
                        **group,
                        "responses": group.get("responses", [])[:50],  # Limit to 50 responses per question
                    }
                )
                responses.append(validated_group)
            except Exception:
                # Skip invalid groups
                continue

        return responses

    async def _analyze_responses(
        self, question_groups: list[SurveyAnalysisQuestionGroup], analysis_focus: str = "comprehensive"
    ) -> SurveyAnalysisOutput:
        """
        Analyze the extracted responses using LLM to generate themes, sentiment, and insights.

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
                question_breakdown=None,
            )

        # Count total responses across all questions
        total_response_count = sum(len(group.responses or []) for group in question_groups)

        try:
            # Format the data for LLM analysis
            formatted_data = self._format_responses_for_llm(question_groups)

            # Initialize LLM with PostHog context and structured output
            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,  # Lower temperature for consistent analysis
                billable=self.billable,
            ).with_structured_output(SurveyAnalysisOutput)

            # Create the analysis prompt by directly substituting the data
            formatted_prompt = SURVEY_ANALYSIS_SYSTEM_PROMPT.replace("{{{survey_responses}}}", formatted_data)

            # Generate analysis with structured output
            analysis_result = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            # Ensure response_count is accurate (don't rely on LLM calculation)
            if hasattr(analysis_result, "response_count"):
                analysis_result.response_count = total_response_count
            elif isinstance(analysis_result, dict):
                analysis_result["response_count"] = total_response_count

            # Ensure we return the proper type
            if isinstance(analysis_result, dict):
                return SurveyAnalysisOutput(**analysis_result)
            return analysis_result

        except Exception as e:
            # Don't mask the error - let the user know something went wrong
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})

            # Return an error message instead of a fake success
            error_message = f"❌ Survey analysis failed: {str(e)}"
            return SurveyAnalysisOutput(
                themes=[],
                sentiment="neutral",
                insights=[error_message],
                recommendations=["Try the analysis again, or contact support if the issue persists"],
                response_count=total_response_count,
                question_breakdown=None,
            )

    def _format_responses_for_llm(self, question_groups: list[SurveyAnalysisQuestionGroup]) -> str:
        """
        Format the grouped responses into a token-efficient string for LLM analysis.
        Optimized to reduce token usage by avoiding repetition and using compact formatting.
        """
        formatted_sections = []

        for group in question_groups:
            question_name = group.questionName
            responses = group.responses

            formatted_sections.append(f'Q: "{question_name}"')

            # Group responses without repeating question for each response
            response_texts = []
            if responses:  # Ensure responses is not None
                for response in responses:
                    response_text = response.responseText
                    # Include only response text for analysis
                    response_texts.append(f'"{response_text}"')

            formatted_sections.append("Responses:\n" + "\n".join(f"- {text}" for text in response_texts))
            formatted_sections.append("")  # Empty line between questions

        return "\n".join(formatted_sections)

    def _format_analysis_for_user(self, analysis: SurveyAnalysisOutput, survey_name: str) -> str:
        """Format the structured analysis into a user-friendly message."""
        lines = []

        # Header with response count
        header = f"✅ **Survey Analysis: '{survey_name}'**"
        lines.append(header)
        lines.append(f"*Analyzed {analysis.response_count} open-ended responses*")
        lines.append("\n---")

        # Overall sentiment first for context
        sentiment_emoji = {"positive": "😊", "negative": "😞", "mixed": "🤔", "neutral": "😐"}.get(
            analysis.sentiment, "😐"
        )
        lines.append(f"**📊 Overall Sentiment:** {sentiment_emoji} {analysis.sentiment.title()}")

        # Key themes with examples
        if analysis.themes:
            lines.append("\n**🎯 Key Themes:**")
            for i, theme in enumerate(analysis.themes[:5], 1):  # Limit to top 5 themes
                lines.append(f"\n**{i}. {theme.theme}**")
                lines.append(f"{theme.description}")
                if theme.examples:
                    lines.append("\n**Examples:**")
                    for example in theme.examples[:2]:  # Max 2 examples per theme
                        lines.append(f'- "{example}"')
                if i < len(analysis.themes[:5]):  # Don't add separator after last theme
                    lines.append("\n---")

        # Key insights with better formatting
        if analysis.insights:
            lines.append("\n**💡 Key Insights:**")
            for i, insight in enumerate(analysis.insights[:3], 1):  # Limit to top 3 insights
                lines.append(f"\n{i}. {insight}")

        # Recommendations with action-oriented formatting
        if analysis.recommendations:
            lines.append("\n**🚀 Recommendations:**")
            for i, rec in enumerate(analysis.recommendations[:3], 1):  # Top 3 recommendations
                lines.append(f"\n**{i}.** {rec}")

        # Question breakdown with improved structure
        if analysis.question_breakdown:
            lines.append("\n**📝 Question Breakdown:**")
            for question, breakdown in list(analysis.question_breakdown.items())[:3]:  # Top 3 questions
                lines.append(f"\n**Q: {question}**")
                lines.append(f"\nTheme: {breakdown.theme}")
                lines.append(f"\nSentiment: {breakdown.sentiment.title()}")
                if breakdown.key_insights:
                    lines.append("\nKey insights:")
                    for insight in breakdown.key_insights[:2]:  # Limit to 2 insights per question
                        lines.append(f"- {insight}")

        lines.append("\n---")
        lines.append("💡 *Need more detail? Ask me to dive deeper into any specific aspect.*")

        return "\n".join(lines)

    async def _arun_impl(self) -> tuple[str, dict[str, Any]]:
        """
        Analyze survey responses to extract actionable insights from open-ended questions.
        All survey data and responses come from the context provided by the frontend.
        """
        try:
            # Get survey info from context
            survey_id = self.context.get("survey_id")
            survey_name = self.context.get("survey_name", "Unknown Survey")
            # Get pre-formatted responses from frontend (already in correct format)
            raw_responses = self.context.get("formatted_responses", [])
            if not raw_responses:
                responses = []
            else:
                # Apply response limit and validate with Pydantic
                responses = [
                    SurveyAnalysisQuestionGroup.model_validate(
                        {
                            **group,
                            "responses": group.get("responses", [])[:50],  # Limit to 50 responses per question
                        }
                    )
                    for group in raw_responses
                ]

            if not survey_id or not responses:
                return "❌ No survey data provided", {
                    "error": "no_survey_data",
                    "details": "Survey information not found in context",
                }

            # Analyze the responses
            analysis_result = await self._analyze_responses(responses)

            if analysis_result.response_count == 0:
                success_message = f"ℹ️ No open-ended responses found in survey '{survey_name}' to analyze"
                return success_message, {
                    "survey_id": survey_id,
                    "survey_name": survey_name,
                    "analysis": analysis_result.model_dump(),
                }

            # Format the analysis as a user-friendly message
            user_message = self._format_analysis_for_user(analysis_result, survey_name)

            return user_message, {
                "survey_id": survey_id,
                "survey_name": survey_name,
                "analysis": analysis_result.model_dump(),
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to analyze survey responses: {str(e)}", {"error": "analysis_failed", "details": str(e)}
