"""Summarizer scanner: one core turn producing a title + body, embedded whole for free-text search."""

from collections.abc import Sequence
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, Field, field_validator

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.temporal.scanners.base import (
    BaseScanner,
    BaseScannerOutput,
    EmbeddingDocument,
    Segment,
    confidence_field,
    key_moment_field,
    notability_field,
    notability_reason_field,
    strip_citation_markers,
    thumbnail_field,
)
from products.replay_vision.backend.temporal.video_clock import VideoClock

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "4-6 sentences in two short paragraphs separated by a blank line",
    "long": "3-5 short paragraphs separated by blank lines",
}


CHAPTER_TITLE_MAX_LENGTH = 50
# Past this many, a breakdown stops being a summary, and every chapter costs a rendered thumbnail frame.
MAX_CHAPTERS = 20
MIN_CHAPTER_TARGET = 3
# Seconds of video per chapter the prompt aims for. Without a target scaled to the length, the model gives a
# 20-minute session the same two chapters it gives a 1-minute one.
VIDEO_S_PER_CHAPTER = 90


def chapter_target(video_duration_s: float) -> int:
    return max(MIN_CHAPTER_TARGET, min(MAX_CHAPTERS, round(video_duration_s / VIDEO_S_PER_CHAPTER)))


class SummaryChapterResponse(BaseModel, frozen=True):
    """One part of the recording as the model sees it; the chapter ends where the next one starts."""

    # No bounds or required fields here: one malformed chapter would fail the whole summary, so `resolve_chapters`
    # repairs or drops it instead.
    start_t: int | None = Field(
        default=None,
        description=(
            "When this part starts, in whole seconds of video time counted from the start of the video file, the "
            "same scale you cite moments in, not the footer's `REC_T`. The first chapter starts at 0."
        ),
    )
    title: str = Field(
        default="",
        description=(
            "What the user does in this part, in 2 to 6 words, used as a heading. Name the specific page, section, "
            "feature or content involved, so two chapters on the same page read differently (e.g. 'Reads surveys "
            "pricing table', 'Opens install with AI prompt', 'Checkout fails on payment', not 'Browses page'). "
            "Describe what happened neutrally, whatever the summary focuses on. Never copy text the user typed and "
            "never name a person. Sentence case, no final period."
        ),
    )
    thumbnail_t: int | None = Field(
        default=None,
        description=(
            "The frame that best shows this part, in whole seconds of video time, inside this chapter. Pick a "
            "frame where the screen shows the thing itself, not a blank page or a full-page spinner."
        ),
    )

    @field_validator("title", mode="after")
    @classmethod
    def _shorten_title(cls, value: str) -> str:
        cleaned = strip_citation_markers(value).rstrip(".")
        if len(cleaned) <= CHAPTER_TITLE_MAX_LENGTH:
            return cleaned
        # Cut at a word boundary so the heading never ends in half a word.
        return cleaned[: CHAPTER_TITLE_MAX_LENGTH + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")


# A boundary the model put this close to a cut was meant for the cut, because whole video seconds cannot hit it exactly.
CUT_SNAP_S = 3.0


class SummaryChapter(BaseModel, frozen=True):
    """One persisted chapter, on the session clock the player seeks to; chapters are in order and never overlap.

    Inactive time between chapters is a gap, listed in `SummarizerOutput.inactive_periods`. Chapters stored
    before that list existed can carry `kind: idle` entries, which readers skip.
    """

    kind: Literal["activity", "idle"] = "activity"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    title: str
    thumbnail_ms: int | None = Field(default=None, ge=0)


class InactivePeriod(BaseModel, frozen=True):
    """A stretch the replay player marked inactive, which the analysis video cut out."""

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class SummarizerSummaryResponse(BaseModel, frozen=True):
    """The core turn: title + body summary. Field order is load-bearing — `confidence` last, after the content."""

    title: str = Field(
        max_length=120,
        description=(
            "Short title for the session (~80 chars). Plain text, no quotes. If the team's context specifies "
            "a naming convention or format for observations, the title must follow it exactly."
        ),
    )
    summary: str = Field(description="Body text whose length follows the scanner's configured length.")
    # Optional so that a model that skips the breakdown still produces a paid-for summary.
    chapters: list[SummaryChapterResponse] = Field(
        default_factory=list,
        description=(
            "The recording broken down into its distinct parts, in order, covering the whole video, one chapter per "
            "thing the user did, as many as the instruction asks for. Give a notable moment (an error, a blocker, a "
            "burst of rage clicks) its own short chapter so it can be jumped to directly."
        ),
    )
    notability_reason: str | None = notability_reason_field()
    notability: float | None = notability_field()
    confidence: float = confidence_field()
    key_moment_t: int | None = key_moment_field()
    thumbnail_t: int | None = thumbnail_field()


class SummarizerOutput(BaseScannerOutput, frozen=True):
    """Persisted output: the summary turn's fields."""

    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    title: str = ""
    summary: str = ""
    summary_segments: list[Segment] = Field(default_factory=list)
    chapters: list[SummaryChapter] = Field(default_factory=list)
    inactive_periods: list[InactivePeriod] = Field(default_factory=list)

    def embedding_document(self) -> EmbeddingDocument | None:
        text = summary_embedding_text(self)
        return EmbeddingDocument(rendering="summary", text=text) if text else None

    def to_event_properties(self) -> dict[str, Any]:
        # A count is enough to chart adoption, and the full list would make every event carry the whole breakdown.
        properties = super().to_event_properties()
        del properties["scanner_output_chapters"]
        del properties["scanner_output_inactive_periods"]
        properties["scanner_output_chapter_count"] = len(self.chapters)
        return properties


def summary_embedding_text(output: SummarizerOutput) -> str:
    """The single document embedded for search: title and body together, so a query can match either."""
    return "\n\n".join(part for part in (output.title.strip(), output.summary.strip()) if part)


def resolve_chapters(
    chapters: Sequence[SummaryChapterResponse], duration_ms: int, clock: VideoClock
) -> list[SummaryChapter]:
    """Repair the model's chapters into an ordered list over the active time, on the session clock.

    A malformed breakdown is repaired rather than re-prompted, because a re-prompt bills the whole conversation
    again for a field the scan does not depend on. Chapters tile the video, which has the inactive time cut out.
    A boundary near a cut snaps onto it, so on the session clock the inactive time falls between two chapters.
    """
    video_end_s = clock.citable_duration_s(duration_ms / 1000)
    if not video_end_s:
        return []
    cuts = clock.cuts_video_s()
    starts: dict[float, SummaryChapterResponse] = {}
    # A negative start clamps to 0, and a start at or past the video's end is a time the model invented, which
    # would make an empty chapter.
    for chapter in chapters:
        if chapter.start_t is None or not chapter.title or chapter.start_t >= video_end_s:
            continue
        start_s = float(max(0, chapter.start_t))
        nearest_cut = min(cuts, key=lambda cut: abs(cut - start_s), default=None)
        # The first chapter starts at 0 regardless, so snapping a 0 start would only collide it with the next one.
        if start_s > 0 and nearest_cut is not None and abs(nearest_cut - start_s) <= CUT_SNAP_S:
            start_s = nearest_cut
        starts.setdefault(start_s, chapter)
    kept = sorted(starts.items())[:MAX_CHAPTERS]
    if not kept:
        return []

    resolved: list[SummaryChapter] = []
    for index, (start_s, chapter) in enumerate(kept):
        start_s = 0.0 if index == 0 else start_s
        end_s = kept[index + 1][0] if index + 1 < len(kept) else video_end_s
        start_ms, end_ms = clock.video_s_to_session_ms(start_s), clock.video_end_s_to_session_ms(end_s)
        # Checked on the session clock, because a video second at a cut can map onto the chapter's exclusive end.
        thumbnail_ms = clock.video_s_to_session_ms(chapter.thumbnail_t) if chapter.thumbnail_t is not None else None
        if thumbnail_ms is None or not start_ms <= thumbnail_ms < end_ms:
            thumbnail_ms = clock.video_s_to_session_ms((start_s + end_s) / 2)
        resolved.append(
            SummaryChapter(start_ms=start_ms, end_ms=end_ms, title=chapter.title, thumbnail_ms=thumbnail_ms)
        )
    return resolved


def inactive_periods(clock: VideoClock, duration_ms: int) -> list[InactivePeriod]:
    return [
        InactivePeriod(start_ms=stretch.start_ms, end_ms=stretch.end_ms)
        for stretch in clock.inactive_session_ms(duration_ms)
    ]


class SummarizerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    core_step_template: ClassVar[str] = "summarizer_summary_step.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("summary",)
    output_cls: ClassVar[type[BaseScannerOutput]] = SummarizerOutput
    length: SummaryLength = "medium"
    chapter_target: int = MIN_CHAPTER_TARGET
    session_fields: ClassVar[frozenset[str]] = BaseScanner.session_fields | {"chapter_target"}

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return SummarizerSummaryResponse

    def prompt_context(self) -> dict[str, Any]:
        return {
            "length_guidance": _LENGTH_GUIDANCE[self.length],
            "chapter_target": self.chapter_target,
        }

    def bind_session(self, clock: VideoClock, duration_ms: int) -> Self:
        # The video is the active time only, so the target follows how much the user did, not how long the tab was open.
        return self.model_copy(
            update={"chapter_target": chapter_target(clock.citable_duration_s(duration_ms / 1000) or 0)}
        )

    def resolve_session_clock(
        self, output: BaseScannerOutput, core_response: BaseModel | None, clock: VideoClock, duration_ms: int
    ) -> BaseScannerOutput:
        if not isinstance(output, SummarizerOutput):
            return output
        chapters = getattr(core_response, "chapters", ())
        return output.model_copy(
            update={
                "chapters": resolve_chapters(chapters, duration_ms, clock),
                "inactive_periods": inactive_periods(clock, duration_ms),
            }
        )

    def finalize(self, llm_response: BaseModel) -> BaseScannerOutput:
        # Chapters join the output in the provider activity, which holds the clock that moves them onto session time.
        return SummarizerOutput(**llm_response.model_dump(exclude={"chapters"}))
