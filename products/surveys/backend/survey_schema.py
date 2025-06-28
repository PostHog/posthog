"""
Pydantic schemas for survey creation LLM output.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from enum import Enum
from posthog.constants import DEFAULT_SURVEY_APPEARANCE
import uuid
from urllib.parse import urlparse


class SurveyTypeEnum(str, Enum):
    POPOVER = "popover"
    WIDGET = "widget"
    API = "api"


class QuestionTypeEnum(str, Enum):
    OPEN = "open"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    RATING = "rating"
    LINK = "link"


class RatingDisplayEnum(str, Enum):
    NUMBER = "number"
    EMOJI = "emoji"


class SurveyQuestionSchema(BaseModel):
    type: QuestionTypeEnum
    question: str = Field(min_length=1, description="The question text")
    description: Optional[str] = Field(
        default="",
        description="Optional question description. Usually not needed, but can be used to provide more context for the question if it's a loaded question.",
    )
    descriptionContentType: Optional[Literal["text", "html"]] = Field(
        default="text", description="Content type for description"
    )
    optional: bool = Field(default=False, description="Whether the question is optional")
    buttonText: str = Field(default="Submit", description="Text for submit button")
    id: Optional[str] = Field(default=None, description="Question ID - auto-generated if not provided")

    # For single_choice and multiple_choice
    choices: Optional[list[str]] = Field(default=None, description="Answer choices for choice questions")
    shuffleOptions: Optional[bool] = Field(default=False, description="Whether to shuffle choice options")
    hasOpenChoice: Optional[bool] = Field(default=False, description="Whether to allow open-ended response")

    # For rating questions
    display: Optional[RatingDisplayEnum] = Field(default=RatingDisplayEnum.NUMBER, description="Rating display type")
    scale: Optional[int] = Field(
        default=None, description="Rating scale (e.g., 5, 7, 10). NPS Surveys are always scale 10."
    )
    lowerBoundLabel: Optional[str] = Field(default=None, description="Label for lowest rating")
    upperBoundLabel: Optional[str] = Field(default=None, description="Label for highest rating")
    skipSubmitButton: Optional[bool] = Field(
        default=True,
        description="Whether to skip the submit button for questions that require a single click, like rating or single choice. Default to True when a question is Rating or Single Choice.",
    )

    # For link questions
    link: Optional[str] = Field(default=None, description="URL for link questions")

    @field_validator("scale")
    @classmethod
    def validate_scale(cls, v):
        if v is not None and v not in [5, 7, 10]:
            raise ValueError("Scale must be 5, 7, or 10")
        return v

    @field_validator("link")
    @classmethod
    def validate_link(cls, v):
        if v is not None:
            parsed = urlparse(v)
            if parsed.scheme not in ["https", "mailto"]:
                raise ValueError("Links must use HTTPS or mailto scheme")
        return v

    @model_validator(mode="before")
    @classmethod
    def validate_question_requirements(cls, values):
        if isinstance(values, dict):
            question_type = values.get("type")

            # Validate choices for choice questions
            choices = values.get("choices")
            if question_type in [QuestionTypeEnum.SINGLE_CHOICE, QuestionTypeEnum.MULTIPLE_CHOICE]:
                if not choices or len(choices) == 0:
                    raise ValueError("Choice questions must have at least one choice")
                if any(not choice.strip() for choice in choices):
                    raise ValueError("All choices must be non-empty strings")

            # Ensure required fields are present for each question type
            if question_type == QuestionTypeEnum.RATING:
                if not values.get("scale"):
                    raise ValueError("Rating questions must have a scale")

            if question_type == QuestionTypeEnum.LINK:
                if not values.get("link"):
                    raise ValueError("Link questions must have a link")

            # Auto-generate question ID if not provided
            if not values.get("id"):
                values["id"] = str(uuid.uuid4())

        return values


class SurveyDisplayConditionsSchema(BaseModel):
    url: Optional[str] = Field(default=None, description="URL pattern to match")
    urlMatchType: Optional[Literal["contains", "exact", "regex"]] = Field(default="contains")
    selector: Optional[str] = Field(default=None, description="CSS selector")
    # Additional condition fields from the serializer
    wait_period: Optional[int] = Field(default=None, description="Wait period in seconds before showing survey")
    device_type: Optional[Literal["Desktop", "Mobile", "Tablet"]] = Field(
        default=None, description="Device type targeting"
    )


class SurveyAppearanceSchema(BaseModel):
    backgroundColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["backgroundColor"])
    borderColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["borderColor"])
    position: Optional[Literal["bottom-right", "bottom-left", "top-right", "top-left", "center"]] = Field(
        default=DEFAULT_SURVEY_APPEARANCE["position"]
    )
    thankYouMessageHeader: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["thankYouMessageHeader"])
    thankYouMessageDescription: Optional[str] = Field(default="We appreciate your feedback.")

    # Additional appearance fields to match frontend defaults
    submitButtonColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["submitButtonColor"])
    submitButtonTextColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["submitButtonTextColor"])
    ratingButtonColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["ratingButtonColor"])
    ratingButtonActiveColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["ratingButtonActiveColor"])
    placeholder: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["placeholder"])
    whiteLabel: Optional[bool] = Field(default=DEFAULT_SURVEY_APPEARANCE["whiteLabel"])
    displayThankYouMessage: Optional[bool] = Field(default=DEFAULT_SURVEY_APPEARANCE["displayThankYouMessage"])
    widgetType: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["widgetType"])
    widgetLabel: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["widgetLabel"])
    widgetColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["widgetColor"])
    zIndex: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["zIndex"])
    disabledButtonOpacity: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["disabledButtonOpacity"])
    maxWidth: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["maxWidth"])
    textSubtleColor: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["textSubtleColor"])
    inputBackground: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["inputBackground"])
    boxPadding: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["boxPadding"])
    boxShadow: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["boxShadow"])
    borderRadius: Optional[str] = Field(default=DEFAULT_SURVEY_APPEARANCE["borderRadius"])
    shuffleQuestions: Optional[bool] = Field(default=DEFAULT_SURVEY_APPEARANCE["shuffleQuestions"])
    surveyPopupDelaySeconds: Optional[int] = Field(default=DEFAULT_SURVEY_APPEARANCE["surveyPopupDelaySeconds"])


class SurveyCreationOutput(BaseModel):
    name: str = Field(max_length=400, description="Survey name")
    description: str = Field(description="Survey description.")
    type: SurveyTypeEnum = Field(default=SurveyTypeEnum.POPOVER, description="Survey type")
    questions: list[SurveyQuestionSchema] = Field(min_items=1, description="List of survey questions")
    should_launch: bool = Field(default=False, description="Whether to launch immediately")
    conditions: Optional[SurveyDisplayConditionsSchema] = Field(default=None, description="Display conditions")
    appearance: Optional[SurveyAppearanceSchema] = Field(
        default_factory=lambda: SurveyAppearanceSchema(), description="Appearance settings"
    )
    enable_partial_responses: bool = Field(
        default=True,
        description="Should always be True by default, unless the user explicitly asks for it to be False.",
    )

    # Additional fields from Django model
    start_date: Optional[str] = Field(default=None, description="ISO datetime string for survey start")
    end_date: Optional[str] = Field(default=None, description="ISO datetime string for survey end")
    responses_limit: Optional[int] = Field(default=None, description="Maximum number of responses to collect")
    iteration_count: Optional[int] = Field(default=None, description="Number of iterations for recurring surveys")
    iteration_frequency_days: Optional[int] = Field(default=None, description="Days between iterations")

    # Targeting - simplified for LLM use
    targeting_flag_filters: Optional[dict] = Field(default=None, description="Feature flag filters for targeting")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Survey name cannot be empty")
        return v.strip()

    @field_validator("iteration_count")
    @classmethod
    def validate_iteration_count(cls, v):
        if v is not None and (v < 1 or v > 500):
            raise ValueError("Iteration count must be between 1 and 500")
        return v

    @field_validator("responses_limit")
    @classmethod
    def validate_responses_limit(cls, v):
        if v is not None and v < 1:
            raise ValueError("Response limit must be positive")
        return v
