"""
Pydantic schemas for survey creation LLM output.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum


class SurveyTypeEnum(str, Enum):
    POPOVER = "popover"
    FULL_SCREEN = "full_screen"
    EMAIL = "email"
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
    description: Optional[str] = Field(default="", description="Optional question description")
    optional: bool = Field(default=False, description="Whether the question is optional")
    buttonText: str = Field(default="Submit", description="Text for submit button")

    # For single_choice and multiple_choice
    choices: Optional[list[str]] = Field(default=None, description="Answer choices for choice questions")

    # For rating questions
    display: Optional[RatingDisplayEnum] = Field(default=None, description="Rating display type")
    scale: Optional[int] = Field(default=None, description="Rating scale (e.g., 5, 7, 10)")
    lowerBoundLabel: Optional[str] = Field(default=None, description="Label for lowest rating")
    upperBoundLabel: Optional[str] = Field(default=None, description="Label for highest rating")

    # For link questions
    link: Optional[str] = Field(default=None, description="URL for link questions")


class SurveyDisplayConditionsSchema(BaseModel):
    url: Optional[str] = Field(default=None, description="URL pattern to match")
    urlMatchType: Optional[Literal["contains", "exact", "regex"]] = Field(default="contains")
    selector: Optional[str] = Field(default=None, description="CSS selector")


class SurveyAppearanceSchema(BaseModel):
    backgroundColor: Optional[str] = Field(default=None)
    borderColor: Optional[str] = Field(default=None)
    position: Optional[Literal["bottom-right", "bottom-left", "top-right", "top-left", "center"]] = Field(
        default="bottom-right"
    )
    thankYouMessageHeader: Optional[str] = Field(default="Thank you!")
    thankYouMessageDescription: Optional[str] = Field(default="We appreciate your feedback.")


class SurveyCreationOutput(BaseModel):
    name: str = Field(description="Survey name")
    description: str = Field(description="Survey description")
    type: SurveyTypeEnum = Field(default=SurveyTypeEnum.POPOVER, description="Survey type")
    questions: list[SurveyQuestionSchema] = Field(description="List of survey questions")
    should_launch: bool = Field(default=False, description="Whether to launch immediately")
    conditions: Optional[SurveyDisplayConditionsSchema] = Field(default=None, description="Display conditions")
    appearance: Optional[SurveyAppearanceSchema] = Field(default=None, description="Appearance settings")
