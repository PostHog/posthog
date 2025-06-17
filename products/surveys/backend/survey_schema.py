"""
Pydantic schemas for survey creation LLM output.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum
from posthog.constants import DEFAULT_SURVEY_APPEARANCE


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
    question: str = Field(description="The question text")
    description: Optional[str] = Field(
        default="",
        description="Optional question description. Usually not needed, but can be used to provide more context for the question if it's a loaded question.",
    )
    optional: bool = Field(default=False, description="Whether the question is optional")
    buttonText: str = Field(default="Submit", description="Text for submit button")

    # For single_choice and multiple_choice
    choices: Optional[list[str]] = Field(default=None, description="Answer choices for choice questions")

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


class SurveyDisplayConditionsSchema(BaseModel):
    url: Optional[str] = Field(default=None, description="URL pattern to match")
    urlMatchType: Optional[Literal["contains", "exact", "regex"]] = Field(default="contains")
    selector: Optional[str] = Field(default=None, description="CSS selector")


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
    name: str = Field(description="Survey name")
    description: str = Field(description="Survey description.")
    type: SurveyTypeEnum = Field(default=SurveyTypeEnum.POPOVER, description="Survey type")
    questions: list[SurveyQuestionSchema] = Field(description="List of survey questions")
    should_launch: bool = Field(default=False, description="Whether to launch immediately")
    conditions: Optional[SurveyDisplayConditionsSchema] = Field(default=None, description="Display conditions")
    appearance: Optional[SurveyAppearanceSchema] = Field(
        default_factory=lambda: SurveyAppearanceSchema(), description="Appearance settings"
    )
    enable_partial_responses: bool = Field(
        default=True,
        description="Should always be True by default, unless the user explicitly asks for it to be False.",
    )

    def get_appearance_with_defaults(self) -> dict:
        """Get appearance settings with all defaults applied."""
        if self.appearance is None:
            return DEFAULT_SURVEY_APPEARANCE.copy()

        # Convert Pydantic model to dict and fill in any missing values with defaults
        appearance_dict = self.appearance.model_dump(exclude_unset=False)
        result = DEFAULT_SURVEY_APPEARANCE.copy()
        result.update({k: v for k, v in appearance_dict.items() if v is not None})
        return result


def get_survey_appearance_with_defaults(
    llm_appearance: Optional[SurveyAppearanceSchema] = None, team_appearance: Optional[dict] = None
) -> dict:
    """
    Get survey appearance with proper defaults applied in order:
    1. Frontend defaults
    2. Team-specific overrides
    3. LLM-specified overrides
    """
    appearance = DEFAULT_SURVEY_APPEARANCE.copy()

    # Apply team defaults if provided
    if team_appearance:
        appearance.update(team_appearance)

    # Apply LLM appearance if provided
    if llm_appearance:
        llm_dict = llm_appearance.model_dump(exclude_unset=False)
        appearance.update({k: v for k, v in llm_dict.items() if v is not None})

    return appearance
