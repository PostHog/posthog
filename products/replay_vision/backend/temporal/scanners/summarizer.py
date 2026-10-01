"""Summarizer scanner: one core turn producing a title + body, embedded whole for free-text search."""

from collections.abc import Sequence
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, Field, field_validator

from posthog.dataclasses import frozen

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
from products.replay_vision.backend.temporal.video_clock import IdleStretch, VideoClock

SummaryLength = Literal["short", "medium", "long"]

_LENGTH_GUIDANCE: dict[SummaryLength, str] = {
    "short": "1-2 sentences",
    "medium": "1 paragraph",
    "long": "3-5 paragraphs",
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


IDLE_CHAPTER_TITLE = "Idle"
# A shorter pause is part of whatever the user was doing around it, so it stays inside that chapter.
LONG_IDLE_MS = 60_000
MAX_IDLE_CHAPTERS = 10


class SummaryChapter(BaseModel, frozen=True):
    """One persisted chapter, on the session clock the player seeks to; chapters tile the recording in order.

    An `idle` chapter is a stretch of at least `LONG_IDLE_MS` the player marked inactive. It comes from the render,
    never from the model, and has no thumbnail because the analysis video cut it out.
    """

    kind: Literal["activity", "idle"] = "activity"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    title: str
    thumbnail_ms: int | None = Field(default=None, ge=0)


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

    def embedding_document(self) -> EmbeddingDocument | None:
        text = summary_embedding_text(self)
        return EmbeddingDocument(rendering="summary", text=text) if text else None

    def to_event_properties(self) -> dict[str, Any]:
        # A count is enough to chart adoption, and the full list would make every event carry the whole breakdown.
        properties = super().to_event_properties()
        del properties["scanner_output_chapters"]
        properties["scanner_output_chapter_count"] = len(self.chapters)
        return properties


def summary_embedding_text(output: SummarizerOutput) -> str:
    """The single document embedded for search: title and body together, so a query can match either."""
    return "\n\n".join(part for part in (output.title.strip(), output.summary.strip()) if part)


def resolve_chapters(
    chapters: Sequence[SummaryChapterResponse], duration_ms: int, clock: VideoClock
) -> list[SummaryChapter]:
    """Repair the model's chapters into an ordered list that tiles the recording, on the session clock.

    A malformed breakdown is repaired rather than re-prompted, because a re-prompt bills the whole conversation
    again for a field the scan does not depend on. Each chapter ends where the next one starts, so the list can
    have neither gaps nor overlaps. The stretches the player marked inactive are then cut out into idle chapters.
    """
    video_end_s = clock.citable_duration_s(duration_ms / 1000)
    if not video_end_s:
        return []
    starts: dict[int, SummaryChapterResponse] = {}
    # A negative start clamps to 0, and a start at or past the video's end is a time the model invented, which
    # would make an empty chapter.
    for chapter in chapters:
        if chapter.start_t is not None and chapter.title and chapter.start_t < video_end_s:
            starts.setdefault(max(0, chapter.start_t), chapter)
    kept = sorted(starts.items())[:MAX_CHAPTERS]
    if not kept:
        return []

    resolved: list[SummaryChapter] = []
    for index, (start_t, chapter) in enumerate(kept):
        start_s = 0.0 if index == 0 else float(start_t)
        end_s = float(kept[index + 1][0]) if index + 1 < len(kept) else video_end_s
        thumbnail_t = chapter.thumbnail_t
        # A pick outside its chapter is dropped here, and `_split_out_idle` falls back to the midpoint.
        thumbnail_ms = (
            clock.video_s_to_session_ms(thumbnail_t)
            if thumbnail_t is not None and start_s <= thumbnail_t < end_s
            else None
        )
        resolved.append(
            SummaryChapter(
                # Pinned, because the render's first kept stretch can start after the session does.
                start_ms=0 if index == 0 else clock.video_s_to_session_ms(start_s),
                # The last chapter runs to the end of the session, which can be past the video's end when the render cut trailing inactivity.
                end_ms=clock.video_s_to_session_ms(end_s) if index + 1 < len(kept) else duration_ms,
                title=chapter.title,
                thumbnail_ms=thumbnail_ms,
            )
        )
    return _split_out_idle(resolved, _long_idle(clock, duration_ms))


@frozen
class IdleBreak:
    """A long idle stretch as the prompt names it: where the video resumes, and how long the user was away."""

    video_s: int
    idle_s: int


def long_idle_breaks(clock: VideoClock, duration_ms: int) -> tuple[IdleBreak, ...]:
    """One break per long idle between two stretches of activity.

    Idle at the very start or end of the session has no activity on one side, so it cannot split a chapter.
    """
    return tuple(
        IdleBreak(
            video_s=int(clock.session_ms_to_video_s(stretch.end_ms)),
            idle_s=(stretch.end_ms - stretch.start_ms) // 1000,
        )
        for stretch in _long_idle(clock, duration_ms)
        if stretch.start_ms > 0 and stretch.end_ms < duration_ms
    )


def _long_idle(clock: VideoClock, duration_ms: int) -> list[IdleStretch]:
    """The long idle stretches, at most the `MAX_IDLE_CHAPTERS` longest, in order.

    Each one adds an idle chapter and can split another, so the bound keeps the timeline and its frames bounded.
    """
    long_idle = [s for s in clock.inactive_session_ms(duration_ms) if s.end_ms - s.start_ms >= LONG_IDLE_MS]
    longest = sorted(long_idle, key=lambda s: s.start_ms - s.end_ms)[:MAX_IDLE_CHAPTERS]
    return sorted(longest, key=lambda s: s.start_ms)


# The model cites whole video seconds, so a boundary it meant to put at a cut can land a second or two past it.
_MIN_ACTIVITY_FRAGMENT_MS = 3_000


@frozen(frozen=False)
class _Piece:
    """A stretch of the session while idle stretches are cut out; `source` is None for an idle one."""

    start_ms: int
    end_ms: int
    source: SummaryChapter | None
    # True for a piece an idle stretch cut off a chapter; a whole chapter is never merged away, however short.
    fragment: bool = False


def _split_out_idle(chapters: list[SummaryChapter], idle: list[IdleStretch]) -> list[SummaryChapter]:
    """Cut each inactive stretch out of the chapters it overlaps and put an idle chapter in its place.

    A chapter that an idle stretch splits keeps its title on both sides. A fragment too short to be a real
    part of the session joins the neighbouring activity chapter, or the idle stretch when it has none.
    """
    pieces: list[_Piece] = []
    for chapter in chapters:
        cursor = chapter.start_ms
        cut = False
        for stretch in idle:
            start, end = max(stretch.start_ms, chapter.start_ms), min(stretch.end_ms, chapter.end_ms)
            if end <= start:
                continue
            if start > cursor:
                pieces.append(_Piece(start_ms=cursor, end_ms=start, source=chapter, fragment=True))
            pieces.append(_Piece(start_ms=start, end_ms=end, source=None))
            cursor, cut = end, True
        if cursor < chapter.end_ms:
            pieces.append(_Piece(start_ms=cursor, end_ms=chapter.end_ms, source=chapter, fragment=cut))

    index = 0
    while index < len(pieces):
        piece = pieces[index]
        if not piece.fragment or piece.end_ms - piece.start_ms >= _MIN_ACTIVITY_FRAGMENT_MS:
            index += 1
            continue
        before = pieces[index - 1] if index > 0 else None
        after = pieces[index + 1] if index + 1 < len(pieces) else None
        if after is not None and after.source is not None:
            after.start_ms = piece.start_ms
        elif before is not None and before.source is not None:
            before.end_ms = piece.end_ms
        else:
            piece.source = None
            index += 1
            continue
        pieces.pop(index)

    resolved: list[SummaryChapter] = []
    for piece in pieces:
        if piece.source is None:
            if resolved and resolved[-1].kind == "idle":
                resolved[-1] = resolved[-1].model_copy(update={"end_ms": piece.end_ms})
            else:
                resolved.append(
                    SummaryChapter(kind="idle", start_ms=piece.start_ms, end_ms=piece.end_ms, title=IDLE_CHAPTER_TITLE)
                )
            continue
        thumbnail_ms = piece.source.thumbnail_ms
        if thumbnail_ms is None or not piece.start_ms <= thumbnail_ms < piece.end_ms:
            thumbnail_ms = (piece.start_ms + piece.end_ms) // 2
        resolved.append(
            SummaryChapter(
                start_ms=piece.start_ms, end_ms=piece.end_ms, title=piece.source.title, thumbnail_ms=thumbnail_ms
            )
        )
    return resolved


class SummarizerScanner(BaseScanner, frozen=True):
    scanner_type: Literal[ScannerType.SUMMARIZER] = ScannerType.SUMMARIZER
    core_step_template: ClassVar[str] = "summarizer_summary_step.jinja"
    citation_fields: ClassVar[tuple[str, ...]] = ("summary",)
    output_cls: ClassVar[type[BaseScannerOutput]] = SummarizerOutput
    length: SummaryLength = "medium"
    # (video second the video resumes at, idle seconds) per long idle stretch, set per session before the scan runs.
    long_idle_breaks: tuple[IdleBreak, ...] = ()
    chapter_target: int = MIN_CHAPTER_TARGET
    session_fields: ClassVar[frozenset[str]] = frozenset({"long_idle_breaks", "chapter_target"})

    @property
    def llm_response_schema(self) -> type[BaseModel]:
        return SummarizerSummaryResponse

    def prompt_context(self) -> dict[str, Any]:
        return {
            "length_guidance": _LENGTH_GUIDANCE[self.length],
            "long_idle_breaks": self.long_idle_breaks,
            "chapter_target": self.chapter_target,
        }

    def bind_session(self, clock: VideoClock, duration_ms: int) -> Self:
        # The video has the idle time cut out, so the model cannot see a long break unless the prompt names it.
        return self.model_copy(
            update={
                "long_idle_breaks": long_idle_breaks(clock, duration_ms),
                "chapter_target": chapter_target(clock.citable_duration_s(duration_ms / 1000) or 0),
            }
        )

    def resolve_session_clock(
        self, output: BaseScannerOutput, core_response: BaseModel | None, clock: VideoClock, duration_ms: int
    ) -> BaseScannerOutput:
        if not isinstance(output, SummarizerOutput):
            return output
        chapters = getattr(core_response, "chapters", ())
        return output.model_copy(update={"chapters": resolve_chapters(chapters, duration_ms, clock)})

    def finalize(self, llm_response: BaseModel) -> BaseScannerOutput:
        # Chapters join the output in the provider activity, which holds the clock that moves them onto session time.
        return SummarizerOutput(**llm_response.model_dump(exclude={"chapters"}))
