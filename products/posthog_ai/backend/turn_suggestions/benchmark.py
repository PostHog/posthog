"""Runs labeled PostHog AI turns through live Jev and scores the policy at a range of show thresholds.

The cases live in ``benchmark_cases.yaml``. Each case lists the offers that would be a good outcome,
so one Jev run per case scores every threshold: the policy is re-applied to the same judgment
instead of asking Jev again.
"""

import re
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import yaml
import requests

from posthog.dataclasses import frozen
from posthog.llm.system_one import SystemOneRequestFailed, build_system_one_body, parse_system_one_response

from products.posthog_ai.backend.turn_suggestions.classifier import pick_offer
from products.posthog_ai.backend.turn_suggestions.judgment import (
    TurnJudgment,
    build_judge_questions,
    build_judge_state,
    judge_turn,
    read_judgment,
)
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
# Fine enough that a small case file can land within a case or two of a target offer rate.
FINE_THRESHOLDS: tuple[float, ...] = tuple(round(step * 0.01, 2) for step in range(1, 100))

# A candidate server can answer slower than TypeSafe. The benchmark prints the seconds per case, so a
# slow answer shows up there instead of as a failure.
ENDPOINT_TIMEOUT: tuple[float, float] = (5.0, 60.0)


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

    @property
    def want_label(self) -> str:
        return "nothing" if self.expectation == Expectation.NOTHING else "|".join(sorted(self.acceptable))


@frozen
class SystemOneEndpoint:
    """A server other than TypeSafe that serves the System One API. ``model`` is sent only when set,
    because a candidate server can reject TypeSafe's model ids. Basic auth is sent only when
    ``username`` is set."""

    url: str
    model: str | None = None
    username: str | None = None
    password: str = field(default="", repr=False)

    @property
    def label(self) -> str:
        return f"{urlsplit(self.url).netloc} {self.model or 'default'}"


SYSTEM_ONE_PATH = "/v1/systemone"

# A URL never holds a space, a comma, or a semicolon, so any of them can separate the entries.
_ENTRY_SEPARATORS = re.compile(r"[\s,;]+")


def parse_endpoint(entry: str, position: int = 1) -> SystemOneEndpoint:
    """Reads ``http[s]://[username:password@]host[:port][/path][#model]``. The path defaults to
    ``/v1/systemone``. The fragment names the model, and a URL fragment never reaches the server.
    Percent-encode a ``:``, ``@``, or ``#`` inside the username or password."""
    parts = urlsplit(entry)
    # The entry can hold a password, so the errors name its position, never its text.
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"Endpoint {position} is not an http:// or https:// URL")
    try:
        port = parts.port
    except ValueError:
        raise ValueError(f"Endpoint {position} has an invalid port") from None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    netloc = f"{host}:{port}" if port else host
    path = parts.path if parts.path not in {"", "/"} else SYSTEM_ONE_PATH
    return SystemOneEndpoint(
        url=urlunsplit((parts.scheme, netloc, path, parts.query, "")),
        model=unquote(parts.fragment) or None,
        username=unquote(parts.username) if parts.username else None,
        password=unquote(parts.password or ""),
    )


def parse_endpoints(value: str) -> list[SystemOneEndpoint]:
    entries = [entry for entry in _ENTRY_SEPARATORS.split(value) if entry]
    return [parse_endpoint(entry, position) for position, entry in enumerate(entries, start=1)]


@frozen
class CaseResult:
    case: BenchmarkCase
    judgment: TurnJudgment | None
    seconds: float
    error: str | None = None

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
            TranscriptToolCall(name=tool, args_preview="", status=status) for tool in raw.get("tools", [])
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


def _judge_at_endpoint(case: BenchmarkCase, endpoint: SystemOneEndpoint) -> TurnJudgment:
    questions = build_judge_questions(case.transcript, case.available)
    body = build_system_one_body(state=build_judge_state(case.transcript), questions=questions, model=endpoint.model)
    # The candidate server is not TypeSafe, so this call stays out of the TypeSafe egress budget and metrics.
    response = requests.post(
        endpoint.url,
        json=body,
        auth=(endpoint.username, endpoint.password) if endpoint.username else None,
        timeout=ENDPOINT_TIMEOUT,
        allow_redirects=False,
    )
    response.raise_for_status()
    return read_judgment(parse_system_one_response(response.json(), questions), case.transcript, case.available)


def _judge(case: BenchmarkCase, endpoint: SystemOneEndpoint | None) -> CaseResult:
    started = time.monotonic()
    judgment: TurnJudgment | None = None
    failure: str | None = None
    if endpoint is None:
        judgment = judge_turn(case.transcript, available=case.available)
    else:
        try:
            judgment = _judge_at_endpoint(case, endpoint)
        except requests.HTTPError as error:
            response = error.response
            # The start of the body usually names the rejected field, which is what a 400 needs to be fixed.
            failure = f"HTTP {response.status_code}: {response.text[:200]}" if response is not None else "HTTP error"
        except requests.RequestException as error:
            failure = type(error).__name__
        except SystemOneRequestFailed as error:
            # A malformed answer, such as a choice outside the options, fails only this case.
            failure = f"malformed answer: {error}"
    return CaseResult(case=case, judgment=judgment, seconds=time.monotonic() - started, error=failure)


def run_cases(
    cases: Sequence[BenchmarkCase],
    *,
    workers: int,
    on_result: Callable[[CaseResult], None],
    endpoint: SystemOneEndpoint | None = None,
) -> list[CaseResult]:
    """Judge every case, calling ``on_result`` as each answer arrives so a caller can print it live.
    ``endpoint`` sends the judgments to that server instead of TypeSafe. The results come back in
    the order of ``cases``."""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(_judge, case, endpoint) for case in cases]):
            result = future.result()
            on_result(result)
            results.append(result)
    order = {case.name: index for index, case in enumerate(cases)}
    return sorted(results, key=lambda result: order[result.case.name])


@frozen
class JudgeRun:
    """Every case's result from one judge: Jev through TypeSafe, or one candidate endpoint."""

    label: str
    results: tuple[CaseResult, ...]

    def by_case(self) -> dict[str, CaseResult]:
        return {result.case.name: result for result in self.results}


def agreement(run: JudgeRun, run_threshold: float, reference: JudgeRun, reference_threshold: float) -> float | None:
    """The share of cases both judges answered where they pick the same offer, each at its own threshold."""
    reference_results = reference.by_case()
    pairs = [
        (result, reference_results[result.case.name])
        for result in run.results
        if result.judgment is not None
        and result.case.name in reference_results
        and reference_results[result.case.name].judgment is not None
    ]
    same = sum(1 for result, other in pairs if result.picked(run_threshold) == other.picked(reference_threshold))
    return _ratio(same, len(pairs))


def disagreements(runs: Sequence[JudgeRun], thresholds: Sequence[float]) -> list[tuple[CaseResult, ...]]:
    """The cases where the judges that answered pick different offers, each judge at its threshold in
    ``thresholds``, in case file order. A failed request alone does not make a disagreement, because
    the failure counts show those."""
    per_run = [run.by_case() for run in runs]
    rows = []
    for name in (result.case.name for result in runs[0].results):
        row = tuple(results[name] for results in per_run if name in results)
        if len(row) != len(runs):
            continue
        picks = {result.picked(threshold) for result, threshold in zip(row, thresholds) if result.judgment is not None}
        if len(picks) > 1:
            rows.append(row)
    return rows


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


def closest_to_offer_rate(results: Sequence[CaseResult], target: float) -> ThresholdScore | None:
    """The fine-grained threshold whose offer rate lands nearest ``target``. A tie goes to the higher
    threshold, which interrupts fewer people. ``None`` when no case was judged."""
    if not any(result.judgment is not None for result in results):
        return None
    return min(sweep(results, FINE_THRESHOLDS), key=lambda entry: (abs(entry.offer_rate - target), -entry.threshold))
