"""Repository permissions for scout contributions. Empty means unrestricted; None denies targets."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from django.db.models import Q

from products.signals.backend.models import SignalReport, SignalScoutConfig, SignalScoutRun
from products.signals.backend.repo_corrections import sanitized_repository


def normalized_pin(repositories: Iterable[str] | None) -> list[str] | None:
    if repositories is None:
        return None
    repositories = list(repositories)
    normalized = [sanitized_repository(entry) for entry in repositories]
    if any(name is None for name in normalized):
        return None
    return [name for name in normalized if name is not None]


def intersect_pins(*pins: Sequence[str] | None) -> list[str] | None:
    restricted: set[str] | None = None
    for pin in pins:
        if pin is None:
            return None
        if pin:
            restricted = set(pin) if restricted is None else restricted.intersection(pin)
    if restricted is None:
        return []
    return sorted(restricted) or None


def repository_within_pin(repository: str | None, pinned: Sequence[str] | None) -> bool:
    if repository is None:
        return True
    if pinned is None:
        return False
    return not pinned or sanitized_repository(repository) in pinned


def repositories_within_pin(repositories: Iterable[str], pinned: Sequence[str] | None) -> list[str]:
    return [name for name in repositories if repository_within_pin(name, pinned)]


def run_pinned_repositories(run: SignalScoutRun) -> list[str] | None:
    metadata = run.metadata or {}
    if "repository_scope" in metadata:
        return normalized_pin(metadata["repository_scope"])
    if "repositories" in metadata:
        return normalized_pin(metadata["repositories"])
    if run.scout_config is not None:
        return normalized_pin(run.scout_config.repositories)
    return None


def report_pinned_repositories(*, team_id: int, report_id: str, lock: bool = False) -> list[str] | None:
    """Keep every contributing run's restriction, even if its configuration is deleted."""
    key = (
        SignalReport.objects.filter(team_id=team_id, id=report_id)
        .values_list("scout_idempotency_key", flat=True)
        .first()
    )
    contributors = Q(emitted_report_ids__contains=[report_id]) | Q(edited_report_ids__contains=[report_id])
    author_id = None
    if key:
        try:
            author_id = uuid.UUID(key.split(":", 1)[0])
        except ValueError:
            return None
        contributors |= Q(id=author_id)
    runs = list(SignalScoutRun.objects.for_team(team_id).filter(contributors).select_related("scout_config"))
    if author_id is not None and not any(run.id == author_id for run in runs):
        return None
    configs = (
        SignalScoutConfig.objects.for_team(team_id)
        .filter(id__in=[run.scout_config_id for run in runs if run.scout_config_id is not None])
        .order_by("id")
    )
    if lock:
        configs = configs.select_for_update()
    current = {config.id: normalized_pin(config.repositories) for config in configs}
    pins = []
    for run in runs:
        pins.append(run_pinned_repositories(run))
        if run.scout_config_id in current:
            pins.append(current[run.scout_config_id])
    return intersect_pins(*pins)
