"""
MaxTool for AI-powered survey creation and analysis.
"""

from datetime import timedelta
from textwrap import dedent
from typing import Any, Literal

import django.utils.timezone

from asgiref.sync import sync_to_async
from pydantic import BaseModel, ConfigDict, Field

from posthog.schema import SurveyAnalysisQuestionGroup, SurveyAnalysisResponseItem

from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from posthog.exceptions_capture import capture_exception
from posthog.models import Survey, Team

from products.surveys.backend.summarization.fetch import fetch_responses

from ee.hogai.tool import MaxTool

SEMANTIC_QUESTION_TYPE = Literal[
    "open",
    "single_choice",
    "multiple_choice",
    "nps",
    "csat",
    "emoji_scale",
    "thumbs",
    "link",
]

QUESTION_TYPE_MAP: dict[str, dict[str, Any]] = {
    "open": {"type": "open"},
    "single_choice": {"type": "single_choice"},
    "multiple_choice": {"type": "multiple_choice"},
    "nps": {"type": "rating", "scale": 10, "display": "number"},
    "csat": {"type": "rating", "scale": 5, "display": "number"},
    "emoji_scale": {"type": "rating", "scale": 5, "display": "emoji"},
    "thumbs": {"type": "rating", "scale": 2, "display": "emoji"},
    "link": {"type": "link"},
}


class SimpleSurveyQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(
        default=None,
        description="Question number from the survey context (e.g. '1', '2', '3'). "
        "Reuse to preserve question identity and historical response data. Omit for new questions.",
    )
    type: SEMANTIC_QUESTION_TYPE
    question: str
    description: str | None = None
    optional: bool | None = None
    choices: list[str] | None = None
    lower_bound_label: str | None = None
    upper_bound_label: str | None = None
    link: str | None = None
    button_text: str | None = None


def get_team_survey_config(team: Team) -> dict[str, Any]:
    """Get team survey configuration for context."""
    survey_config = getattr(team, "survey_config", {}) or {}
    return {
        "appearance": survey_config.get("appearance", {}),
        "default_settings": {"type": "popover", "enable_partial_responses": True},
    }


def _build_question(q: SimpleSurveyQuestion) -> dict[str, Any]:
    """Convert a SimpleSurveyQuestion to the internal question dict."""
    result = dict(QUESTION_TYPE_MAP[q.type])
    result["question"] = q.question
    if q.description is not None:
        result["description"] = q.description
    if q.optional is not None:
        result["optional"] = q.optional
    if q.choices is not None:
        result["choices"] = q.choices
    if q.lower_bound_label is not None:
        result["lowerBoundLabel"] = q.lower_bound_label
    if q.upper_bound_label is not None:
        result["upperBoundLabel"] = q.upper_bound_label
    if q.link is not None:
        result["link"] = q.link
    if q.button_text is not None:
        result["buttonText"] = q.button_text
    return result


def _build_appearance(team: Team) -> dict[str, Any]:
    """Build appearance dict with global + team defaults."""
    appearance = DEFAULT_SURVEY_APPEARANCE.copy()
    team_appearance = get_team_survey_config(team).get("appearance", {})
    if team_appearance:
        appearance.update(team_appearance)
    return appearance


URL_MATCH_ALIASES: dict[str, str] = {
    "exact": "exact",
    "contains": "icontains",
    "icontains": "icontains",
    "regex": "regex",
}

TOOL_MANAGED_CONDITION_KEYS = {"url", "urlMatchType", "linkedFlagVariant", "seenSurveyWaitPeriodInDays"}


def _build_targeting_conditions(
    target_url: str | None,
    target_url_match: str | None,
    linked_flag_variant: str | None,
    wait_period_days: int | None = None,
) -> dict[str, Any]:
    conditions: dict[str, Any] = {}
    if target_url is not None:
        conditions["url"] = target_url
        conditions["urlMatchType"] = URL_MATCH_ALIASES[target_url_match or "contains"]
    if linked_flag_variant is not None:
        conditions["linkedFlagVariant"] = linked_flag_variant
    if wait_period_days is not None:
        conditions["seenSurveyWaitPeriodInDays"] = wait_period_days
    return conditions


SURVEY_CREATION_TOOL_DESCRIPTION = dedent("""
    Create and optionally launch an in-app survey.

    # When to use
    - The user wants to create a new survey
    - The user mentions NPS, CSAT, PMF, or feedback surveys

    # Design principles
    These are in-app surveys shown as overlays. Keep to 1-3 questions.
    DO NOT set should_launch=true unless the user explicitly asks to launch.

    # Survey types
    - "popover" (default): small overlay that appears on the page — use this for most surveys
    - "widget": persistent tab/button on the page edge, good for always-available feedback
    - "api": headless, no UI — for custom implementations only
    Note: hosted surveys (standalone pages with a shareable link) are not yet supported by this tool. If a user asks, let them know it's coming soon.

    # Semantic question types
    - "nps": 0-10 numeric rating (Net Promoter Score)
    - "csat": 1-5 numeric rating (Customer Satisfaction)
    - "emoji_scale": 1-5 emoji rating
    - "thumbs": thumbs up/down (2-point emoji)
    - "open": free-form text
    - "single_choice": pick one from choices
    - "multiple_choice": pick many from choices
    - "link": call-to-action link

    # After creation
    Always share the survey link with the user so they can view and configure it.
    The link is included in the tool response.
    """).strip()


class CreateSurveyToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Survey name")
    description: str = Field(default="", description="Brief survey description")
    questions: list[SimpleSurveyQuestion] = Field(description="List of questions")
    survey_type: Literal["popover", "widget", "api"] = Field(default="popover", description="Survey display type")
    should_launch: bool = Field(default=False, description="Launch immediately after creation")
    target_url: str | None = Field(default=None, description="URL path to target (e.g. '/pricing')")
    target_url_match: Literal["exact", "contains", "regex"] | None = Field(
        default=None, description="How to match the target URL"
    )
    linked_flag_id: int | None = Field(default=None, description="Feature flag ID for targeting")
    linked_flag_variant: str | None = Field(default=None, description="Feature flag variant to target")
    wait_period_days: int | None = Field(
        default=None, description="Days to wait after user has seen any survey before showing this one"
    )
    responses_limit: int | None = Field(default=None, description="Maximum number of responses to collect")


class CreateSurveyTool(MaxTool):
    name: str = "create_survey"
    description: str = SURVEY_CREATION_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = CreateSurveyToolArgs

    def get_required_resource_access(self):
        return [("survey", "editor")]

    async def is_dangerous_operation(self, should_launch: bool = False, **kwargs) -> bool:
        return should_launch is True

    async def format_dangerous_operation_preview(
        self, name: str = "Untitled Survey", questions: list[SimpleSurveyQuestion] | None = None, **kwargs
    ) -> str:
        question_count = len(questions) if questions else 0
        return f"**Create and launch** survey '{name}' with {question_count} question(s). It will immediately start collecting responses."

    def _build_survey_data(
        self,
        *,
        name: str,
        description: str,
        questions: list[SimpleSurveyQuestion],
        survey_type: str,
        target_url: str | None,
        target_url_match: str | None,
        linked_flag_id: int | None,
        linked_flag_variant: str | None,
        wait_period_days: int | None,
        responses_limit: int | None,
    ) -> dict[str, Any]:
        survey_data: dict[str, Any] = {
            "name": name,
            "description": description,
            "type": survey_type,
            "questions": [_build_question(q) for q in questions],
            "appearance": _build_appearance(self._team),
            "archived": False,
            "enable_partial_responses": True,
        }

        if linked_flag_id is not None:
            survey_data["linked_flag_id"] = linked_flag_id

        if responses_limit is not None:
            survey_data["responses_limit"] = responses_limit

        conditions = _build_targeting_conditions(target_url, target_url_match, linked_flag_variant, wait_period_days)
        if conditions:
            survey_data["conditions"] = conditions

        if self.context.get("insight_id"):
            survey_data["linked_insight_id"] = self.context["insight_id"]

        return survey_data

    async def _arun_impl(
        self,
        name: str = "Untitled Survey",
        description: str = "",
        questions: list[SimpleSurveyQuestion] | None = None,
        survey_type: str = "popover",
        should_launch: bool = False,
        target_url: str | None = None,
        target_url_match: str | None = None,
        linked_flag_id: int | None = None,
        linked_flag_variant: str | None = None,
        wait_period_days: int | None = None,
        responses_limit: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            if not questions:
                return "Survey must have at least one question", {
                    "error": "validation_failed",
                    "error_message": "No questions provided in the survey configuration.",
                }

            survey_data = self._build_survey_data(
                name=name,
                description=description,
                questions=questions,
                survey_type=survey_type,
                target_url=target_url,
                target_url_match=target_url_match,
                linked_flag_id=linked_flag_id,
                linked_flag_variant=linked_flag_variant,
                wait_period_days=wait_period_days,
                responses_limit=responses_limit,
            )

            if should_launch:
                survey_data["start_date"] = django.utils.timezone.now()

            created_survey = await Survey.objects.acreate(team=self._team, created_by=self._user, **survey_data)

            launch_msg = " and launched" if should_launch else ""
            survey_id = str(created_survey.id)
            if survey_type == "popover":
                survey_url = f"/surveys/guided/{survey_id}"
            else:
                survey_url = f"/surveys/{survey_id}?edit=true"
            return f"Survey '{created_survey.name}' created{launch_msg} successfully! [View survey]({survey_url})", {
                "survey_id": created_survey.id,
                "survey_name": created_survey.name,
                "survey_type": survey_type,
            }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"Failed to create survey: {str(e)}", {"error": "creation_failed", "details": str(e)}


SURVEY_EDIT_TOOL_DESCRIPTION = dedent("""
    Edit an existing survey.

    # When to use
    - User wants to modify a survey's name, description, or questions
    - User wants to launch, stop, or archive a survey
    - User wants to change survey targeting conditions

    # Finding the survey
    First use the search tool with kind="surveys" to find the survey ID.

    # Lifecycle
    - Set launch=true to start collecting responses
    - Set stop=true to stop collecting responses
    - Set archive=true to archive the survey

    # Question identity
    - When updating questions, use read_data(kind="survey") first to see the current questions
    - Each question is shown with a number (1, 2, 3, ...) — pass that number as the question's `id` to preserve its identity and historical response data
    - Omit `id` for entirely new questions; they will be assigned a fresh ID automatically

    # Important
    - Only include fields you want to change
    - When updating questions, provide the complete list (it replaces existing)
    """).strip()


class EditSurveyToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    survey_id: str = Field(description="UUID of the survey to edit")
    name: str | None = Field(default=None, description="New survey name")
    description: str | None = Field(default=None, description="New survey description")
    questions: list[SimpleSurveyQuestion] | None = Field(default=None, description="Replacement questions list")
    target_url: str | None = Field(default=None, description="URL path to target")
    target_url_match: Literal["exact", "contains", "regex"] | None = Field(
        default=None, description="How to match the target URL"
    )
    linked_flag_id: int | None = Field(default=None, description="Feature flag ID for targeting")
    linked_flag_variant: str | None = Field(default=None, description="Feature flag variant to target")
    wait_period_days: int | None = Field(
        default=None, description="Minimum days before showing this survey again to a user who has seen any survey"
    )
    responses_limit: int | None = Field(default=None, description="Maximum number of responses")
    launch: bool | None = Field(default=None, description="Set to true to launch the survey")
    stop: bool | None = Field(default=None, description="Set to true to stop the survey")
    archive: bool | None = Field(default=None, description="Set to true to archive the survey")


class EditSurveyTool(MaxTool):
    name: str = "edit_survey"
    description: str = SURVEY_EDIT_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = EditSurveyToolArgs

    def get_required_resource_access(self):
        return [("survey", "editor")]

    async def is_dangerous_operation(
        self,
        survey_id: str,
        launch: bool | None = None,
        stop: bool | None = None,
        archive: bool | None = None,
        **kwargs,
    ) -> bool:
        return launch is True or stop is True or archive is True

    async def format_dangerous_operation_preview(
        self,
        survey_id: str,
        launch: bool | None = None,
        stop: bool | None = None,
        archive: bool | None = None,
        **kwargs,
    ) -> str:
        survey_name = survey_id
        try:
            survey = await sync_to_async(Survey.objects.get)(id=survey_id, team=self._team)
            survey_name = f"'{survey.name}'"
        except Survey.DoesNotExist:
            survey_name = f"(ID: {survey_id})"

        actions = []
        if launch is True:
            actions.append("**Launch** the survey (it will start collecting responses)")
        if stop is True:
            actions.append("**Stop** the survey (it will stop collecting responses)")
        if archive is True:
            actions.append("**Archive** the survey")

        if len(actions) == 1:
            return f"{actions[0]} {survey_name}"
        else:
            action_list = "\n".join(f"- {action}" for action in actions)
            return f"Perform the following actions on survey {survey_name}:\n{action_list}"

    async def _arun_impl(
        self,
        survey_id: str,
        name: str | None = None,
        description: str | None = None,
        questions: list[SimpleSurveyQuestion] | None = None,
        target_url: str | None = None,
        target_url_match: str | None = None,
        linked_flag_id: int | None = None,
        linked_flag_variant: str | None = None,
        wait_period_days: int | None = None,
        responses_limit: int | None = None,
        launch: bool | None = None,
        stop: bool | None = None,
        archive: bool | None = None,
    ) -> tuple[str, dict[str, Any]]:
        try:
            team = self._team

            try:
                survey = await sync_to_async(Survey.objects.get)(id=survey_id, team=team)
            except Survey.DoesNotExist:
                return f"Survey with ID '{survey_id}' not found", {
                    "error": "not_found",
                    "error_message": f"No survey found with ID '{survey_id}' in your team.",
                }

            update_data: dict[str, Any] = {}

            if name is not None:
                update_data["name"] = name
            if description is not None:
                update_data["description"] = description
            if questions is not None:
                new_questions = [_build_question(q) for q in questions]
                existing_questions = survey.questions or []

                # Build numeric label -> real UUID mapping (1-indexed, matching read_data output)
                id_map = {str(i + 1): eq["id"] for i, eq in enumerate(existing_questions) if "id" in eq}

                # Resolve numeric labels back to real UUIDs; unknown/missing id -> new question
                for new_q, simple_q in zip(new_questions, questions):
                    if simple_q.id and simple_q.id in id_map:
                        new_q["id"] = id_map[simple_q.id]

                update_data["questions"] = new_questions
            if linked_flag_id is not None:
                update_data["linked_flag_id"] = linked_flag_id
            if responses_limit is not None:
                update_data["responses_limit"] = responses_limit

            # When any targeting field is provided, strip all tool-managed keys
            # from existing conditions first, then apply new values. This prevents
            # stale targeting from accumulating across edits.
            conditions = _build_targeting_conditions(
                target_url, target_url_match, linked_flag_variant, wait_period_days
            )
            if conditions:
                existing_conditions = {
                    k: v for k, v in (survey.conditions or {}).items() if k not in TOOL_MANAGED_CONDITION_KEYS
                }
                update_data["conditions"] = {**existing_conditions, **conditions}

            # Lifecycle bools
            lifecycle_actions = []
            if launch is True:
                update_data["start_date"] = django.utils.timezone.now()
                lifecycle_actions.append("launched")
            if stop is True:
                update_data["end_date"] = django.utils.timezone.now()
                lifecycle_actions.append("stopped")
            if archive is True:
                update_data["archived"] = True
                lifecycle_actions.append("archived")

            if not update_data:
                return "No updates provided", {
                    "error": "no_updates",
                    "error_message": "No fields were provided to update.",
                }

            for field, value in update_data.items():
                setattr(survey, field, value)

            await sync_to_async(survey.save)()

            if lifecycle_actions:
                action_str = " and ".join(lifecycle_actions)
                message = f"Survey '{survey.name}' has been {action_str} successfully!"
            else:
                fields_str = ", ".join(update_data.keys())
                message = f"Survey '{survey.name}' updated successfully! Modified fields: {fields_str}"

            return message, {
                "survey_id": str(survey.id),
                "survey_name": survey.name,
                "updated_fields": list(update_data.keys()),
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
