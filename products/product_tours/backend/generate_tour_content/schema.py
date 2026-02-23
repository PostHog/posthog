from pydantic import BaseModel, Field


class TourStepContent(BaseModel):
    """A single step in the generated tour."""

    step_id: int = Field(description="The step ID, matching exactly what was provided.")
    title: str = Field(description="Short step title, 2-5 words. No markdown formatting.")
    description: str = Field(description="Brief step description, 1-2 sentences. No markdown formatting.")


class TourGenerationResponse(BaseModel):
    """Structured response from the tour generation LLM."""

    steps: list[TourStepContent] = Field(description="List of tour steps with content for each element")
