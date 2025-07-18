"""
MaxTool for AI-powered survey creation.
"""

from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from asgiref.sync import sync_to_async
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, Survey

from ee.hogai.tool import MaxTool
from posthog.schema import SurveyCreationSchema
from posthog.constants import DEFAULT_SURVEY_APPEARANCE
from .prompts import SURVEY_CREATION_SYSTEM_PROMPT


class SurveyCreatorArgs(BaseModel):
    instructions: str = Field(description="Natural language description of the survey to create")


class CreateSurveyTool(MaxTool):
    name: str = "create_survey"
    description: str = "Create and optionally launch a survey based on natural language instructions"
    thinking_message: str = "Creating your survey"

    args_schema: type[BaseModel] = SurveyCreatorArgs

    async def _create_survey_from_instructions(self, instructions: str) -> SurveyCreationSchema:
        """
        Create a survey from natural language instructions.
        """
        # Create the prompt
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SURVEY_CREATION_SYSTEM_PROMPT),
                ("human", "Create a survey based on these instructions: {{{instructions}}}"),
            ],
            template_format="mustache",
        )

        # Set up the LLM with structured output
        model = (
            ChatOpenAI(model="gpt-4.1-mini", temperature=0.2)
            .with_structured_output(SurveyCreationSchema, include_raw=False)
            .with_retry()
        )

        # Generate the survey configuration
        chain = prompt | model
        result = await chain.ainvoke(
            {
                "instructions": instructions,
                "existing_surveys": await self._get_existing_surveys_summary(),
                "team_survey_config": self._get_team_survey_config(self._team),
            }
        )

        return result

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

                # Convert to PostHog survey format
                survey_data = self._convert_to_posthog_format(result, team)

                # Set launch date if requested
                if result.should_launch:
                    survey_data["start_date"] = datetime.now()

                # Create the survey directly using Django ORM
                survey = await sync_to_async(Survey.objects.create)(team=team, created_by=user, **survey_data)

                launch_msg = " and launched" if result.should_launch else ""
                return f"✅ Survey '{survey.name}' created{launch_msg} successfully!", {
                    "survey_id": str(survey.id),
                    "survey_name": survey.name,
                    "launched": result.should_launch,
                    "questions_count": len(survey.questions),
                }

            except Exception as validation_error:
                return f"❌ Survey validation failed: {str(validation_error)}", {
                    "error": "validation_failed",
                    "details": str(validation_error),
                }

        except Exception as e:
            capture_exception(e, {"team_id": self._team.id, "user_id": self._user.id})
            return f"❌ Failed to create survey: {str(e)}", {"error": str(e)}

    def _get_team_survey_config(self, team: Team) -> dict[str, Any]:
        """Get team survey configuration for context."""
        survey_config = getattr(team, "survey_config", {}) or {}
        return {
            "appearance": survey_config.get("appearance", {}),
            "default_settings": {"type": "popover", "enable_partial_responses": True},
        }

    async def _get_existing_surveys_summary(self) -> str:
        """Get summary of existing surveys for context."""
        try:
            # Use sync_to_async to convert the Django QuerySet to async
            surveys = await sync_to_async(list)(
                Survey.objects.filter(
                    team_id=self._team.id,
                    archived=False,
                )[:5]
            )

            if not surveys:
                return "No existing surveys"

            summaries = []
            for survey in surveys:
                status = "active" if survey.start_date and not survey.end_date else "draft"
                summaries.append(f"- '{survey.name}' ({survey.type}, {status})")

            return "\n".join(summaries)
        except Exception as e:
            capture_exception(e, {"team_id": self._team.id})
            return "Unable to load existing surveys"

    def _convert_to_posthog_format(self, llm_output: SurveyCreationSchema, team: Team) -> dict[str, Any]:
        """Convert LLM output to PostHog survey format."""
        # Convert questions to PostHog format
        questions = []
        for q in llm_output.questions:
            question_data = {
                "type": q.type,
                "question": q.question,
                "description": q.description or "",
                "optional": q.optional,
                "buttonText": q.buttonText,
            }

            # Add type-specific fields
            if q.type in ["single_choice", "multiple_choice"] and q.choices:
                question_data["choices"] = q.choices
            elif q.type == "rating":
                if q.display:
                    question_data["display"] = q.display
                if q.scale:
                    question_data["scale"] = q.scale
                if q.lowerBoundLabel:
                    question_data["lowerBoundLabel"] = q.lowerBoundLabel
                if q.upperBoundLabel:
                    question_data["upperBoundLabel"] = q.upperBoundLabel
            elif q.type == "link" and q.link:
                question_data["link"] = q.link

            # Add skipSubmitButton for rating and single_choice questions
            if q.type in ["rating", "single_choice"] and q.skipSubmitButton is not None:
                question_data["skipSubmitButton"] = q.skipSubmitButton

            questions.append(question_data)

        # Build the survey data
        survey_data = {
            "name": llm_output.name,
            "description": llm_output.description,
            "type": llm_output.type,
            "questions": questions,
            "archived": False,
            "enable_partial_responses": llm_output.enable_partial_responses,
        }

        # Add conditions if specified
        if llm_output.conditions:
            conditions = {}
            if llm_output.conditions.url:
                conditions["url"] = llm_output.conditions.url
                conditions["urlMatchType"] = llm_output.conditions.urlMatchType or "contains"
            if llm_output.conditions.selector:
                conditions["selector"] = llm_output.conditions.selector
            if llm_output.conditions.seenSurveyWaitPeriodInDays:
                conditions["seenSurveyWaitPeriodInDays"] = llm_output.conditions.seenSurveyWaitPeriodInDays
            if llm_output.conditions.deviceTypes:
                conditions["deviceTypes"] = llm_output.conditions.deviceTypes
            if llm_output.conditions.deviceTypesMatchType:
                conditions["deviceTypesMatchType"] = llm_output.conditions.deviceTypesMatchType

            if conditions:
                survey_data["conditions"] = conditions

        # Add appearance settings with proper defaults
        # Start with the frontend default appearance
        appearance = DEFAULT_SURVEY_APPEARANCE.copy()

        # Override with team-specific defaults if they exist
        team_appearance = self._get_team_survey_config(team).get("appearance", {})
        if team_appearance:
            appearance.update(team_appearance)

        # Finally, override with LLM-specified appearance settings
        if llm_output.appearance:
            # Convert the appearance object to dict
            if hasattr(llm_output.appearance, "model_dump"):
                llm_appearance = llm_output.appearance.model_dump(exclude_unset=False)
            else:
                llm_appearance = llm_output.appearance.__dict__
            # Only update fields that are actually set (not None)
            appearance.update({k: v for k, v in llm_appearance.items() if v is not None})

        # Always set appearance to ensure surveys have consistent defaults
        survey_data["appearance"] = appearance

        return survey_data
