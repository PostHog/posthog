"""
MaxTool for AI-powered survey creation.
"""

from typing import Any
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ee.hogai.tool import MaxTool
from posthog.models import Team
from .prompts import SURVEY_CREATION_SYSTEM_PROMPT
from .survey_schema import SurveyCreationOutput


class SurveyCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the survey to create")


class SurveyCreatorTool(MaxTool):
    name: str = "create_survey"
    description: str = "Create and optionally launch a survey based on natural language instructions"
    thinking_message: str = "Creating your survey..."

    root_system_prompt_template: str = """
    You are helping create surveys for this PostHog team.

    Current context:
    - Total surveys: {total_surveys_count}
    - Recent surveys: {existing_surveys}

    When creating surveys, consider the existing surveys to avoid duplication and suggest complementary survey strategies.
    """

    args_schema: type[BaseModel] = SurveyCreatorArgs

    def _run_impl(self, instructions: str) -> tuple[str, dict[str, Any]]:
        """
        Generate survey configuration from natural language instructions.
        """
        # Get team for context
        team = Team.objects.get(id=self._team_id)

        # Create the prompt
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SURVEY_CREATION_SYSTEM_PROMPT),
                ("human", "Create a survey based on these instructions: {instructions}"),
            ]
        )

        # Set up the LLM with structured output
        model = (
            ChatOpenAI(model="gpt-4.1-nano", temperature=0.2)
            .with_structured_output(SurveyCreationOutput, include_raw=False)
            .with_retry()
        )

        # Generate the survey configuration
        chain = prompt | model
        result = chain.invoke(
            {
                "instructions": instructions,
                "existing_surveys": self._get_existing_surveys_summary(),
                "team_survey_config": self._get_team_survey_config(team),
            }
        )

        # Convert to PostHog survey format and create directly
        survey_data = self._convert_to_posthog_format(result, team)

        try:
            # Create the survey directly using the model
            from posthog.models import Survey
            from datetime import datetime

            survey = Survey.objects.create(team=team, **survey_data)

            # Launch immediately if requested
            if result.should_launch:
                survey.start_date = datetime.now()
                survey.save()
                launch_msg = " and launched"
            else:
                launch_msg = ""

            return f"✅ Survey '{survey.name}' created{launch_msg} successfully!", {
                "survey_id": str(survey.id),
                "survey_name": survey.name,
                "launched": result.should_launch,
                "questions_count": len(survey.questions) if survey.questions else 0,
            }

        except Exception as e:
            return f"❌ Failed to create survey: {str(e)}", {"error": str(e)}

    def _get_team_survey_config(self, team: Team) -> dict[str, Any]:
        """Get team survey configuration for context."""
        survey_config = getattr(team, "survey_config", {}) or {}
        return {
            "appearance": survey_config.get("appearance", {}),
            "default_settings": {"type": "popover", "enable_partial_responses": True},
        }

    def _get_existing_surveys_summary(self) -> str:
        """Get summary of existing surveys for context."""
        try:
            from posthog.models import Survey

            surveys = Survey.objects.filter(team_id=self._team_id, archived=False)[:5]

            if not surveys:
                return "No existing surveys"

            summaries = []
            for survey in surveys:
                status = "active" if survey.start_date and not survey.end_date else "draft"
                summaries.append(f"- '{survey.name}' ({survey.type}, {status})")

            return "\n".join(summaries)
        except Exception:
            return "Unable to load existing surveys"

    def _convert_to_posthog_format(self, llm_output: SurveyCreationOutput, team: Team) -> dict[str, Any]:
        """Convert LLM output to PostHog survey format."""
        # Convert questions to PostHog format
        questions = []
        for q in llm_output.questions:
            question_data = {
                "type": q.type.value,
                "question": q.question,
                "description": q.description or "",
                "optional": q.optional,
                "buttonText": q.buttonText,
            }

            # Add type-specific fields
            if q.type.value in ["single_choice", "multiple_choice"] and q.choices:
                question_data["choices"] = q.choices
            elif q.type.value == "rating":
                if q.display:
                    question_data["display"] = q.display.value
                if q.scale:
                    question_data["scale"] = q.scale
                if q.lowerBoundLabel:
                    question_data["lowerBoundLabel"] = q.lowerBoundLabel
                if q.upperBoundLabel:
                    question_data["upperBoundLabel"] = q.upperBoundLabel
            elif q.type.value == "link" and q.link:
                question_data["link"] = q.link

            questions.append(question_data)

        # Build the survey data
        survey_data = {
            "name": llm_output.name,
            "description": llm_output.description,
            "type": llm_output.type.value,
            "questions": questions,
            "archived": False,
        }

        # Add conditions if specified
        if llm_output.conditions:
            conditions = {}
            if llm_output.conditions.url:
                conditions["url"] = llm_output.conditions.url
                conditions["urlMatchType"] = llm_output.conditions.urlMatchType or "contains"
            if llm_output.conditions.selector:
                conditions["selector"] = llm_output.conditions.selector

            if conditions:
                survey_data["conditions"] = conditions

        # Add appearance settings
        if llm_output.appearance:
            appearance = {}
            for field in [
                "backgroundColor",
                "borderColor",
                "position",
                "thankYouMessageHeader",
                "thankYouMessageDescription",
            ]:
                value = getattr(llm_output.appearance, field, None)
                if value:
                    appearance[field] = value

            # Merge with team defaults
            team_appearance = self._get_team_survey_config(team).get("appearance", {})
            appearance = {**team_appearance, **appearance}

            if appearance:
                survey_data["appearance"] = appearance

        return survey_data
