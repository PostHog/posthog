import re
import statistics
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any

from posthog.dataclasses import frozen

MIN_PEOPLE = 100
MIN_CHANGE = 0.2
MIN_DROP = 0.3
MIN_SURVEY_ANSWERS = 10
SURVEY_MULTIPLE = 2.0
UI_TRACKING = re.compile(
    r"(shown|dismissed|opened|closed|copied|toggled|loaded|selected|requested|clicked|viewed|timing|performance|changed|_called|connecting|stopped)$",
    re.I,
)
PROBLEM_WORDS = re.compile(r"error|timeout|404|fail|crash|denied", re.I)
NUMBERED_PATH = re.compile(r"/\d+")

SCOPES = {
    "error": ("error_tracking:read",),
    "survey answer": ("survey:read",),
    "key metric": ("query:read",),
    "user action": ("query:read",),
    "visitors": ("query:read",),
}


@frozen
class Candidate:
    id: str
    source: str
    key: str
    name: str
    today: float
    baseline: float
    change: str
    unit: str
    context: dict[str, str]


def _candidate(
    source: str,
    key: str,
    name: str,
    today: float,
    baseline: float,
    change: str,
    unit: str,
    context: dict[str, str] | None = None,
) -> Candidate:
    return Candidate(
        id="",
        source=source,
        key=key,
        name=name,
        today=today,
        baseline=baseline,
        change=change,
        unit=unit,
        context=context or {},
    )


def windows(row: Sequence[Any], first: int) -> tuple[float, float]:
    counts = [float(value or 0) for value in row[first : first + 5]]
    return counts[0], float(round(statistics.median(counts[1:])))


def describe_change(today: float, baseline: float) -> str | None:
    if baseline <= max(2, today * 0.01):
        return "new" if today >= MIN_PEOPLE else None
    ratio = (today - baseline) / baseline
    if ratio >= MIN_CHANGE or ratio <= -MIN_DROP:
        return f"{ratio:+.0%}"
    return None


def change_percent(change: str) -> float | None:
    return float(change.rstrip("%")) if change.endswith("%") else None


def from_actions(rows: Sequence[Sequence[Any]]) -> Iterator[Candidate]:
    for row in rows:
        name = str(row[0])
        today, baseline = windows(row, 1)
        if max(today, baseline) < MIN_PEOPLE or (UI_TRACKING.search(name) and not PROBLEM_WORDS.search(name)):
            continue
        change = describe_change(today, baseline)
        if change and (change != "new" or PROBLEM_WORDS.search(name)):
            yield _candidate("user action", name, name, today, baseline, change, "people")


def from_errors(rows: Sequence[Sequence[Any]]) -> Iterator[Candidate]:
    for row in rows:
        issue_id, error_type, message, page, host = (str(value or "") for value in row[:5])
        today, baseline = windows(row, 5)
        change = describe_change(today, baseline) if today >= MIN_PEOPLE else None
        if change:
            context = {
                "error type": error_type,
                "message": message,
                "page": NUMBERED_PATH.sub("/<id>", page),
                "host": host,
            }
            yield _candidate("error", issue_id, issue_id[:8], today, baseline, change, "people", context)


def from_surveys(rows: Sequence[Sequence[Any]]) -> Iterator[Candidate]:
    for row in rows:
        survey_id, survey_name, answer = str(row[0]), str(row[1] or "Unnamed survey"), str(row[2])
        today, baseline = windows(row, 3)
        if today < MIN_SURVEY_ANSWERS or (baseline and today / baseline < SURVEY_MULTIPLE):
            continue
        change = f"{today / baseline:.1f} times" if baseline else "new"
        yield _candidate(
            "survey answer", f"{survey_id}|{answer}", f"{survey_name}: {answer}", today, baseline, change, "answers"
        )


def from_key_events(rows: Sequence[Sequence[Any]]) -> Iterator[Candidate]:
    for row in rows:
        name = str(row[0])
        today, baseline = windows(row, 1)
        change = describe_change(today, baseline) if max(today, baseline) >= MIN_PEOPLE else None
        if change:
            yield _candidate("key metric", name, name, today, baseline, change, "events")


def from_traffic(rows: Sequence[Sequence[Any]]) -> Iterator[Candidate]:
    for row in rows:
        host = str(row[0])
        today, baseline = windows(row, 1)
        change = describe_change(today, baseline) if today >= MIN_PEOPLE else None
        if change:
            yield _candidate("visitors", host, host or "(no host)", today, baseline, change, "people")


def number(candidates: Sequence[Candidate]) -> list[Candidate]:
    return [replace(candidate, id=f"c{index}") for index, candidate in enumerate(candidates, start=1)]
