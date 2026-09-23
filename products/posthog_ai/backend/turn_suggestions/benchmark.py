"""Runs labeled PostHog AI turns through live Jev and scores the policy at a range of show thresholds.

The cases live in ``benchmark_cases.yaml``. Each case lists the offers that would be a good outcome,
so one Jev run per case scores every threshold: the policy is re-applied to the same judgment
instead of asking Jev again.
"""

import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from posthog.dataclasses import frozen

from products.posthog_ai.backend.turn_suggestions.classifier import pick_offer
from products.posthog_ai.backend.turn_suggestions.judgment import TurnJudgment, judge_turn
from products.posthog_ai.backend.turn_suggestions.service import available_offers
from products.posthog_ai.backend.turn_suggestions.transcript import (
    EarlierTurn,
    ErrorIssueRef,
    SavedInsightRef,
    TranscriptToolCall,
    TurnTranscript,
)
from products.posthog_ai.backend.turn_suggestions.verdict import OfferKind

CASES_PATH = Path(__file__).with_name("benchmark_cases.yaml")

DEFAULT_THRESHOLDS: tuple[float, ...] = tuple(round(0.2 + step * 0.05, 2) for step in range(15))


class Expectation(StrEnum):
    OFFER = "offer"
    NOTHING = "nothing"
    EITHER = "either"


class Outcome(StrEnum):
    CORRECT = "correct"
    FALSE_OFFER = "false_offer"
    MISSED = "missed"
    WRONG_KIND = "wrong_kind"
    EITHER = "either"
    FAILED = "failed"


@frozen
class BenchmarkCase:
    name: str
    category: str
    acceptable: frozenset[OfferKind]
    transcript: TurnTranscript
    available: frozenset[OfferKind]

    @property
    def expectation(self) -> Expectation:
        if self.acceptable == {OfferKind.NONE}:
            return Expectation.NOTHING
        return Expectation.EITHER if OfferKind.NONE in self.acceptable else Expectation.OFFER


@frozen
class CaseResult:
    case: BenchmarkCase
    judgment: TurnJudgment | None
    seconds: float

    def picked(self, show_threshold: float) -> OfferKind:
        if self.judgment is None:
            return OfferKind.NONE
        return pick_offer(self.judgment, self.case.available, show_threshold=show_threshold)

    def outcome(self, show_threshold: float) -> Outcome:
        if self.judgment is None:
            return Outcome.FAILED
        expectation = self.case.expectation
        picked = self.picked(show_threshold)
        if expectation == Expectation.EITHER:
            return Outcome.EITHER if picked in self.case.acceptable else Outcome.WRONG_KIND
        if expectation == Expectation.NOTHING:
            return Outcome.CORRECT if picked == OfferKind.NONE else Outcome.FALSE_OFFER
        if picked == OfferKind.NONE:
            return Outcome.MISSED
        return Outcome.CORRECT if picked in self.case.acceptable else Outcome.WRONG_KIND


@frozen
class ThresholdScore:
    threshold: float
    offer_rate: float
    precision: float | None
    recall: float | None
    false_offers: int
    missed: int
    wrong_kind: int

    @property
    def f1(self) -> float | None:
        if self.precision is None or self.recall is None:
            return None
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


def _transcript_from_case(raw: dict[str, Any]) -> TurnTranscript:
    status = raw.get("tool_status", "completed")
    earlier = [
        EarlierTurn(question=turn["question"], tool_names=tuple(turn.get("tools", [])), answer_excerpt=turn["answer"])
        for turn in raw.get("earlier", [])
    ]
    return TurnTranscript(
        human_messages=(*(turn.question for turn in earlier), raw["question"]),
        assistant_text=raw["answer"],
        tool_calls=tuple(
            TranscriptToolCall(name=tool, args_preview="", status=status, from_posthog=True)
            for tool in raw.get("tools", [])
        ),
        earlier_turns=tuple(earlier),
        saved_insights=tuple(
            SavedInsightRef(short_id=ref["short_id"], insight_id=None, name=ref["name"], query_kind=ref["kind"])
            for ref in raw.get("insights", [])
        ),
        error_issues=tuple(ErrorIssueRef(issue_id=ref["id"], name=ref["name"]) for ref in raw.get("issues", [])),
    )


def load_cases(path: Path = CASES_PATH) -> list[BenchmarkCase]:
    cases = []
    for raw in yaml.safe_load(path.read_text()):
        transcript = _transcript_from_case(raw)
        cases.append(
            BenchmarkCase(
                name=raw["name"],
                category=raw["category"],
                acceptable=frozenset(OfferKind(kind) for kind in raw["acceptable"]),
                transcript=transcript,
                available=available_offers(transcript, scouts_available=raw.get("scouts_available", True)),
            )
        )
    return cases


def _judge(case: BenchmarkCase) -> CaseResult:
    started = time.monotonic()
    judgment = judge_turn(case.transcript, available=case.available)
    return CaseResult(case=case, judgment=judgment, seconds=time.monotonic() - started)


def run_cases(
    cases: Sequence[BenchmarkCase], *, workers: int, on_result: Callable[[CaseResult], None]
) -> list[CaseResult]:
    """Judge every case, calling ``on_result`` as each answer arrives so a caller can print it live."""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(_judge, case) for case in cases]):
            result = future.result()
            on_result(result)
            results.append(result)
    return results


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score(results: Iterable[CaseResult], threshold: float) -> ThresholdScore:
    judged = [result for result in results if result.judgment is not None]
    outcomes = [result.outcome(threshold) for result in judged]
    offered = sum(1 for result in judged if result.picked(threshold) != OfferKind.NONE)
    correct_offers = sum(
        1
        for result, outcome in zip(judged, outcomes)
        if outcome == Outcome.CORRECT and result.case.expectation == Expectation.OFFER
    )
    false_offers = outcomes.count(Outcome.FALSE_OFFER)
    wrong_kind = outcomes.count(Outcome.WRONG_KIND)
    expecting_offer = sum(1 for result in judged if result.case.expectation == Expectation.OFFER)
    return ThresholdScore(
        threshold=threshold,
        offer_rate=_ratio(offered, len(judged)) or 0.0,
        precision=_ratio(correct_offers, correct_offers + false_offers + wrong_kind),
        recall=_ratio(correct_offers, expecting_offer),
        false_offers=false_offers,
        missed=outcomes.count(Outcome.MISSED),
        wrong_kind=wrong_kind,
    )


def sweep(results: Sequence[CaseResult], thresholds: Iterable[float] = DEFAULT_THRESHOLDS) -> list[ThresholdScore]:
    return [score(results, threshold) for threshold in thresholds]


def best_threshold(scores: Sequence[ThresholdScore]) -> ThresholdScore | None:
    """The threshold with the best F1. A tie goes to the higher threshold, which interrupts fewer people."""
    ranked = [entry for entry in scores if entry.f1 is not None]
    return max(ranked, key=lambda entry: (entry.f1 or 0.0, entry.threshold)) if ranked else None
