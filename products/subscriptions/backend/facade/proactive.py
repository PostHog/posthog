"""Narrow persistence boundary for subscription-triggered recommendations."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.subscriptions.backend.facade.api import start_recommendation_generation
from products.subscriptions.backend.facade.contracts import (
    Recommendation,
    RecommendationCitation,
    RecommendationGenerationHandle,
    RecommendationGenerationInput,
    RecommendationResult,
    RecommendationStatus,
)
from products.subscriptions.backend.models import (
    ProactiveRecommendation,
    ProactiveRecommendationRun,
    ProactiveSubscriptionConfig,
)
from products.tasks.backend.facade.repository_authorization import (
    list_authorizable_repositories,
    resolve_staged_repository_binding,
)
from products.tasks.backend.facade.staged_execution import StagedRepositoryBinding

MAX_MEMORY_ROWS = 20
MAX_MEMORY_BYTES = 12_000


@frozen
class ProactiveConfigDTO:
    enabled: bool
    allow_public_web_research: bool
    create_draft_pr: bool
    repository: str | None
    repository_integration_id: int | None


@frozen
class RecommendationMemoryDTO:
    semantic_key: str
    title: str
    created_at: str


@frozen
class RecommendationAppendixDTO:
    status: RecommendationStatus
    recommendations: tuple[Recommendation, ...]
    citations: tuple[RecommendationCitation, ...]
    failure_code: str | None = None


@frozen
class RecommendationRunDTO:
    id: UUID
    status: RecommendationStatus


def get_proactive_config(*, team_id: int, subscription_id: int) -> ProactiveConfigDTO:
    config = ProactiveSubscriptionConfig.objects.for_team(team_id).filter(subscription_id=subscription_id).first()
    return ProactiveConfigDTO(
        enabled=config.enabled if config else False,
        allow_public_web_research=config.allow_public_web_research if config else True,
        create_draft_pr=config.create_draft_pr if config else False,
        repository=config.repository if config else None,
        repository_integration_id=config.repository_integration_id if config else None,
    )


def update_proactive_config(
    *,
    team_id: int,
    subscription_id: int,
    enabled: bool,
    allow_public_web_research: bool,
    create_draft_pr: bool = False,
    repository: str | None = None,
    repository_integration_id: int | None = None,
) -> ProactiveConfigDTO:
    if not create_draft_pr and (repository is not None or repository_integration_id is not None):
        raise ValueError("repository settings require draft PR preparation")
    with transaction.atomic():
        config, _ = (
            ProactiveSubscriptionConfig.objects.for_team(team_id)
            .select_for_update()
            .get_or_create(
                subscription_id=subscription_id,
                defaults={
                    "team_id": team_id,
                    "enabled": enabled,
                    "allow_public_web_research": allow_public_web_research,
                    "create_draft_pr": create_draft_pr,
                    "repository": repository,
                    "repository_integration_id": repository_integration_id,
                },
            )
        )
        if (
            config.enabled != enabled
            or config.allow_public_web_research != allow_public_web_research
            or config.create_draft_pr != create_draft_pr
            or config.repository != repository
            or config.repository_integration_id != repository_integration_id
        ):
            config.enabled = enabled
            config.allow_public_web_research = allow_public_web_research
            config.create_draft_pr = create_draft_pr
            config.repository = repository
            config.repository_integration_id = repository_integration_id
            config.save(
                update_fields=[
                    "enabled",
                    "allow_public_web_research",
                    "create_draft_pr",
                    "repository",
                    "repository_integration_id",
                    "updated_at",
                ]
            )
    return ProactiveConfigDTO(
        enabled=config.enabled,
        allow_public_web_research=config.allow_public_web_research,
        create_draft_pr=config.create_draft_pr,
        repository=config.repository,
        repository_integration_id=config.repository_integration_id,
    )


def resolve_draft_repository_binding(
    *, team_id: int, actor_id: int, config: ProactiveConfigDTO
) -> StagedRepositoryBinding | None:
    """Freeze the actor's currently authorized repository consent for one analysis run."""
    if not config.create_draft_pr or config.repository is None:
        return None
    repositories = list_authorizable_repositories(team_id=team_id, actor_id=actor_id)
    if not any(
        _repository_identity(repository.repository) == _repository_identity(config.repository)
        and (
            config.repository_integration_id is None
            or repository.github_integration_id == config.repository_integration_id
        )
        for repository in repositories
    ):
        return None
    resolved = resolve_staged_repository_binding(
        team_id=team_id,
        actor_id=actor_id,
        repository=config.repository,
        github_integration_id=config.repository_integration_id,
    )
    if resolved is None:
        return None
    return StagedRepositoryBinding(
        repository=resolved.repository,
        base_sha=resolved.base_sha,
        base_branch=resolved.base_branch,
        github_integration_id=resolved.github_integration_id,
        github_user_integration_id=resolved.github_user_integration_id,
        github_installation_id=resolved.github_installation_id,
        grant_version=resolved.grant_version,
    )


def claim_recommendation_run(
    *, team_id: int, subscription_id: int, delivery_id: UUID, actor_id: int, snapshot: Mapping[str, object]
) -> RecommendationRunDTO:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    snapshot_hash = hashlib.sha256(encoded).hexdigest()
    try:
        with transaction.atomic():
            ProactiveSubscriptionConfig.objects.for_team(team_id).get_or_create(
                subscription_id=subscription_id,
                defaults={"team_id": team_id},
            )
            run = ProactiveRecommendationRun.objects.for_team(team_id).create(
                team_id=team_id,
                subscription_id=subscription_id,
                delivery_id=delivery_id,
                actor_id=actor_id,
                snapshot_hash=snapshot_hash,
            )
    except IntegrityError:
        run = ProactiveRecommendationRun.objects.for_team(team_id).get(delivery_id=delivery_id)
        if run.subscription_id != subscription_id or run.actor_id != actor_id or run.snapshot_hash != snapshot_hash:
            raise ValueError("recommendation delivery replay does not match its claimed run")
    return RecommendationRunDTO(id=run.id, status=cast(RecommendationStatus, run.status))


def read_recommendation_appendix(*, team_id: int, delivery_id: UUID) -> RecommendationAppendixDTO | None:
    run = ProactiveRecommendationRun.objects.for_team(team_id).filter(delivery_id=delivery_id).first()
    return (
        _appendix_for_run(run) if run is not None and run.status != ProactiveRecommendationRun.Status.PENDING else None
    )


def finalize_recommendation_run(
    *, team_id: int, run_id: UUID, result: RecommendationResult | None = None, failure_code: str | None = None
) -> RecommendationAppendixDTO:
    with transaction.atomic():
        run = ProactiveRecommendationRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        if run.status != ProactiveRecommendationRun.Status.PENDING:
            return _appendix_for_run(run)
        if (result is None) == (failure_code is None):
            raise ValueError("exactly one terminal recommendation result is required")
        if failure_code is not None:
            run.status = ProactiveRecommendationRun.Status.FAILED
            run.failure_code = failure_code[:128]
            run.save(update_fields=["status", "failure_code", "updated_at"])
            return RecommendationAppendixDTO(
                status="failed", recommendations=(), citations=(), failure_code=run.failure_code
            )
        assert result is not None
        # One quiet control row serializes finalization for this subscription. This makes the
        # 90-day check-and-insert exact without locking the hot Team row or adding another model.
        ProactiveSubscriptionConfig.objects.for_team(team_id).select_for_update().get(
            subscription_id=run.subscription_id
        )
        blocked_keys = set(_recent_semantic_keys(team_id=team_id, subscription_id=run.subscription_id))
        allowed: list[Recommendation] = []
        for item in result.recommendations:
            if item.semantic_key in blocked_keys:
                continue
            blocked_keys.add(item.semantic_key)
            allowed.append(item)
            if len(allowed) == 3:
                break
        for item in allowed:
            ProactiveRecommendation.objects.for_team(team_id).create(
                team_id=team_id,
                run=run,
                semantic_key=item.semantic_key,
                recommendation=_recommendation_payload(item),
                citations=[
                    _citation_payload(citation) for citation in result.citations if citation.id in item.citation_ids
                ],
            )
        run.status = ProactiveRecommendationRun.Status.COMPLETED
        run.save(update_fields=["status", "updated_at"])
        return _appendix_for_run(run)


def start_or_reuse_recommendation_generation(
    *, input: RecommendationGenerationInput, run_id: UUID
) -> RecommendationGenerationHandle:
    artifact_config_hash = _artifact_config_hash(input)
    repository_binding = _repository_binding_payload(input.repository)
    with transaction.atomic():
        run = ProactiveRecommendationRun.objects.for_team(input.team_id).select_for_update().get(id=run_id)
        handles = (run.staged_run_id, run.task_id, run.analysis_run_id)
        if any(handle is not None for handle in handles):
            if not all(handle is not None for handle in handles):
                raise ValueError("recommendation generation handles are partial")
            if run.artifact_config_hash != artifact_config_hash or not _is_valid_repository_binding_payload(
                run.repository_binding, input
            ):
                raise ValueError("recommendation generation replay does not match its frozen binding")
            assert run.staged_run_id is not None
            assert run.task_id is not None
            assert run.analysis_run_id is not None
            return RecommendationGenerationHandle(
                staged_run_id=run.staged_run_id,
                task_id=run.task_id,
                analysis_run_id=run.analysis_run_id,
            )
        if run.artifact_config_hash is not None or run.repository_binding is not None:
            raise ValueError("recommendation generation binding is partial")
        handle = start_recommendation_generation(input)
        run.staged_run_id = handle.staged_run_id
        run.task_id = handle.task_id
        run.analysis_run_id = handle.analysis_run_id
        run.repository_binding = repository_binding
        run.artifact_config_hash = artifact_config_hash
        run.save(
            update_fields=[
                "staged_run_id",
                "task_id",
                "analysis_run_id",
                "repository_binding",
                "artifact_config_hash",
                "updated_at",
            ]
        )
        return handle


def _artifact_config_hash(input: RecommendationGenerationInput) -> str:
    payload = {
        "create_draft_pr": input.create_draft_pr,
        "repository": input.repository_name,
        "repository_integration_id": input.repository_integration_id,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _repository_binding_payload(binding: StagedRepositoryBinding | None) -> dict[str, object] | None:
    if binding is None:
        return None
    return {
        "repository": binding.repository,
        "base_sha": binding.base_sha,
        "base_branch": binding.base_branch,
        "github_integration_id": binding.github_integration_id,
        "github_user_integration_id": str(binding.github_user_integration_id),
        "github_installation_id": binding.github_installation_id,
        "grant_version": binding.grant_version,
    }


def _is_valid_repository_binding_payload(payload: object, input: RecommendationGenerationInput) -> bool:
    if payload is None:
        return True
    if not isinstance(payload, dict):
        return False
    expected_fields = {
        "repository",
        "base_sha",
        "base_branch",
        "github_integration_id",
        "github_user_integration_id",
        "github_installation_id",
        "grant_version",
    }
    if set(payload) != expected_fields:
        return False
    if input.repository_name is not None and (
        not isinstance(payload["repository"], str)
        or _repository_identity(payload["repository"]) != _repository_identity(input.repository_name)
    ):
        return False
    return all(
        isinstance(payload[key], str) and payload[key] for key in expected_fields - {"github_integration_id"}
    ) and isinstance(payload["github_integration_id"], int)


def _repository_identity(repository: str) -> str:
    """Compare repository names using GitHub's case-insensitive identity."""
    return repository.casefold()


def recent_recommendation_memory(*, team_id: int, subscription_id: int) -> tuple[RecommendationMemoryDTO, ...]:
    rows = (
        ProactiveRecommendation.objects.for_team(team_id)
        .filter(run__subscription_id=subscription_id, created_at__gte=timezone.now() - timedelta(days=90))
        .order_by("-created_at")[:MAX_MEMORY_ROWS]
    )
    result: list[RecommendationMemoryDTO] = []
    used = 0
    for row in rows:
        title = row.recommendation.get("title") if isinstance(row.recommendation, dict) else None
        if not isinstance(title, str):
            continue
        item = RecommendationMemoryDTO(
            semantic_key=row.semantic_key, title=title, created_at=row.created_at.isoformat()
        )
        size = len(json.dumps(_memory_item_payload(item), sort_keys=True, separators=(",", ":")).encode())
        if used + size > MAX_MEMORY_BYTES:
            break
        used += size
        result.append(item)
    return tuple(result)


def _recent_semantic_keys(*, team_id: int, subscription_id: int) -> list[str]:
    return list(
        ProactiveRecommendation.objects.for_team(team_id)
        .filter(run__subscription_id=subscription_id, created_at__gte=timezone.now() - timedelta(days=90))
        .values_list("semantic_key", flat=True)
    )


def _memory_item_payload(item: RecommendationMemoryDTO) -> dict[str, str]:
    return {
        "semantic_key": item.semantic_key,
        "title": item.title,
        "created_at": item.created_at,
    }


def _appendix_for_run(run: ProactiveRecommendationRun) -> RecommendationAppendixDTO:
    rows = ProactiveRecommendation.objects.for_team(run.team_id).filter(run=run).order_by("created_at")
    recommendations: list[Recommendation] = []
    citations: dict[str, RecommendationCitation] = {}
    for row in rows:
        payload = row.recommendation
        if not isinstance(payload, dict):
            continue
        try:
            recommendation = Recommendation(
                kind=payload["kind"],
                title=payload["title"],
                rationale=payload["rationale"],
                target=payload["target"],
                why_now=payload["why_now"],
                confidence=payload["confidence"],
                effort=payload["effort"],
                metric_name=payload["metric_name"],
                metric_direction=payload["metric_direction"],
                expected_metric_movement=payload["expected_metric_movement"],
                citation_ids=tuple(payload["citation_ids"]),
                semantic_key=row.semantic_key,
            )
        except (KeyError, TypeError):
            continue
        recommendations.append(recommendation)
        for citation in row.citations:
            if (
                isinstance(citation, dict)
                and isinstance(citation.get("id"), str)
                and isinstance(citation.get("title"), str)
            ):
                citations[citation["id"]] = RecommendationCitation(
                    id=citation["id"],
                    title=citation["title"],
                    url=citation.get("url") if isinstance(citation.get("url"), str) else None,
                )
    return RecommendationAppendixDTO(
        status=cast(RecommendationStatus, run.status),
        recommendations=tuple(recommendations),
        citations=tuple(citations.values()),
        failure_code=run.failure_code,
    )


def _recommendation_payload(item: Recommendation) -> dict[str, object]:
    return {
        "kind": item.kind,
        "title": item.title,
        "rationale": item.rationale,
        "target": item.target,
        "why_now": item.why_now,
        "confidence": item.confidence,
        "effort": item.effort,
        "metric_name": item.metric_name,
        "metric_direction": item.metric_direction,
        "expected_metric_movement": item.expected_metric_movement,
        "citation_ids": list(item.citation_ids),
    }


def _citation_payload(citation: RecommendationCitation) -> dict[str, str | None]:
    return {"id": citation.id, "title": citation.title, "url": citation.url}
