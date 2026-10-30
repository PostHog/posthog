"""Turn the model's answer into a complete ranked list, or say why it cannot.

Pure functions over refs (`c1` to `cN`), so every rule is testable without a database or a model call.
The result always covers every candidate: what the model ranks comes first, in rank order, and the
candidates it did not rank follow in model order.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.signals.backend.personal_ranking.candidates import NeedsYouKind
from products.signals.backend.personal_ranking.config import ReasonLimits
from products.signals.backend.personal_ranking.prompt import NEEDS_YOU_KINDS, TIERS, Tier

RankedBy = Literal["llm", "model"]


class MalformedRankingError(ValueError):
    pass


@frozen
class Matched:
    theme: str | None
    needs_you: tuple[NeedsYouKind, ...]


@frozen
class RankedEntry:
    ref: str
    rank: int
    tier: Tier
    reason: str
    next_step: str | None
    matched: Matched | None
    ranked_by: RankedBy


@frozen
class FoldedEntry:
    ref: str
    into: str
    reason: str


@frozen
class ValidationCounts:
    # Entries whose rank changed to close a gap or break a tie.
    renumbered: int = 0
    # Repeat entries of one ref. The one with the lowest (rank, position) stays.
    duplicate_refs: int = 0
    unknown_refs: int = 0
    # Candidates the model neither ranked nor folded. They follow in model order.
    missing_refs: int = 0
    tier_corrections: int = 0
    # Folds of an unknown ref, into an unknown or folded ref, or into the ref itself.
    invalid_folds: int = 0


@frozen
class ValidatedRanking:
    entries: tuple[RankedEntry, ...]
    folded: tuple[FoldedEntry, ...]
    counts: ValidationCounts


@frozen
class _RawEntry:
    ref: str
    rank: int
    position: int
    tier: Tier
    reason: str
    next_step: str | None
    matched: Matched | None


def cap(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + "…"


def _reason_limit(tier: Tier, limits: ReasonLimits) -> int:
    return {"top": limits.top, "worth_a_look": limits.worth_a_look, "later": limits.later}[tier]


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise MalformedRankingError(f"{field} is not a string")
    return value


def _optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = _string(value, field).strip()
    return text or None


def _matched(value: Any) -> Matched | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("needs_you"), list):
        raise MalformedRankingError("matched has the wrong shape")
    kinds = tuple(dict.fromkeys(kind for kind in value["needs_you"] if kind in NEEDS_YOU_KINDS))
    return Matched(theme=_optional_string(value.get("theme"), "matched.theme"), needs_you=kinds)


def _raw_entry(item: Any, position: int) -> _RawEntry:
    if not isinstance(item, dict):
        raise MalformedRankingError("a ranked entry is not an object")
    rank = item.get("rank")
    # `bool` is an `int` subclass, and `true` is not a rank.
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise MalformedRankingError("rank is not an integer")
    tier = item.get("tier")
    if tier not in TIERS:
        raise MalformedRankingError("tier is not one of the tiers")
    return _RawEntry(
        ref=_string(item.get("ref"), "ref"),
        rank=rank,
        position=position,
        tier=tier,
        reason=_string(item.get("reason"), "reason"),
        next_step=_optional_string(item.get("next_step"), "next_step"),
        matched=_matched(item.get("matched")),
    )


def _parse(content: str | None) -> tuple[list[_RawEntry], list[Any]]:
    if not content:
        raise MalformedRankingError("empty response")
    try:
        answer = json.loads(content)
    except json.JSONDecodeError as error:
        raise MalformedRankingError("response is not JSON") from error
    if not isinstance(answer, dict) or not isinstance(answer.get("ranked"), list):
        raise MalformedRankingError("response has no ranked list")
    folded = answer.get("folded", [])
    if not isinstance(folded, list):
        raise MalformedRankingError("folded is not a list")
    return [_raw_entry(item, position) for position, item in enumerate(answer["ranked"])], folded


def _folds(items: list[Any], known: set[str], limits: ReasonLimits) -> tuple[dict[str, FoldedEntry], int]:
    proposed: dict[str, FoldedEntry] = {}
    invalid = 0
    for item in items:
        if not isinstance(item, dict):
            raise MalformedRankingError("a folded entry is not an object")
        ref, into = _string(item.get("ref"), "folded.ref"), _string(item.get("into"), "folded.into")
        if ref not in known or into not in known or ref == into or ref in proposed:
            invalid += 1
            continue
        proposed[ref] = FoldedEntry(
            ref=ref, into=into, reason=cap(_string(item.get("reason"), "folded.reason"), limits.worth_a_look)
        )
    # A fold into a folded ref has no ranked entry to point at.
    valid = {ref: fold for ref, fold in proposed.items() if fold.into not in proposed}
    return valid, invalid + len(proposed) - len(valid)


def model_order(refs: Sequence[str], model_reasons: Mapping[str, str], limit: int) -> tuple[RankedEntry, ...]:
    """The fallback list: every candidate in model order, the first `limit` as worth a look."""
    return tuple(
        RankedEntry(
            ref=ref,
            rank=rank,
            tier="worth_a_look" if rank <= limit else "later",
            reason=model_reasons[ref],
            next_step=None,
            matched=None,
            ranked_by="model",
        )
        for rank, ref in enumerate(refs, start=1)
    )


def validate_ranking(
    content: str | None,
    *,
    refs: Sequence[str],
    model_reasons: Mapping[str, str],
    limit: int,
    reason_limits: ReasonLimits,
    next_step_max_chars: int,
) -> ValidatedRanking:
    """`refs` are the candidates in model order. Raises `MalformedRankingError` when the answer cannot be used at all."""
    raw, folded_items = _parse(content)
    known = set(refs)
    folds, invalid_folds = _folds(folded_items, known, reason_limits)

    unknown = sum(1 for entry in raw if entry.ref not in known)
    ordered = sorted(
        (entry for entry in raw if entry.ref in known and entry.ref not in folds),
        key=lambda entry: (entry.rank, entry.position),
    )
    seen: set[str] = set()
    kept: list[_RawEntry] = []
    for entry in ordered:
        if entry.ref not in seen:
            seen.add(entry.ref)
            kept.append(entry)
    if refs and not kept:
        raise MalformedRankingError("no known ref is ranked")

    entries: list[RankedEntry] = []
    renumbered = tier_corrections = 0
    worst_tier = 0
    for rank, entry in enumerate(kept, start=1):
        renumbered += entry.rank != rank
        tier_index = max(TIERS.index(entry.tier), worst_tier)
        tier_corrections += tier_index != TIERS.index(entry.tier)
        worst_tier = tier_index
        tier = TIERS[tier_index]
        reason = entry.reason.strip() or model_reasons[entry.ref]
        entries.append(
            RankedEntry(
                ref=entry.ref,
                rank=rank,
                tier=tier,
                reason=cap(reason, _reason_limit(tier, reason_limits)),
                next_step=cap(entry.next_step, next_step_max_chars) if entry.next_step and rank <= limit else None,
                matched=entry.matched,
                ranked_by="llm",
            )
        )

    missing = [ref for ref in refs if ref not in seen and ref not in folds]
    for ref in missing:
        entries.append(
            RankedEntry(
                ref=ref,
                rank=len(entries) + 1,
                tier="later",
                reason=model_reasons[ref],
                next_step=None,
                matched=None,
                ranked_by="model",
            )
        )
    return ValidatedRanking(
        entries=tuple(entries),
        folded=tuple(folds[ref] for ref in refs if ref in folds),
        counts=ValidationCounts(
            renumbered=renumbered,
            duplicate_refs=len(ordered) - len(kept),
            unknown_refs=unknown,
            missing_refs=len(missing),
            tier_corrections=tier_corrections,
            invalid_folds=invalid_folds,
        ),
    )
