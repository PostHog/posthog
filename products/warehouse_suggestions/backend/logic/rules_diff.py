from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any

from posthog.dataclasses import frozen

from ..facade.enums import WarehouseSuggestionKind
from .candidates import CandidateResult
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


def diff_candidates(
    before: Mapping[WarehouseSuggestionKind, CandidateResult],
    after: Mapping[WarehouseSuggestionKind, CandidateResult],
) -> dict[WarehouseSuggestionKind, KindDiff]:
    return {kind: _diff(_ranked_names(before[kind]), _ranked_names(after[kind])) for kind in before}


def _diff(before: list[str], after: list[str]) -> KindDiff:
    kept_before = [name for name in before if name in after]
    kept_after = [name for name in after if name in before]
    return KindDiff(
        added=tuple(name for name in after if name not in before),
        removed=tuple(name for name in before if name not in after),
        reranked=tuple(name for position, name in enumerate(kept_after) if kept_before[position] != name),
    )


def _ranked_names(result: CandidateResult) -> list[str]:
    ranked = sorted(result.drafts, key=lambda draft: draft.score, reverse=True)
    return [draft.payload.subject_name for draft in ranked]


def _parse_like(current: Any, raw_value: str) -> Any:
    if isinstance(current, bool):
        return raw_value.lower() in ("true", "1", "yes")
    if isinstance(current, int):
        return int(raw_value)
    if isinstance(current, float):
        return float(raw_value)
    if isinstance(current, timedelta):
        return timedelta(seconds=float(raw_value))
    raise InvalidRuleOverrideError(f"Only numbers, booleans and durations can be overridden, not {current!r}")
