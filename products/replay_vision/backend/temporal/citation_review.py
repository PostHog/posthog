"""Re-place the scan's `(t N)` citations that point at a moment the page and events on screen contradict.

Jev reads each citation with the page shown at its second and the events recorded around it, and flags the ones
whose sentence those contradict. The flagged citations go back to the scanner as one more turn of the same
conversation, while the video is still cached, with the page each one points at. The model returns a second for each.
A moved citation that Jev still flags is removed. Where Jev is unavailable, every citation stays as written.
"""

import re
import json
import bisect
import asyncio
from collections.abc import Sequence
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, Field

from posthog.dataclasses import frozen
from posthog.temporal.session_replay.rasterize_recording.types import NavigationChange

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import DecisionQuestion, DecisionRequest
from products.ml_inference.backend.facade.enums import DecisionQuestionType
from products.replay_vision.backend.temporal.events_tool import EventsIndex, get_events_around
from products.replay_vision.backend.temporal.metrics import record_citation_review
from products.replay_vision.backend.temporal.navigation import is_navigable_url
from products.replay_vision.backend.temporal.pii_check import JEV_MODEL
from products.replay_vision.backend.temporal.scanners.base import (
    STEP_CITATIONS,
    STEP_CORE,
    TIMESTAMP_CITATION_RE,
    MissionStep,
    strip_citation_markers,
)
from products.replay_vision.backend.temporal.scanners.prompt_env import render_prompt

logger = structlog.get_logger(__name__)

_ResponseT = TypeVar("_ResponseT", bound=BaseModel)

# Jev takes at most 32 questions per request; an answer with more citations than this has its tail left as written.
_MAX_CITATIONS = 24
FLAG_PROBABILITY = 0.5
_JEV_TIMEOUT_SECONDS = 10.0
# Each question reads the whole state, and the model rejects a prompt past its context window (8k tokens for Jeeves,
# 16k for JevK5), so the state stays well under the smaller one.
_MAX_STATE_CHARS = 16_000
_MAX_CLAIM_CHARS = 400
_MAX_VALUE_CHARS = 150
_EVENTS_WINDOW_S = 10
_MAX_EVENTS_PER_CITATION = 4
_EVENT_FIELDS = ("event", "$current_url", "$event_type", "$exception_types", "$exception_values")
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s)|\n")

_FLAG_QUESTION = (
    "The state lists citations an AI wrote about a recorded user session. Each has the claim it closes, the video "
    "second `t` it points at, the page on screen at that second, and the analytics events recorded near it. Look only "
    "at citation {n}. Does the page on screen, or what the events show the user doing, contradict what the claim says "
    "happened at that moment? For example, the claim describes a different page from the one on screen. Answer no "
    "when the claim describes something only visible on screen that the page and events do not rule out."
)


@frozen
class Citation:
    """One cited second in the core answer, numbered in reading order across the citation fields."""

    n: int
    claim: str
    video_s: int


class CitationPlacement(BaseModel, frozen=True):
    n: int = Field(description="The citation's number from the list.")
    t: int | None = Field(
        description="The video second the claim happens at, in whole seconds, or null when you cannot find it."
    )


class CitationPlacementResponse(BaseModel, frozen=True):
    citations: list[CitationPlacement] = Field(description="One entry per citation in the list, by number.")


class CitationReview:
    """Checks the core answer's citations once per mission pass, and holds what it flagged until the answer is fixed."""

    def __init__(
        self,
        *,
        citation_fields: Sequence[str],
        navigation: Sequence[NavigationChange],
        events_index: EventsIndex,
        last_video_second: int | None,
        team_id: int,
        scanner_type: str,
        model: str,
        trace_id: str,
    ) -> None:
        self._fields = tuple(citation_fields)
        self._navigation = sorted(navigation, key=lambda change: change.video_s)
        self._navigation_starts = [change.video_s for change in self._navigation]
        self._events_index = events_index
        self._last_video_second = last_video_second
        self._team_id = team_id
        self._scanner_type = scanner_type
        self._model = model
        self._trace_id = trace_id
        self._flagged: dict[int, Citation] = {}

    def step(self) -> MissionStep:
        return MissionStep(
            name=STEP_CITATIONS,
            instruction="",
            response_model=CitationPlacementResponse,
            required=False,
            validate=self._validate,
            prepare=self._prepare,
        )

    async def _prepare(self, step_outputs: dict[str, BaseModel]) -> str | None:
        self._flagged = {}
        core = step_outputs.get(STEP_CORE)
        if core is None or not self._navigation:
            return None
        citations = citations_in(core, self._fields)[:_MAX_CITATIONS]
        if not citations:
            return None
        probabilities = await asyncio.to_thread(self._contradiction_probabilities, citations)
        if probabilities is None:
            self._record("unavailable", len(citations))
            return None
        flagged = [c for c in citations if probabilities.get(c.n, 0.0) >= FLAG_PROBABILITY]
        self._record("clean", len(citations) - len(flagged))
        if not flagged:
            return None
        self._flagged = {c.n: c for c in flagged}
        logger.info(
            "replay_vision.citation_review.flagged",
            flagged=[(c.n, c.video_s, round(probabilities[c.n], 2)) for c in flagged],
            citations=len(citations),
        )
        return render_prompt(
            "citations_step.jinja",
            citations=[{"n": c.n, "claim": c.claim, "t": c.video_s, "page": self.page_at(c.video_s)} for c in flagged],
            last_video_second=self._last_video_second,
        )

    def _validate(self, parsed: BaseModel) -> str | None:
        if not isinstance(parsed, CitationPlacementResponse):
            return None
        unknown = sorted({p.n for p in parsed.citations} - self._flagged.keys())
        if unknown:
            return f"Citations {unknown} are not in the list. Answer only for the numbered citations."
        last = self._last_video_second
        if last is not None and any(p.t is not None and not 0 <= p.t <= last for p in parsed.citations):
            return f"Every second must be between 0 and {last}, the video's last second, or null."
        return None

    async def apply(self, step_outputs: dict[str, BaseModel]) -> dict[str, BaseModel]:
        """The step outputs with the core answer's flagged citations moved or removed as the review turn decided."""
        if not self._flagged:
            return step_outputs
        placed = step_outputs.get(STEP_CITATIONS)
        core = step_outputs.get(STEP_CORE)
        if not isinstance(placed, CitationPlacementResponse) or core is None:
            # The turn failed, so nobody looked again; the citations stay as written.
            self._record("kept", len(self._flagged))
            return step_outputs
        answers = {p.n: p.t for p in placed.citations if p.n in self._flagged}
        moves = {n: t for n, t in answers.items() if t is None or t != self._flagged[n].video_s}
        self._record("kept", len(self._flagged) - len(moves))
        moved = [Citation(n=n, claim=self._flagged[n].claim, video_s=t) for n, t in moves.items() if t is not None]
        if moved:
            recheck = await asyncio.to_thread(self._contradiction_probabilities, moved)
            for citation in moved:
                if recheck is not None and recheck.get(citation.n, 0.0) >= FLAG_PROBABILITY:
                    moves[citation.n] = None
        self._record("moved", sum(1 for t in moves.values() if t is not None))
        self._record("removed", sum(1 for t in moves.values() if t is None))
        logger.info(
            "replay_vision.citation_review.applied",
            moves=[(n, self._flagged[n].video_s, t) for n, t in sorted(moves.items())],
        )
        if not moves:
            return step_outputs
        return {**step_outputs, STEP_CORE: replace_citations(core, self._fields, moves)}

    def page_at(self, video_s: int) -> str | None:
        """The URL on screen at `video_s`, when the rendered video recorded one fit for a prompt."""
        index = bisect.bisect_right(self._navigation_starts, video_s) - 1
        if index < 0:
            return None
        url = self._navigation[index].url
        return _clip(url) if is_navigable_url(url) else None

    def _contradiction_probabilities(self, citations: Sequence[Citation]) -> dict[int, float] | None:
        if not decision_api.decisions_available_here():
            return None
        state = self._state(citations)
        in_state = {entry["n"] for entry in state["citations"]}
        checked = [c for c in citations if c.n in in_state]
        try:
            result = decision_api.decide_when_available(
                DecisionRequest(
                    team_id=self._team_id,
                    state=state,
                    questions={
                        f"c{c.n}": DecisionQuestion(
                            type=DecisionQuestionType.NOUL, instructions=_FLAG_QUESTION.format(n=c.n)
                        )
                        for c in checked
                    },
                    model=JEV_MODEL,
                    ai_product="replay_vision",
                    trace_id=self._trace_id,
                    # The state is recording-derived, which stays out of the internal AI observability project.
                    privacy_mode=True,
                ),
                timeout_seconds=_JEV_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.warning("replay_vision.citation_review.unavailable", team_id=self._team_id, exc_info=True)
            return None
        probabilities: dict[int, float] = {}
        for c in checked:
            probability = getattr(result.answers.get(f"c{c.n}"), "probability", None)
            if isinstance(probability, float | int):
                probabilities[c.n] = float(probability)
        return probabilities

    def _state(self, citations: Sequence[Citation]) -> dict[str, Any]:
        entries = [
            {
                "n": c.n,
                "claim": c.claim,
                "t": c.video_s,
                "page_on_screen": self.page_at(c.video_s),
                "events_nearby": self._events_near(c.video_s),
            }
            for c in citations
        ]
        while len(entries) > 1 and len(json.dumps(entries, ensure_ascii=False)) > _MAX_STATE_CHARS:
            entries.pop()
        return {"citations": entries}

    def _events_near(self, video_s: int) -> list[dict[str, Any]]:
        nearest = sorted(
            get_events_around(self._events_index, video_s, _EVENTS_WINDOW_S),
            key=lambda event: abs(event["vid_t"] - video_s),
        )[:_MAX_EVENTS_PER_CITATION]
        return [
            {"t": event["vid_t"], **{f: _clip(str(event[f])) for f in _EVENT_FIELDS if event.get(f)}}
            for event in sorted(nearest, key=lambda event: event["vid_t"])
        ]

    def _record(self, outcome: str, count: int) -> None:
        if count > 0:
            record_citation_review(self._scanner_type, self._model, outcome, count)


def citations_in(response: BaseModel, fields: Sequence[str]) -> list[Citation]:
    """Every cited second in `fields`, numbered in reading order, each with the sentence it closes."""
    citations: list[Citation] = []
    for field_name in fields:
        text = getattr(response, field_name, None)
        if not isinstance(text, str):
            continue
        for match in TIMESTAMP_CITATION_RE.finditer(text):
            claim = _sentence_before(text, match.start())
            for raw in re.findall(r"\d+", match.group(1)):
                citations.append(Citation(n=len(citations) + 1, claim=claim, video_s=int(raw)))
    return citations


def replace_citations(response: _ResponseT, fields: Sequence[str], moves: dict[int, int | None]) -> _ResponseT:
    """`response` with each numbered cited second moved to its new second, or removed when that is None."""
    n = 0
    updates: dict[str, str] = {}

    def _rewrite(match: re.Match[str]) -> str:
        nonlocal n
        seconds: list[str] = []
        for raw in re.findall(r"\d+", match.group(1)):
            n += 1
            new = moves[n] if n in moves else int(raw)
            if new is not None:
                seconds.append(str(new))
        if not seconds:
            return ""
        leading = match.group(0)[: len(match.group(0)) - len(match.group(0).lstrip())]
        return leading + " ".join(f"(t {second})" for second in seconds)

    for field_name in fields:
        text = getattr(response, field_name, None)
        if isinstance(text, str):
            updates[field_name] = TIMESTAMP_CITATION_RE.sub(_rewrite, text)
    return response.model_copy(update=updates)


def _sentence_before(text: str, end: int) -> str:
    """The sentence that a citation at `end` closes, without its own citation markers."""
    # A marker placed after the full stop closes the sentence before that stop, so skip boundaries with nothing after.
    starts = [0, *(boundary.end() for boundary in _SENTENCE_END_RE.finditer(text, 0, end))]
    for start in reversed(starts):
        if claim := strip_citation_markers(text[start:end]):
            return claim[-_MAX_CLAIM_CHARS:]
    return ""


def _clip(value: str) -> str:
    return value if len(value) <= _MAX_VALUE_CHARS else value[:_MAX_VALUE_CHARS] + "…"
