"""Narrow persistence boundary for subscription-triggered recommendations."""

from __future__ import annotations

import json
import time
import hashlib
from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.subscriptions.backend.facade.api import read_recommendation_generation, start_recommendation_generation
from products.subscriptions.backend.facade.contracts import (
    Recommendation,
    RecommendationCitation,
    RecommendationGenerationInput,
    RecommendationResult,
    RecommendationStatus,
)
from products.subscriptions.backend.models import (
    ProactiveRecommendation,
    ProactiveRecommendationRun,
    ProactiveSubscriptionConfig,
)

MAX_MEMORY_ROWS = 20
MAX_MEMORY_BYTES = 12_000


@frozen
class ProactiveConfigDTO:
    enabled: bool
    allow_public_web_research: bool


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
    )


def update_proactive_config(
    *, team_id: int, subscription_id: int, enabled: bool, allow_public_web_research: bool
) -> ProactiveConfigDTO:
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
                },
            )
        )
        if config.enabled != enabled or config.allow_public_web_research != allow_public_web_research:
            config.enabled = enabled
            config.allow_public_web_research = allow_public_web_research
            config.save(update_fields=["enabled", "allow_public_web_research", "updated_at"])
    return ProactiveConfigDTO(enabled=config.enabled, allow_public_web_research=config.allow_public_web_research)


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


def generate_recommendation_appendix(
    *,
    input: RecommendationGenerationInput,
    snapshot: dict[str, object],
    timeout_seconds: float,
    poll_interval_seconds: float = 10,
    on_wait: Callable[[], None] | None = None,
) -> RecommendationAppendixDTO:
    """Own one replay-safe recommendation run from claim through terminal persistence."""

    run = claim_recommendation_run(
        team_id=input.team_id,
        subscription_id=input.subscription_id,
        delivery_id=input.delivery_id,
        actor_id=input.actor_id,
        snapshot=snapshot,
    )
    try:
        handle = start_recommendation_generation(input)
        deadline = time.monotonic() + max(timeout_seconds, 0)
        state = read_recommendation_generation(input, handle)
        while state.status == "pending" and time.monotonic() < deadline:
            if on_wait is not None:
                on_wait()
            time.sleep(min(max(poll_interval_seconds, 0), max(deadline - time.monotonic(), 0)))
            state = read_recommendation_generation(input, handle)

        if state.status != "completed" or state.result is None:
            failure_code = "timeout" if state.status == "pending" else state.failure_code
            return finalize_recommendation_run(
                team_id=input.team_id,
                run_id=run.id,
                failure_code=failure_code or "generation_failed",
            )
        return finalize_recommendation_run(team_id=input.team_id, run_id=run.id, result=state.result)
    except Exception:
        return finalize_recommendation_run(
            team_id=input.team_id,
            run_id=run.id,
            failure_code="pulse_failure",
        )


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
