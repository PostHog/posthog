"""
MaxTool for AI-powered survey creation.
"""

from textwrap import dedent
from typing import Any, Literal

import django.utils.timezone

from asgiref.sync import sync_to_async
from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import (
    SurveyAnalysisQuestionGroup,
    SurveyAppearanceSchema,
    SurveyCreationSchema,
    SurveyDisplayConditionsSchema,
    SurveyQuestionSchema,
    SurveyType,
)

from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import Survey, Team

from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .prompts import SURVEY_ANALYSIS_SYSTEM_PROMPT


def get_team_survey_config(team: Team) -> dict[str, Any]:
    """Get team survey configuration for context."""
    survey_config = getattr(team, "survey_config", {}) or {}
    return {
        "appearance": survey_config.get("appearance", {}),
        "default_settings": {"type": "popover", "enable_partial_responses": True},
    }


SURVEY_CREATION_TOOL_DESCRIPTION = dedent("""
    Use this tool to create and optionally launch in-app surveys based on structured survey configurations.

    # When to use
    - The user wants to create a new survey
    - The user wants to launch a survey for collecting feedback
    - The user mentions NPS, CSAT, PMF, or feedback surveys

    # Critical Survey Design Principles
    **These are in-app surveys that appear as overlays while users are actively using the product.**
    - **Keep surveys SHORT**: 1-3 questions maximum - users are trying to accomplish tasks
    - **Focus on ONE key insight**: Don't try to gather everything at once
    - **Prioritize user experience**: A short survey with high completion is better than a long abandoned one

    # Survey Types
    - **popover** (default): Small overlay that appears on the page - most common for in-app surveys
    - **widget**: Widget that appears via CSS selector or embedded button
    - **api**: Headless survey for custom implementations

    # Question Types
    1. **open**: Free-form text input (feedback, suggestions)
    2. **single_choice**: Select one option (Yes/No, satisfaction levels)
    3. **multiple_choice**: Select multiple options (feature preferences)
    4. **rating**: Numeric (1-10 for NPS, 1-5 for CSAT) or emoji scale
    5. **link**: Display a link with call-to-action

    # Common Survey Patterns
    - **NPS**: "How likely are you to recommend us?" (rating scale 10, number display)
    - **CSAT**: "How satisfied are you with X?" (rating scale 5)
    - **PMF**: "How would you feel if you could no longer use X?" (single_choice with specific options)
    - **Feedback**: Open-ended questions about experience

    # Feature Flag Targeting
    When targeting by feature flag:
    - User must provide the flag ID (integer) from a prior search
    - Set `linked_flag_id` to the integer flag ID
    - For variant targeting, add `linkedFlagVariant` in conditions
    """).strip()


class CreateSurveyToolArgs(BaseModel):
    survey: SurveyCreationSchema = Field(
        description=dedent("""
        The complete survey configuration to create.

        # Required Fields
        - **name**: Survey name (e.g., "NPS Survey", "Onboarding Feedback")
        - **description**: Brief survey description
        - **type**: "popover" (default), "widget", or "api"
        - **questions**: Array of question objects (see Question Structure below)

        # Optional Fields
        - **should_launch**: Set to true to launch immediately, false for draft (default: false)
        - **linked_flag_id**: Integer feature flag ID for targeting users with a specific flag
        - **conditions**: Display conditions object (URL targeting, wait period, etc.)
        - **appearance**: Custom appearance settings (colors, positioning)
        - **start_date**: ISO date string to schedule launch
        - **end_date**: ISO date string to end survey
        - **responses_limit**: Maximum number of responses to collect

        # Question Structure
        Each question requires:
        - **type**: "open", "rating", "single_choice", "multiple_choice", or "link"
        - **question**: The question text to display

        Optional per question:
        - **id**: Unique identifier (auto-generated if not provided)
        - **description**: Additional context below the question
        - **optional**: Whether the question can be skipped (default: false)
        - **buttonText**: Text for the continue button

        For **rating** questions:
        - **scale**: Number of points (5, 7, or 10). Use 10 for NPS, 5 for CSAT
        - **display**: "number" or "emoji"
        - **lowerBoundLabel**: Label for low end (e.g., "Not likely")
        - **upperBoundLabel**: Label for high end (e.g., "Very likely")

        For **single_choice**/**multiple_choice** questions:
        - **choices**: Array of option strings

        For **link** questions:
        - **link**: URL to link to
        - **buttonText**: Link button text

        # Conditions Structure
        - **url**: URL path string to match (e.g., "/pricing", "/dashboard")
        - **urlMatchType**: How to match URL - "exact", "icontains" (contains, case-insensitive), "not_icontains", "regex", "not_regex", "is_not"
        - **seenSurveyWaitPeriodInDays**: Number of days to wait after user has seen any survey before showing this one
        - **deviceTypes**: Array of device types to target, e.g., ["Mobile"], ["Desktop", "Tablet"]
        - **deviceTypesMatchType**: Match type for devices - same options as urlMatchType
        - **linkedFlagVariant**: Feature flag variant to target (requires linked_flag_id)
        - **selector**: CSS selector for element-based targeting (e.g., "#signup-button")

        # Examples

        ## NPS Survey
        ```json
        {
            "name": "NPS Survey",
            "description": "Net Promoter Score survey",
            "type": "popover",
            "questions": [{
                "type": "rating",
                "question": "How likely are you to recommend us to a friend or colleague?",
                "scale": 10,
                "display": "number",
                "lowerBoundLabel": "Not likely at all",
                "upperBoundLabel": "Extremely likely"
            }],
            "should_launch": false
        }
        ```

        ## NPS with Follow-up
        ```json
        {
            "name": "NPS with Feedback",
            "description": "NPS with optional follow-up question",
            "type": "popover",
            "questions": [
                {
                    "type": "rating",
                    "question": "How likely are you to recommend us?",
                    "scale": 10,
                    "display": "number",
                    "lowerBoundLabel": "Not likely",
                    "upperBoundLabel": "Very likely"
                },
                {
                    "type": "open",
                    "question": "What could we improve?",
                    "optional": true
                }
            ],
            "should_launch": false
        }
        ```

        ## Targeted Survey (URL + Feature Flag)
        ```json
        {
            "name": "Pricing Page Feedback",
            "description": "Feedback from pricing page visitors",
            "type": "popover",
            "linked_flag_id": 123,
            "conditions": {
                "url": "/pricing",
                "urlMatchType": "icontains"
            },
            "questions": [{
                "type": "single_choice",
                "question": "Is our pricing clear?",
                "choices": ["Yes, very clear", "Somewhat clear", "Not clear at all"]
            }],
            "should_launch": true
        }
        ```

        # Critical Rules
        - Keep to 1-3 questions maximum
        - DO NOT set should_launch=true unless the user explicitly requests to launch
        - NPS uses scale=10, CSAT uses scale=5
        - First question should typically be required (optional: false), follow-ups can be optional
        """).strip()
    )


class CreateSurveyTool(MaxTool):
    name: str = "create_survey"
    description: str = SURVEY_CREATION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateSurveyToolArgs

    def get_required_resource_access(self):
        return [("survey", "editor")]

    async def is_dangerous_operation(self, survey: SurveyCreationSchema, **kwargs) -> bool:
        """Launching a survey immediately is a dangerous operation."""
        return survey.should_launch is True

    async def format_dangerous_operation_preview(self, survey: SurveyCreationSchema, **kwargs) -> str:
        """Format a human-readable preview of the dangerous operation."""
        survey_name = survey.name or "Untitled Survey"
        question_count = len(survey.questions) if survey.questions else 0
        return f"**Create and launch** survey '{survey_name}' with {question_count} question(s). It will immediately start collecting responses."

    async def _arun_impl(self, survey: SurveyCreationSchema) -> tuple[str, dict[str, Any]]:
        """
        Create a survey from the structured configuration.
        """
        try:
            user = self._user
            team = self._team

            if not survey.questions:
                return "Survey must have at least one question", {
                    "error": "validation_failed",
                    "error_message": "No questions provided in the survey configuration.",
                }

            # Apply appearance defaults and prepare survey data
            survey_data = self._prepare_survey_data(survey, team)

            # Set launch date if requested
            if survey.should_launch:
                survey_data["start_date"] = django.utils.timezone.now()

            # Link to insight if provided in context (e.g., from funnel cross-sell)
            if self.context.get("insight_id"):
                survey_data["linked_insight_id"] = self.context["insight_id"]

            # Create the survey directly using Django ORM
            created_survey = await Survey.objects.acreate(team=team, created_by=user, **survey_data)

            launch_msg = " and launched" if survey.should_launch else ""
            return f"Survey '{created_survey.name}' created{launch_msg} successfully!", {
                "survey_id": created_survey.id,
                "survey_name": created_survey.name,
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create survey: {str(e)}", {"error": "creation_failed", "details": str(e)}

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


SURVEY_EDIT_TOOL_DESCRIPTION = dedent("""
    Use this tool to edit an existing survey.

    # When to use
    - User wants to modify a survey's name, description, or questions
    - User wants to launch or stop a survey
    - User wants to archive a survey
    - User wants to change survey targeting conditions

    # Finding the Survey
    First use the search tool with kind="surveys" to find the survey ID, then use this tool.

    # Common Operations
    - **Launch**: Set start_date to "now"
    - **Stop**: Set end_date to "now"
    - **Archive**: Set archived to true
    - **Update questions**: Provide full questions array (replaces existing)
    - **Update conditions**: Provide conditions object (replaces existing)

    # Important Notes
    - Only include fields you want to change in the updates
    - When updating questions, you must provide the complete list (it replaces existing)
    - You cannot edit a survey that doesn't belong to your team
    """).strip()


class SurveyUpdateSchema(BaseModel):
    """Partial schema for survey updates - only include fields to change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    type: SurveyType | None = None
    questions: list[SurveyQuestionSchema] | None = None
    conditions: SurveyDisplayConditionsSchema | None = None
    appearance: SurveyAppearanceSchema | None = None
    linked_flag_id: int | None = None
    start_date: str | None = Field(default=None, description='ISO date string or "now" to launch immediately')
    end_date: str | None = Field(default=None, description='ISO date string or "now" to stop immediately')
    archived: bool | None = None
    responses_limit: int | None = None
    enable_partial_responses: bool | None = None


class EditSurveyToolArgs(BaseModel):
    survey_id: str = Field(description="UUID of the survey to edit")
    updates: SurveyUpdateSchema = Field(description="Fields to update on the survey")


class EditSurveyTool(MaxTool):
    name: str = "edit_survey"
    description: str = SURVEY_EDIT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = EditSurveyToolArgs

    def get_required_resource_access(self):
        return [("survey", "editor")]

    async def is_dangerous_operation(self, survey_id: str, updates: SurveyUpdateSchema, **kwargs) -> bool:
        """Launching, stopping, or archiving a survey are dangerous operations."""
        return updates.start_date == "now" or updates.end_date == "now" or updates.archived is True

    async def format_dangerous_operation_preview(self, survey_id: str, updates: SurveyUpdateSchema, **kwargs) -> str:
        """Format a human-readable preview of the dangerous operation."""
        # Try to get survey name for a better preview
        survey_name = survey_id
        try:
            survey = await sync_to_async(Survey.objects.get)(id=survey_id, team=self._team)
            survey_name = f"'{survey.name}'"
        except Survey.DoesNotExist:
            survey_name = f"(ID: {survey_id})"

        actions = []
        if updates.start_date == "now":
            actions.append("**Launch** the survey (it will start collecting responses)")
        if updates.end_date == "now":
            actions.append("**Stop** the survey (it will stop collecting responses)")
        if updates.archived is True:
            actions.append("**Archive** the survey")

        if len(actions) == 1:
            return f"{actions[0]} {survey_name}"
        else:
            action_list = "\n".join(f"- {action}" for action in actions)
            return f"Perform the following actions on survey {survey_name}:\n{action_list}"

    async def _arun_impl(self, survey_id: str, updates: SurveyUpdateSchema) -> tuple[str, dict[str, Any]]:
        """
        Edit an existing survey with the provided updates.
        """
        try:
            team = self._team

            # Fetch the existing survey
            try:
                survey = await sync_to_async(Survey.objects.get)(id=survey_id, team=team)
            except Survey.DoesNotExist:
                return f"Survey with ID '{survey_id}' not found", {
                    "error": "not_found",
                    "error_message": f"No survey found with ID '{survey_id}' in your team.",
                }

            # Get the updates as a dict, excluding None values
            update_data = updates.model_dump(exclude_unset=True)

            if not update_data:
                return "No updates provided", {
                    "error": "no_updates",
                    "error_message": "No fields were provided to update.",
                }

            # Handle special date values
            if update_data.get("start_date") == "now":
                update_data["start_date"] = django.utils.timezone.now()
            if update_data.get("end_date") == "now":
                update_data["end_date"] = django.utils.timezone.now()

            # Handle nested objects that need conversion
            if "questions" in update_data and update_data["questions"] is not None:
                update_data["questions"] = [
                    q.model_dump(exclude_unset=True) if hasattr(q, "model_dump") else q
                    for q in update_data["questions"]
                ]

            if "conditions" in update_data and update_data["conditions"] is not None:
                conditions = update_data["conditions"]
                update_data["conditions"] = (
                    conditions.model_dump(exclude_unset=True) if hasattr(conditions, "model_dump") else conditions
                )

            if "appearance" in update_data and update_data["appearance"] is not None:
                appearance = update_data["appearance"]
                # Merge with existing appearance
                existing_appearance = survey.appearance or {}
                new_appearance = (
                    appearance.model_dump(exclude_unset=True) if hasattr(appearance, "model_dump") else appearance
                )
                update_data["appearance"] = {**existing_appearance, **new_appearance}

            # Apply updates to survey
            for field, value in update_data.items():
                setattr(survey, field, value)

            await sync_to_async(survey.save)()

            # Build response message
            updated_fields = list(update_data.keys())
            actions = []
            if "start_date" in updated_fields and updates.start_date == "now":
                actions.append("launched")
            if "end_date" in updated_fields and updates.end_date == "now":
                actions.append("stopped")
            if "archived" in updated_fields and updates.archived:
                actions.append("archived")

            if actions:
                action_str = " and ".join(actions)
                message = f"Survey '{survey.name}' has been {action_str} successfully!"
            else:
                fields_str = ", ".join(updated_fields)
                message = f"Survey '{survey.name}' updated successfully! Modified fields: {fields_str}"

            return message, {
                "survey_id": str(survey.id),
                "survey_name": survey.name,
                "updated_fields": updated_fields,
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to edit survey: {str(e)}", {"error": "edit_failed", "details": str(e)}


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
    args_schema: type[BaseModel] = SurveyAnalysisArgs

    def get_required_resource_access(self):
        return [("survey", "viewer")]

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
                billable=True,
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
            error_message = f"Survey analysis failed: {str(e)}"
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
        header = f"**Survey Analysis: '{survey_name}'**"
        lines.append(header)
        lines.append(f"*Analyzed {analysis.response_count} open-ended responses*")
        lines.append("\n---")

        # Overall sentiment first for context
        sentiment_emoji = {"positive": ":)", "negative": ":(", "mixed": ":/", "neutral": ":|"}.get(
            analysis.sentiment, ":|"
        )
        lines.append(f"**Overall Sentiment:** {sentiment_emoji} {analysis.sentiment.title()}")

        # Key themes with examples
        if analysis.themes:
            lines.append("\n**Key Themes:**")
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
            lines.append("\n**Key Insights:**")
            for i, insight in enumerate(analysis.insights[:3], 1):  # Limit to top 3 insights
                lines.append(f"\n{i}. {insight}")

        # Recommendations with action-oriented formatting
        if analysis.recommendations:
            lines.append("\n**Recommendations:**")
            for i, rec in enumerate(analysis.recommendations[:3], 1):  # Top 3 recommendations
                lines.append(f"\n**{i}.** {rec}")

        # Question breakdown with improved structure
        if analysis.question_breakdown:
            lines.append("\n**Question Breakdown:**")
            for question, breakdown in list(analysis.question_breakdown.items())[:3]:  # Top 3 questions
                lines.append(f"\n**Q: {question}**")
                lines.append(f"\nTheme: {breakdown.theme}")
                lines.append(f"\nSentiment: {breakdown.sentiment.title()}")
                if breakdown.key_insights:
                    lines.append("\nKey insights:")
                    for insight in breakdown.key_insights[:2]:  # Limit to 2 insights per question
                        lines.append(f"- {insight}")

        lines.append("\n---")
        lines.append("*Need more detail? Ask me to dive deeper into any specific aspect.*")

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
                return "No survey data provided", {
                    "error": "no_survey_data",
                    "details": "Survey information not found in context",
                }

            # Analyze the responses
            analysis_result = await self._analyze_responses(responses)

            if analysis_result.response_count == 0:
                success_message = f"No open-ended responses found in survey '{survey_name}' to analyze"
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
            return f"Failed to analyze survey responses: {str(e)}", {"error": "analysis_failed", "details": str(e)}
