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
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import SURVEY_CREATION_SYSTEM_PROMPT

SURVEY_ANALYSIS_SYSTEM_PROMPT = """
<agent_info>
You are Max, PostHog's AI assistant specializing in survey response analysis. You are an expert product researcher and data analyst who helps users extract actionable insights from their survey feedback.

Your expertise includes:
- Identifying meaningful themes and patterns in qualitative feedback
- Performing sentiment analysis on user responses
- Generating actionable recommendations for product improvement
- Connecting user feedback to business impact
- Detecting test data and placeholder responses
</agent_info>

<instructions>
**CRITICAL: ONLY analyze what is actually in the response data. Do NOT infer topics from survey titles, question names, or any other metadata.**

First, assess the quality of the response data:
1. **Data Quality Check**: Determine if responses are genuine user feedback or test/placeholder data
   - Look for patterns like random keystrokes ("fasdfasdf", "abc", "hello", "asdf")
   - Identify short, meaningless responses that don't provide real insights
   - Flag responses that appear to be testing or placeholder content

2. If responses appear to be genuine user feedback, analyze for:
   - **Theme Identification**: Find recurring topics, concerns, and suggestions across responses
   - **Sentiment Analysis**: Determine overall sentiment and emotional tone of feedback
   - **Actionable Insights**: Identify specific patterns that suggest product improvements
   - **Recommendations**: Provide concrete, prioritized actions based on the feedback

3. If responses appear to be test data:
   - Clearly state that the responses appear to be test/placeholder data
   - Do not generate fictional themes or insights
   - Recommend collecting real user feedback for meaningful analysis

For each question in the survey data:
- Analyze ONLY the actual response content, not the question title
- Look for patterns within the actual responses
- Ignore question metadata when drawing conclusions about user sentiment

Across all questions:
- Base insights solely on response content
- Never assume topics based on survey or question titles
- If responses are too brief or nonsensical to analyze, acknowledge this limitation
</instructions>

<constraints>
- NEVER make assumptions based on survey titles, question names, or other metadata
- ONLY analyze the actual response text content provided
- Focus on insights that are clearly supported by the actual responses
- If response volume is low or consists of test data, acknowledge limitations honestly
- Distinguish between meaningful feedback and placeholder/test responses
- Be specific in your recommendations - avoid generic advice
- If responses appear to be test data, do not fabricate insights
- If no meaningful patterns emerge from actual response content, say so honestly
</constraints>

<examples>
### Example 1: Product feedback survey
Survey Data:
Question: "What do you like most about our product?"
Responses:
- "Easy to use interface" (user1@example.com)
- "Great customer support" (user2@example.com)
- "Simple setup process" (user3@example.com)

Question: "What could we improve?"
Responses:
- "Loading times are slow" (user1@example.com)
- "Need better mobile app" (user2@example.com)
- "More integrations please" (user3@example.com)

Analysis Output:
{
  "themes": ["User Experience Excellence", "Performance Issues", "Platform Expansion"],
  "sentiment": "mixed",
  "insights": [
    "Users highly value simplicity and ease of use (mentioned in 'likes' responses)",
    "Performance is the top improvement area (loading times mentioned)",
    "Mobile experience needs attention (specific mobile app request)",
    "Integration ecosystem expansion requested"
  ],
  "recommendations": [
    "Prioritize performance optimization, especially loading speed improvements",
    "Develop or enhance mobile application experience",
    "Research and plan integration roadmap based on user requests",
    "Continue focusing on simplicity as a key differentiator"
  ],
  "response_count": 6,
  "question_breakdown": {
    "What do you like most": {
      "theme": "User Experience Excellence",
      "sentiment": "positive",
      "key_insights": ["Ease of use is primary value driver", "Support quality appreciated"]
    },
    "What could we improve": {
      "theme": "Performance and Expansion",
      "sentiment": "constructive",
      "key_insights": ["Performance bottlenecks identified", "Platform expansion desired"]
    }
  }
}

### Example 2: Test/Placeholder Data
Survey Data:
Question: "What can we do to improve our product?"
Responses:
- "fasdfasdf" (test@posthog.com)
- "abc" (test@posthog.com)
- "hello" (user123)
- "asdfasdf" (user456)

Analysis Output:
{
  "themes": ["Test data identified"],
  "sentiment": "neutral",
  "insights": [
    "All responses appear to be test or placeholder data (random keystrokes, single words)",
    "No meaningful user feedback patterns can be extracted from this data",
    "Responses like 'fasdfasdf', 'abc' suggest testing rather than genuine user input"
  ],
  "recommendations": [
    "Collect genuine user feedback by launching the survey to real users",
    "Ensure survey is properly distributed to target audience",
    "Consider adding example responses or clearer instructions to encourage meaningful feedback"
  ],
  "response_count": 4,
  "question_breakdown": {
    "What can we do to improve": {
      "theme": "Test data",
      "sentiment": "neutral",
      "key_insights": ["Responses are placeholder/test content, no real feedback available"]
    }
  }
}

### Example 3: Low response volume
Survey Data:
Question: "How satisfied are you with our service?"
Responses:
- "Very satisfied" (user@example.com)

Analysis Output:
{
  "themes": ["Limited feedback available"],
  "sentiment": "positive",
  "insights": [
    "Single response indicates satisfaction, but sample size too small for meaningful analysis",
    "Need more responses to identify patterns or areas for improvement"
  ],
  "recommendations": [
    "Increase survey response rate to gather more representative feedback",
    "Consider follow-up surveys or alternative feedback collection methods",
    "Current positive response suggests satisfaction but needs validation"
  ],
  "response_count": 1,
  "question_breakdown": {}
}
</examples>

Survey Response Data:
{{{survey_responses}}}

Please provide your analysis in the exact JSON format shown in the examples above.
""".strip()


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
    root_system_prompt_template: str = (
        "You have access to a survey analysis tool that can analyze open-ended responses to identify themes, sentiment, and actionable insights. "
        "When users ask about analyzing survey responses, summarizing feedback, finding patterns in responses, or extracting insights from survey data, "
        "use the analyze_survey_responses tool. Survey data includes: {formatted_responses}"
    )

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
                question_breakdown={},
            )

        # Count total responses across all questions
        total_response_count = sum(len(group.get("responses", [])) for group in question_groups)

        try:
            # Format the data for LLM analysis
            formatted_data = self._format_responses_for_llm(question_groups)

            # Initialize LLM with PostHog context
            llm = MaxChatOpenAI(
                user=self._user,
                team=self._team,
                model="gpt-4.1",
                temperature=0.1,  # Lower temperature for consistent analysis
            )

            # Create the analysis prompt by directly substituting the data
            formatted_prompt = SURVEY_ANALYSIS_SYSTEM_PROMPT.replace("{{{survey_responses}}}", formatted_data)

            # Generate analysis
            response = await llm.ainvoke([{"role": "system", "content": formatted_prompt}])

            # Parse the LLM response
            import json

            try:
                analysis_result = json.loads(response.content.strip())

                return SurveyAnalysisOutput(
                    themes=analysis_result.get("themes", []),
                    sentiment=analysis_result.get("sentiment", "neutral"),
                    insights=analysis_result.get("insights", []),
                    recommendations=analysis_result.get("recommendations", []),
                    response_count=analysis_result.get("response_count", total_response_count),
                    question_breakdown=analysis_result.get("question_breakdown", {}),
                )
            except json.JSONDecodeError:
                # Fallback if LLM doesn't return valid JSON
                return SurveyAnalysisOutput(
                    themes=["Analysis completed"],
                    sentiment="neutral",
                    insights=[f"LLM Analysis: {response.content[:200]}..."],
                    recommendations=["Review the full analysis for detailed insights"],
                    response_count=total_response_count,
                    question_breakdown={},
                )

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
                question_breakdown={},
            )

    def _format_responses_for_llm(self, question_groups: list[dict[str, Any]]) -> str:
        """Format the grouped responses into a clean string for LLM analysis."""
        formatted_sections = []

        for group in question_groups:
            question_name = group.get("questionName", "Unknown question")
            responses = group.get("responses", [])

            formatted_sections.append(f'Question: "{question_name}"')
            formatted_sections.append("Responses:")

            for response in responses:
                response_text = response.get("responseText", "")
                user_id = response.get("userDistinctId", "anonymous")
                email = response.get("email")

                # Format user identifier
                user_identifier = email if email else f"user:{user_id}"
                formatted_sections.append(f'- "{response_text}" ({user_identifier})')

            formatted_sections.append("")  # Empty line between questions

        return "\n".join(formatted_sections)

    def _format_analysis_for_user(self, analysis: SurveyAnalysisOutput, survey_name: str) -> str:
        """Format the structured analysis into a user-friendly message."""
        lines = []

        # Header with response count
        header = f"✅ **Survey Analysis: '{survey_name}'**"
        lines.append(header)
        lines.append(f"*Analyzed {analysis.response_count} open-ended responses*")
        lines.append("")

        # Key themes
        if analysis.themes:
            lines.append("**Key Themes:**")
            for theme in analysis.themes[:5]:  # Limit to top 5 themes
                lines.append(f"• {theme}")
            lines.append("")

        # Sentiment
        sentiment_emoji = {"positive": "😊", "negative": "😞", "mixed": "🤔", "neutral": "😐"}.get(
            analysis.sentiment, "😐"
        )
        lines.append(f"**Overall Sentiment:** {sentiment_emoji} {analysis.sentiment.title()}")
        lines.append("")

        # Key insights
        if analysis.insights:
            lines.append("**Key Insights:**")
            for insight in analysis.insights[:3]:  # Limit to top 3 insights
                lines.append(f"• {insight}")
            lines.append("")

        # Recommendations
        if analysis.recommendations:
            lines.append("**Recommendations:**")
            for i, rec in enumerate(analysis.recommendations[:3], 1):  # Top 3 recommendations
                lines.append(f"{i}. {rec}")
            lines.append("")

        # Question breakdown summary
        if analysis.question_breakdown:
            lines.append("**Question Breakdown:**")
            for question, breakdown in list(analysis.question_breakdown.items())[:3]:  # Top 3 questions
                lines.append(
                    f"• **{question}**: {breakdown.get('theme', 'No theme')} ({breakdown.get('sentiment', 'neutral')})"
                )
            lines.append("")

        lines.append("💡 *Need more detail? Ask me to dive deeper into any specific aspect.*")

        return "\n".join(lines)

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
