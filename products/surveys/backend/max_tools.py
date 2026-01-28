"""
MaxTool for AI-powered survey creation and analysis.
"""

from datetime import timedelta
from textwrap import dedent
from typing import Any

import django.utils.timezone

from asgiref.sync import sync_to_async
from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import (
    SurveyAnalysisQuestionGroup,
    SurveyAnalysisResponseItem,
    SurveyAppearanceSchema,
    SurveyCreationSchema,
    SurveyDisplayConditionsSchema,
    SurveyQuestionSchema,
    SurveyType,
)

from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import Survey, Team

from products.surveys.backend.summarization.fetch import fetch_responses

from ee.hogai.tool import MaxTool


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
    """Retrieve survey responses for analysis."""

    survey_id: str | None = Field(
        default=None,
        description="UUID of the survey to analyze. If not provided, uses survey from current context.",
    )


class SurveyAnalysisTool(MaxTool):
    name: str = "analyze_survey_responses"
    description: str = dedent("""
        Retrieve survey responses for analysis.

        # When to use
        - User asks to analyze survey responses or feedback
        - User wants to find themes, patterns, or insights from survey data
        - User asks about sentiment or recommendations from survey feedback

        # Finding the Survey
        If you don't have a survey_id, first use the search tool with kind="surveys" to find it.

        # What this tool returns
        Returns the raw open-ended responses from the survey which you should then analyze
        to extract themes, sentiment, and actionable insights.
    """).strip()
    args_schema: type[BaseModel] = SurveyAnalysisArgs

    def get_required_resource_access(self):
        return [("survey", "viewer")]

    def _format_responses_for_analysis(self, question_groups: list[SurveyAnalysisQuestionGroup]) -> str:
        """
        Format the grouped responses into a string for analysis.
        """
        formatted_sections = []

        for group in question_groups:
            question_name = group.questionName
            responses = group.responses

            formatted_sections.append(f'Question: "{question_name}"')

            response_texts = []
            if responses:
                for response in responses:
                    response_text = response.responseText
                    response_texts.append(f'- "{response_text}"')

            if response_texts:
                formatted_sections.append("Responses:\n" + "\n".join(response_texts))
            else:
                formatted_sections.append("Responses: (none)")
            formatted_sections.append("")

        return "\n".join(formatted_sections)

    async def _fetch_survey_responses(self, survey: Survey) -> list[SurveyAnalysisQuestionGroup]:
        """Fetch open-ended responses for a survey from the database."""
        questions = survey.questions or []
        question_groups: list[SurveyAnalysisQuestionGroup] = []

        # Use survey start_date or created_at as the start, and now as the end
        start_date = survey.start_date or survey.created_at or (django.utils.timezone.now() - timedelta(days=365))
        end_date = survey.end_date or django.utils.timezone.now()

        for idx, question in enumerate(questions):
            q_type = question.get("type", "")
            # Only fetch open-ended questions
            if q_type != "open":
                continue

            question_id = question.get("id")
            question_text = question.get("question", f"Question {idx + 1}")

            # Fetch responses for this question
            responses_list = await sync_to_async(fetch_responses)(
                survey_id=str(survey.id),
                question_index=idx,
                question_id=question_id,
                start_date=start_date,
                end_date=end_date,
                team=self._team,
                limit=50,  # Limit responses per question
            )

            # Convert to SurveyAnalysisResponseItem objects
            response_items = [
                SurveyAnalysisResponseItem(
                    responseText=text,
                    isOpenEnded=True,
                )
                for text in responses_list
                if text and text.strip()
            ]

            if response_items:
                question_groups.append(
                    SurveyAnalysisQuestionGroup(
                        questionName=question_text,
                        questionId=question_id or str(idx),
                        responses=response_items,
                    )
                )

        return question_groups

    async def _arun_impl(self, survey_id: str | None = None) -> tuple[str, dict[str, Any]]:
        """
        Retrieve survey responses for the main agent to analyze.
        Returns the formatted responses so the agent can extract themes, sentiment, and insights.
        """
        try:
            # Try to get survey_id from argument first, then from context
            context = self.context or {}
            effective_survey_id = survey_id or context.get("survey_id")

            if not effective_survey_id:
                return (
                    "No survey ID provided. Please provide a survey_id or use the search tool to find a survey first.",
                    {
                        "error": "no_survey_id",
                        "details": "No survey_id argument provided and none found in context",
                    },
                )

            # Fetch the survey from database
            try:
                survey = await sync_to_async(Survey.objects.get)(id=effective_survey_id, team=self._team)
            except Survey.DoesNotExist:
                return f"Survey with ID '{effective_survey_id}' not found.", {
                    "error": "not_found",
                    "details": f"No survey found with ID '{effective_survey_id}' in your team.",
                }

            survey_name = survey.name

            # Fetch responses directly from database
            responses = await self._fetch_survey_responses(survey)

            if not responses:
                return (
                    f"No open-ended responses found in survey '{survey_name}'. The survey may not have open-ended questions or no responses yet.",
                    {
                        "survey_id": str(survey.id),
                        "survey_name": survey_name,
                        "response_count": 0,
                    },
                )

            total_response_count = sum(len(group.responses or []) for group in responses)

            if total_response_count == 0:
                return f"No open-ended responses found in survey '{survey_name}' to analyze.", {
                    "survey_id": str(survey.id),
                    "survey_name": survey_name,
                    "response_count": 0,
                }

            formatted_data = self._format_responses_for_analysis(responses)

            message = dedent(f"""
                Survey: "{survey_name}"
                Total open-ended responses: {total_response_count}

                {formatted_data}

                Please analyze these survey responses and provide:
                1. Key themes with example responses
                2. Overall sentiment (positive, negative, mixed, or neutral)
                3. Actionable insights
                4. Specific recommendations based on the feedback
            """).strip()

            return message, {
                "survey_id": str(survey.id),
                "survey_name": survey_name,
                "response_count": total_response_count,
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to retrieve survey responses: {str(e)}", {"error": "retrieval_failed", "details": str(e)}
