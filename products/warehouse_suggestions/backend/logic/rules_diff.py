from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any

from posthog.dataclasses import frozen

from ..facade.enums import WarehouseSuggestionKind
from .candidates.base import CandidateContext, CandidateResult
from .job import is_eligible
from .rules import Rules


class InvalidRuleOverrideError(ValueError):
    pass


@frozen
class KindDiff:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    reranked: tuple[str, ...]


def override_rules(rules: Rules, assignments: Sequence[str]) -> Rules:
    for assignment in assignments:
        path, separator, raw_value = assignment.partition("=")
        section_name, _, field_name = path.partition(".")
        if not separator or not field_name or not hasattr(rules, section_name):
            raise InvalidRuleOverrideError(f"Expected section.field=value, got {assignment!r}")
        section = getattr(rules, section_name)
        if not hasattr(section, field_name):
            raise InvalidRuleOverrideError(f"{section_name} has no rule named {field_name!r}")
        value = _parse_like(getattr(section, field_name), raw_value)
        rules = replace(rules, **{section_name: replace(section, **{field_name: value})})
    return rules


def results_the_job_would_keep(
    context: CandidateContext, results: Mapping[WarehouseSuggestionKind, CandidateResult]
) -> dict[WarehouseSuggestionKind, CandidateResult]:
    if is_eligible(context.reads, context.rules.eligibility):
        return dict(results)
    return {kind: CandidateResult(drafts=(), rejections=()) for kind in results}


def diff_candidates(
    before: Mapping[WarehouseSuggestionKind, CandidateResult],
    after: Mapping[WarehouseSuggestionKind, CandidateResult],
) -> dict[WarehouseSuggestionKind, KindDiff]:
    return {kind: _diff(before[kind], after[kind]) for kind in before}


def _diff(before: CandidateResult, after: CandidateResult) -> KindDiff:
    before_ranked, after_ranked = _ranked(before), _ranked(after)
    names = {draft.fingerprint: draft.payload.subject_name for draft in (*before.drafts, *after.drafts)}
    kept_before = [fingerprint for fingerprint in before_ranked if fingerprint in after_ranked]
    kept_after = [fingerprint for fingerprint in after_ranked if fingerprint in before_ranked]
    return KindDiff(
        added=tuple(names[fingerprint] for fingerprint in after_ranked if fingerprint not in before_ranked),
        removed=tuple(names[fingerprint] for fingerprint in before_ranked if fingerprint not in after_ranked),
        reranked=tuple(
            names[fingerprint]
            for position, fingerprint in enumerate(kept_after)
            if kept_before[position] != fingerprint
        ),
    )


def _ranked(result: CandidateResult) -> list[str]:
    return [draft.fingerprint for draft in sorted(result.drafts, key=lambda draft: draft.score, reverse=True)]


def _parse_like(current: Any, raw_value: str) -> Any:
    if isinstance(current, bool):
        return raw_value.lower() in ("true", "1", "yes")
    if isinstance(current, int):
        return int(raw_value)
    if isinstance(current, float):
        return float(raw_value)
    if isinstance(current, timedelta):
        return timedelta(seconds=float(raw_value))
    if isinstance(current, tuple) and current:
        return _parse_items(type(current[0]), raw_value)
    raise InvalidRuleOverrideError(
        f"Only numbers, booleans, durations and ordered lists can be overridden, not {current!r}"
    )


def _parse_items(item_type: type, raw_value: str) -> tuple[Any, ...]:
    try:
        return tuple(item_type(item.strip()) for item in raw_value.split(","))
    except ValueError as error:
        raise InvalidRuleOverrideError(str(error)) from error
