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


def terms(*texts: str) -> set[str]:
    found: set[str] = set()
    for text in texts:
        for term in TERM.findall(CAMEL_BOUNDARY.sub(r"\1 \2", text or "").lower()):
            if len(term) >= 3 and not term.isdigit() and term not in GENERIC_TERMS:
                found.add(term)
    return found


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
