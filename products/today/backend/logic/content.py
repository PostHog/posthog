"""The briefing text as it is stored."""

from pydantic import BaseModel, ConfigDict, Field


class ContentSegment(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    # The item this segment links to, or None for plain text.
    item_key: str | None = None
    highlight: bool = False


class BriefingContent(BaseModel):
    """Stored in `DailyBriefing.content`. Empty content validates, so a row that is not written yet still reads."""

    model_config = ConfigDict(frozen=True)

    headline: str = ""
    paragraphs: list[list[ContentSegment]] = Field(default_factory=list)
    # Left-bar label and signal per item key.
    labels: dict[str, str] = Field(default_factory=dict)
    signals: dict[str, str] = Field(default_factory=dict)
