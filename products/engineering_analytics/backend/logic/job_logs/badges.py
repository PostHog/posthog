"""What a GitHub Actions job log says its steps did with caches and migrations.

Pure text parsing. A job log has no step numbers. Each declared step opens with a ``##[group]Run``
line, each cleanup step with ``Post job cleanup.``, and the steps inside a composite action sit
between ``start-action`` and ``end-action``. Counting the openers outside composite actions gives
the step a line belongs to. When that count differs from the steps the job reports, no line is
attributed to a step and the badges are reported for the job as a whole only.
"""

import io
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
_MAX_DETAIL_CHARS = 300

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

_BadgeKey = tuple[JobLogBadgeKind, JobLogBadgeState]
_HIT: _BadgeKey = (JobLogBadgeKind.CACHE, JobLogBadgeState.HIT)
_MISS: _BadgeKey = (JobLogBadgeKind.CACHE, JobLogBadgeState.MISS)
_FAILED: _BadgeKey = (JobLogBadgeKind.CACHE, JobLogBadgeState.FAILED)


class _Found:
    """The matches of one job or one step. The pull request's author writes the log, so what is kept
    of it is bounded while it is read: every match is counted, and only the first few details are held.

    A restore that fails logs a hit, then the failure, then a miss. Only the failure is worth showing,
    so the failure removes the hit logged just before it and drops the miss logged just after it. The
    hits and misses of other restores stay."""

    def __init__(self) -> None:
        self.counts: dict[_BadgeKey, int] = {}
        self.details: dict[_BadgeKey, list[str]] = {}
        # Set while the last cache line was a hit. The value says whether the hit's detail was kept.
        self._last_hit_detail_kept: bool | None = None
        self._miss_belongs_to_failure = False

    def add(self, key: _BadgeKey, detail: str) -> None:
        if key[0] is JobLogBadgeKind.CACHE:
            if key == _FAILED:
                self._remove_last_hit()
                self._miss_belongs_to_failure = True
            elif key == _MISS and self._miss_belongs_to_failure:
                self._miss_belongs_to_failure = False
                return
            else:
                self._miss_belongs_to_failure = False
        self.counts[key] = self.counts.get(key, 0) + 1
        details = self.details.setdefault(key, [])
        detail_kept = len(details) < _MAX_DETAILS
        if detail_kept:
            details.append(detail[:_MAX_DETAIL_CHARS])
        if key[0] is JobLogBadgeKind.CACHE:
            self._last_hit_detail_kept = detail_kept if key == _HIT else None

    def _remove_last_hit(self) -> None:
        if self._last_hit_detail_kept is None:
            return
        if self._last_hit_detail_kept:
            self.details[_HIT].pop()
        self.counts[_HIT] -= 1
        if not self.counts[_HIT]:
            del self.counts[_HIT]
            del self.details[_HIT]


def parse_job_log(log_text: str, steps: Sequence[WorkflowJobStep]) -> JobLogInsights:
    assigner = _StepAssigner(steps)
    whole = _Found()
    by_step: dict[int, _Found] = {}
    # StringIO yields one line at a time, where splitlines would hold a second copy of the whole log.
    for raw_line in io.StringIO(log_text):
        line = _ANSI.sub("", _TIMESTAMP.sub("", raw_line.rstrip("\r\n")))
        step = assigner.step_of(line)
        if not any(hint in line for hint in _RULE_HINTS):
            continue
        for kind, state, pattern in _RULES:
            if match := pattern.match(line):
                detail = match.group(1) if match.groups() else ""
                whole.add((kind, state), detail)
                if step is not None:
                    by_step.setdefault(step, _Found()).add((kind, state), detail)
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
    return [
        JobLogBadge(kind=kind, state=state, count=count, detail=found.details[(kind, state)])
        for (kind, state), count in found.counts.items()
    ]
