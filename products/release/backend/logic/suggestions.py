"""Find the releases a feature flag is in, and the releases it probably belongs to."""

from __future__ import annotations

import re

from django.db.models import Q

from ..models import Release

TERM = re.compile(r"[a-z0-9]+")
CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
GENERIC_TERMS = frozenset(
    {
        "and",
        "beta",
        "disable",
        "disabled",
        "enable",
        "enabled",
        "experiment",
        "feature",
        "features",
        "flag",
        "flags",
        "for",
        "new",
        "release",
        "rollout",
        "test",
        "the",
        "with",
    }
)
SUMMARY_FIELDS = ("id", "name", "description", "auto_named", "feature_flag_ids", "created_at")
MAX_TEXT_LENGTH = 500
MAX_SEARCH_TERMS = 12


def _ordered_terms(texts: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for text in texts:
        for term in TERM.findall(CAMEL_BOUNDARY.sub(r"\1 \2", (text or "")[:MAX_TEXT_LENGTH]).lower()):
            if len(term) >= 3 and not term.isdigit() and term not in GENERIC_TERMS and term not in found:
                found.append(term)
    return found


def terms(*texts: str) -> set[str]:
    return set(_ordered_terms(texts))


def search_terms(*texts: str) -> set[str]:
    return set(_ordered_terms(texts)[:MAX_SEARCH_TERMS])


def rank(
    candidates: list[Release], words: set[str], linked_terms: dict[int, set[str]]
) -> list[tuple[Release, list[str]]]:
    scored: list[tuple[int, Release, list[str]]] = []
    for release in candidates:
        own = terms(release.name, release.description) & words
        via_flags: set[str] = set()
        for linked_id in release.feature_flag_ids:
            via_flags |= linked_terms.get(linked_id, set()) & words
        matched = own | via_flags
        if matched:
            scored.append((2 * len(own) + len(via_flags - own), release, sorted(matched)))
    scored.sort(key=lambda entry: -entry[0])
    return [(release, matched) for _, release, matched in scored]


def releases_with_flag(team_id: int, flag_id: int) -> list[Release]:
    return list(
        Release.objects.filter(team_id=team_id, feature_flag_ids__contains=[flag_id])
        .only(*SUMMARY_FIELDS)
        .order_by("-created_at", "-id")
    )


def candidate_releases(team_id: int, flag_id: int, words: set[str], flag_ids: list[int], limit: int) -> list[Release]:
    query = Q()
    for word in sorted(words):
        query |= Q(name__icontains=word) | Q(description__icontains=word)
    if flag_ids:
        query |= Q(feature_flag_ids__overlap=flag_ids)
    return list(
        Release.objects.filter(team_id=team_id)
        .exclude(feature_flag_ids__contains=[flag_id])
        .filter(query)
        .only(*SUMMARY_FIELDS)
        .order_by("-created_at", "-id")[:limit]
    )
