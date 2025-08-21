"""
MaxTool for AI-powered survey creation.
"""

from typing import Any, Optional
from asgiref.sync import async_to_sync
import django.utils.timezone
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from enum import Enum

from ee.hogai.tool import MaxTool
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.graph.taxonomy.nodes import TaxonomyAgentNode, TaxonomyAgentToolsNode
from ee.hogai.graph.taxonomy.toolkit import TaxonomyAgentToolkit
from ee.hogai.graph.taxonomy.agent import TaxonomyAgent
from ee.hogai.graph.taxonomy.tools import base_final_answer
from ee.hogai.graph.taxonomy.types import TaxonomyAgentState
from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import Survey, Team, FeatureFlag, User
from posthog.schema import SurveyCreationSchema


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


# =============================================================================
# Survey Response Analysis Tool
# =============================================================================


class AnalysisType(str, Enum):
    """
    AI Analysis Explanation:
    We define specific analysis types to help the LLM understand exactly what kind of
    analysis to perform. This enum provides clear constraints that improve prompt clarity
    and output consistency.
    """

    SUMMARIZE = "summarize"  # Extract key themes and actionable insights
    CATEGORIZE = "categorize"  # Group responses into categories for charting


class ResponseCategory(BaseModel):
    """
    AI Analysis Explanation:
    Structured output schema for categorization results. This ensures the LLM returns
    data in a format that's immediately usable for creating dynamic charts in the frontend.
    The Pydantic model provides type safety and validation.
    """

    name: str = Field(description="Category name")
    description: str = Field(description="Brief description of what this category represents")
    responses: list[str] = Field(description="List of responses that belong to this category")
    count: int = Field(description="Number of responses in this category")


class SurveyAnalysisResult(BaseModel):
    """
    AI Analysis Explanation:
    Comprehensive result structure that handles both summarization and categorization.
    This structured approach allows the frontend to handle different analysis types
    consistently while providing rich data for visualization.
    """

    analysis_type: AnalysisType
    summary: Optional[str] = Field(description="Key insights and action items (for summarize type)")
    categories: Optional[list[ResponseCategory]] = Field(description="Response categories (for categorize type)")
    total_responses_analyzed: int = Field(description="Number of responses analyzed")
    key_themes: list[str] = Field(description="Main themes identified across responses")


class AnalyzeSurveyResponsesArgs(BaseModel):
    """
    AI Analysis Explanation:
    Input schema that captures all necessary context for analysis. The survey_id and
    question_index help fetch the right data, while analysis_type guides the LLM's
    processing approach.
    """

    survey_id: str = Field(description="ID of the survey to analyze")
    question_index: int = Field(description="Index of the question to analyze (0-based)")
    analysis_type: AnalysisType = Field(description="Type of analysis to perform")


class AnalyzeSurveyResponsesTool(MaxTool):
    """
    AI Analysis Explanation:
    This MaxTool uses a direct LLM approach rather than a complex agent graph because:
    1. The task is well-defined (analyze text responses)
    2. We don't need to search through taxonomies or complex data
    3. A focused prompt with structured output is more reliable for this use case

    The tool follows PostHog's pattern of using MaxChatOpenAI for automatic context injection
    and structured output for consistent results.
    """

    name: str = "analyze_survey_responses"
    description: str = "Analyze open-ended survey responses to extract insights and categorize feedback"
    thinking_message: str = "Analyzing survey responses"
    args_schema: type[BaseModel] = AnalyzeSurveyResponsesArgs

    async def _get_survey_responses(self, survey_id: str, question_index: int) -> list[str]:
        """
        AI Analysis Explanation:
        This method fetches and filters survey responses to get only the open-ended text
        responses from choice questions. We focus on non-predefined responses which contain
        the rich qualitative data that's most valuable for AI analysis.
        """
        try:
            # Get the survey and validate access
            survey = await Survey.objects.aget(id=survey_id, team=self._team)

            # Validate question index
            if not survey.questions or question_index >= len(survey.questions):
                return []

            question = survey.questions[question_index]

            # Only analyze multiple choice and single choice questions
            if question.get("type") not in ["multiple_choice", "single_choice"]:
                return []

            # TODO: In a real implementation, we would query the survey responses from the database
            # For now, we'll use the context data passed from the frontend
            response_data = self.context.get("response_data", [])

            # Extract open-ended responses (non-predefined responses)
            open_ended_responses = []
            for response in response_data:
                if not response.get("isPredefined", True) and response.get("label"):
                    # Add each response multiple times based on its count
                    count = response.get("value", 1)
                    for _ in range(count):
                        open_ended_responses.append(response["label"])

            return open_ended_responses

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "survey_id": survey_id})
            return []

    async def _analyze_responses(
        self, responses: list[str], analysis_type: AnalysisType, question_text: str
    ) -> SurveyAnalysisResult:
        """
        AI Analysis Explanation:
        This is the core AI processing method. It uses a carefully crafted prompt that:
        1. Provides clear context about the survey question and analysis goal
        2. Uses structured output to ensure consistent, parseable results
        3. Follows PostHog's prompting guidelines with XML tags for organization
        4. Focuses on actionable insights rather than just thematic analysis
        """

        if not responses:
            return SurveyAnalysisResult(
                analysis_type=analysis_type,
                summary="No open-ended responses to analyze.",
                categories=[],
                total_responses_analyzed=0,
                key_themes=[],
            )

        # Create the analysis prompt
        if analysis_type == AnalysisType.SUMMARIZE:
            prompt_template = """
<analysis_context>
You are analyzing open-ended survey responses to extract actionable insights for a product team.
Survey Question: "{question_text}"
Number of responses: {response_count}
</analysis_context>

<instructions>
Analyze the following survey responses and provide:
1. A concise summary highlighting the most important themes and patterns
2. Specific action items or recommendations based on the feedback
3. Key themes that emerge from the responses

Focus on actionable insights rather than just describing what people said.
Prioritize feedback that appears frequently or represents significant user concerns.
</instructions>

<responses>
{responses_text}
</responses>

Provide your analysis focusing on what the product team should do next based on this feedback.
"""
        else:  # CATEGORIZE
            prompt_template = """
<analysis_context>
You are categorizing open-ended survey responses to help create meaningful data visualizations.
Survey Question: "{question_text}"
Number of responses: {response_count}
</analysis_context>

<instructions>
Categorize these survey responses into 3-7 meaningful groups that would be useful for:
1. Creating charts and visualizations
2. Understanding user sentiment patterns
3. Identifying areas for product improvement

Each category should:
- Have a clear, concise name
- Include a brief description of what it represents
- Contain responses that genuinely belong together
- Be actionable for product decisions

Avoid overly granular categories. Aim for categories that capture the main themes.
</instructions>

<responses>
{responses_text}
</responses>

Group these responses into categories that will help the product team understand user feedback patterns.
"""

        # Format the prompt with actual data
        responses_text = "\n".join([f"- {response}" for response in responses])
        formatted_prompt = prompt_template.format(
            question_text=question_text, response_count=len(responses), responses_text=responses_text
        )

        # Use MaxChatOpenAI with structured output for consistent results
        llm = (
            MaxChatOpenAI(
                model="gpt-4o",  # Use the most capable model for nuanced text analysis
                temperature=0.3,  # Low temperature for consistent categorization, but some creativity for insights
                user=self._user,
                team=self._team,
            )
            .with_structured_output(SurveyAnalysisResult)
            .with_retry()  # Automatic retry on failures
        )

        try:
            result = await llm.ainvoke([("human", formatted_prompt)])

            # Ensure the analysis_type is set correctly
            result.analysis_type = analysis_type
            result.total_responses_analyzed = len(responses)

            return result

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "analysis_type": analysis_type})
            # Return a fallback result
            return SurveyAnalysisResult(
                analysis_type=analysis_type,
                summary="Unable to analyze responses due to an error.",
                categories=[],
                total_responses_analyzed=len(responses),
                key_themes=[],
            )

    async def _arun_impl(
        self, survey_id: str, question_index: int, analysis_type: AnalysisType
    ) -> tuple[str, SurveyAnalysisResult]:
        """
        AI Analysis Explanation:
        Main execution method that orchestrates the analysis process:
        1. Fetches and validates survey data
        2. Extracts open-ended responses from choice questions
        3. Performs AI analysis based on the requested type
        4. Returns both a user-friendly message and structured data

        The structured data can be used by the frontend to create visualizations,
        while the message provides immediate feedback to the user.
        """
        try:
            # Get survey information for context
            survey = await Survey.objects.aget(id=survey_id, team=self._team)
            question = (
                survey.questions[question_index] if survey.questions and question_index < len(survey.questions) else {}
            )
            question_text = question.get("question", "Unknown question")

            # Extract open-ended responses
            responses = await self._get_survey_responses(survey_id, question_index)

            if not responses:
                return "❌ No open-ended responses found for this question.", SurveyAnalysisResult(
                    analysis_type=analysis_type,
                    summary="No open-ended responses available for analysis.",
                    categories=[],
                    total_responses_analyzed=0,
                    key_themes=[],
                )

            # Perform AI analysis
            analysis_result = await self._analyze_responses(responses, analysis_type, question_text)

            # Create user-friendly response message
            if analysis_type == AnalysisType.SUMMARIZE:
                message = f"✅ Analyzed {len(responses)} open-ended responses and extracted key insights."
            else:
                category_count = len(analysis_result.categories) if analysis_result.categories else 0
                message = f"✅ Categorized {len(responses)} responses into {category_count} meaningful groups."

            return message, analysis_result

        except Survey.DoesNotExist:
            return "❌ Survey not found.", SurveyAnalysisResult(
                analysis_type=analysis_type,
                summary="Survey not found.",
                categories=[],
                total_responses_analyzed=0,
                key_themes=[],
            )
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "survey_id": survey_id})
            return "❌ Failed to analyze survey responses.", SurveyAnalysisResult(
                analysis_type=analysis_type,
                summary="Analysis failed due to an error.",
                categories=[],
                total_responses_analyzed=0,
                key_themes=[],
            )
