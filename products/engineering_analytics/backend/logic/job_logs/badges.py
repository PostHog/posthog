"""What a GitHub Actions job log says its steps did with caches and migrations.

Pure text parsing. A job log has no step numbers. Each declared step opens with a ``##[group]Run``
line, each cleanup step with ``Post job cleanup.``, and the steps inside a composite action sit
between ``start-action`` and ``end-action``. Counting the openers outside composite actions gives
the step a line belongs to. When that count differs from the steps the job reports, no line is
attributed to a step and the badges are reported for the job as a whole only.
"""

import re
from collections.abc import Sequence

from products.engineering_analytics.backend.facade.contracts import (
    JobLogBadge,
    JobLogBadgeKind,
    JobLogBadgeState,
    JobLogInsights,
    JobStepLogBadges,
    WorkflowJobStep,
)

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TIMESTAMP = re.compile(r"^﻿?\d{4}-\d\d-\d\dT[\d:.]+Z ")
_MAX_DETAILS = 20

_Rule = tuple[JobLogBadgeKind, JobLogBadgeState, re.Pattern[str]]
# Matched at the start of a line. The pattern's group, when it has one, is the badge's detail.
_RULES: tuple[_Rule, ...] = (
    (JobLogBadgeKind.CACHE, JobLogBadgeState.HIT, re.compile(r"Cache hit for: (.+)")),
    (JobLogBadgeKind.CACHE, JobLogBadgeState.PARTIAL, re.compile(r"Cache hit for restore-key: (.+)")),
    (JobLogBadgeKind.CACHE, JobLogBadgeState.MISS, re.compile(r"Cache not found for input keys: (.+)")),
    (JobLogBadgeKind.CACHE, JobLogBadgeState.FAILED, re.compile(r"##\[warning\]Failed to restore: (.+)")),
    (JobLogBadgeKind.MIGRATIONS, JobLogBadgeState.NONE, re.compile(r"\s*No migrations to apply\.")),
    (JobLogBadgeKind.MIGRATIONS, JobLogBadgeState.APPLIED, re.compile(r"\s*Applying (\S+?)\.\.\.")),
)
# A line without one of these cannot match a rule, which spares most lines the regexes. A new rule needs its hint here.
_RULE_HINTS = ("Cache ", "Failed to restore", "igrations to apply", "Applying ")
# The runner adds these around the declared steps, and they do not open with a "Run" group.
_RUNNER_STEPS = ("Set up job", "Complete job")
_POST_PREFIX = "Post "

_Found = dict[tuple[JobLogBadgeKind, JobLogBadgeState], list[str]]


def parse_job_log(log_text: str, steps: Sequence[WorkflowJobStep]) -> JobLogInsights:
    assigner = _StepAssigner(steps)
    whole: _Found = {}
    by_step: dict[int, _Found] = {}
    for raw_line in log_text.splitlines():
        line = _ANSI.sub("", _TIMESTAMP.sub("", raw_line))
        step = assigner.step_of(line)
        if not any(hint in line for hint in _RULE_HINTS):
            continue
        for kind, state, pattern in _RULES:
            if match := pattern.match(line):
                detail = match.group(1) if match.groups() else ""
                whole.setdefault((kind, state), []).append(detail)
                if step is not None:
                    by_step.setdefault(step, {}).setdefault((kind, state), []).append(detail)
                break
    attributed = assigner.matches_job_steps()
    return JobLogInsights(
        log_read=True,
        attributed_to_steps=attributed,
        job=_badges(whole),
        steps=(
            [JobStepLogBadges(number=number, badges=_badges(found)) for number, found in sorted(by_step.items())]
            if attributed
            else []
        ),
    )


class _StepAssigner:
    """Gives each log line, fed in order, the number of the step that wrote it."""

    def __init__(self, steps: Sequence[WorkflowJobStep]) -> None:
        ran = sorted((step for step in steps if step.conclusion != "skipped"), key=lambda step: step.number)
        names = {step.name for step in ran}
        # The runner names a cleanup step "Post " plus the name of the step it cleans up after.
        self._post = [
            step.number
            for step in ran
            if step.name.startswith(_POST_PREFIX) and step.name.removeprefix(_POST_PREFIX) in names
        ]
        self._main = [step.number for step in ran if step.name not in _RUNNER_STEPS and step.number not in self._post]
        self._current = ran[0].number if ran else None
        self._composite_depth = 0
        self._opened = 0
        self._cleaned = 0

    def step_of(self, line: str) -> int | None:
        if line.startswith("##[start-action"):
            self._composite_depth += 1
        elif line.startswith("##[end-action"):
            self._composite_depth -= 1
        elif self._composite_depth == 0 and line.startswith("##[group]Run "):
            self._current = self._main[self._opened] if self._opened < len(self._main) else None
            self._opened += 1
        elif self._composite_depth == 0 and line.startswith("Post job cleanup."):
            self._current = self._post[self._cleaned] if self._cleaned < len(self._post) else None
            self._cleaned += 1
        return self._current

    def matches_job_steps(self) -> bool:
        return self._opened == len(self._main) and self._cleaned == len(self._post)


def _badges(found: _Found) -> list[JobLogBadge]:
    # A restore that fails logs a hit, then the failure, then a miss. Only the failure is worth showing.
    failed = len(found.get((JobLogBadgeKind.CACHE, JobLogBadgeState.FAILED), []))
    badges: list[JobLogBadge] = []
    for (kind, state), details in found.items():
        masked = kind is JobLogBadgeKind.CACHE and state in (JobLogBadgeState.HIT, JobLogBadgeState.MISS)
        count = len(details) - (failed if masked else 0)
        if count > 0:
            badges.append(JobLogBadge(kind=kind, state=state, count=count, detail=details[:_MAX_DETAILS]))
    return badges
