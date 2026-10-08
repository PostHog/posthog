"""Matches the metric names of one team with the bank, and asks the model which dashboards to suggest and to make."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.dashboard_import.catalog import CATALOG_LIMIT, MetricCatalog
from products.metrics.backend.models import (
    MetricsDashboardDiscovery,
    MetricsDashboardSuggestion,
    MetricsDashboardTemplate,
)
from products.metrics.backend.suggested_dashboards import prompts
from products.metrics.backend.suggested_dashboards.generation import GenerationRequest, generation_key
from products.metrics.backend.suggested_dashboards.llm import ModelFailed, ModelUnavailable, ask_model, text_block
from products.metrics.backend.suggested_dashboards.matching import TemplateMatch, match_template, metric_families
from products.metrics.backend.suggested_dashboards.spec import MAX_REASON_LENGTH, EvaluationAnswer, TemplatePanel

logger = structlog.get_logger(__name__)

MAX_NEW_DASHBOARDS = 5
MIN_NEW_DASHBOARD_METRICS = 4
# A proposal that shares this much with a template that exists, or that waits for review, is not made again.
MAX_PROPOSAL_OVERLAP = 0.6
MAX_PROPOSAL_METRICS = 40


@frozen
class AnalysisResult:
    analyzed: bool
    suggestion_count: int = 0
    generation_requests: tuple[GenerationRequest, ...] = ()


def bank_revision() -> str:
    """Changes whenever a template is approved, changed or withdrawn, so that every team gets analyzed again."""
    approved = MetricsDashboardTemplate.objects.filter(status=MetricsDashboardTemplate.Status.APPROVED)
    summary = approved.aggregate(latest=Max("updated_at"))
    latest = summary["latest"].isoformat() if summary["latest"] else ""
    return hashlib.sha256(f"{approved.count()}:{latest}".encode()).hexdigest()[:16]


def _panels(template: MetricsDashboardTemplate) -> list[TemplatePanel]:
    return [TemplatePanel.model_validate(panel) for panel in template.panels or []]


def _overlap(names: set[str], others: Sequence[str]) -> float:
    return len(names & set(others)) / len(names) if names else 0.0


def _proposals(answer: EvaluationAnswer, catalog: MetricCatalog, covered: set[str]) -> tuple[GenerationRequest, ...]:
    """The new dashboards of the answer that are worth a generation: real metric names, not covered, not made before."""
    existing = list(
        MetricsDashboardTemplate.objects.exclude(status=MetricsDashboardTemplate.Status.FAILED).values_list(
            "key", "metric_names"
        )
    )
    existing_keys = {key for key, _ in existing}
    requests: list[GenerationRequest] = []
    for proposal in answer.new_dashboards[:MAX_NEW_DASHBOARDS]:
        names = sorted(
            {
                entry.name
                for name in proposal.metric_names
                if (entry := catalog.resolve(name)) is not None and entry.name not in covered
            }
        )[:MAX_PROPOSAL_METRICS]
        if len(names) < MIN_NEW_DASHBOARD_METRICS:
            continue
        key = generation_key(names)
        name_set = set(names)
        if key in existing_keys or any(_overlap(name_set, others) >= MAX_PROPOSAL_OVERLAP for _, others in existing):
            continue
        requests.append(
            GenerationRequest(
                key=key,
                name=" ".join(proposal.name.split())[:200],
                description=" ".join(proposal.description.split())[:300],
                metric_names=tuple(names),
            )
        )
        existing.append((key, names))
        existing_keys.add(key)
    return tuple(requests)


def _save_suggestions(team: Team, suggested: dict[str, str], matches: dict[str, tuple[str, TemplateMatch]]) -> int:
    with transaction.atomic():
        current = {
            str(suggestion.template_id): suggestion
            for suggestion in MetricsDashboardSuggestion.objects.for_team(team.id).select_for_update()
        }
        keep: set[str] = set()
        for key, reason in suggested.items():
            template_id, match = matches[key]
            keep.add(template_id)
            values = {
                "matched_metric_names": list(match.matched_metric_names),
                "coverage": round(match.coverage, 3),
                "reason": " ".join(reason.split())[:MAX_REASON_LENGTH],
            }
            suggestion = current.get(template_id)
            if suggestion is None:
                MetricsDashboardSuggestion.objects.for_team(team.id).create(
                    team_id=team.id, template_id=template_id, **values
                )
                continue
            for field, value in values.items():
                setattr(suggestion, field, value)
            suggestion.save(update_fields=[*values, "updated_at"])
        # A suggestion that no longer fits goes away, unless the team acted on it.
        stale = [
            suggestion.id
            for template_id, suggestion in current.items()
            if template_id not in keep and suggestion.dashboard_id is None
        ]
        MetricsDashboardSuggestion.objects.for_team(team.id).filter(id__in=stale).delete()
    return len(suggested)


def _record_analysis(team: Team, names: list[str], revision: str) -> None:
    MetricsDashboardDiscovery.objects.for_team(team.id).update_or_create(
        team_id=team.id,
        defaults={"analyzed_metric_names": names, "bank_revision": revision, "analyzed_at": timezone.now()},
    )


def analyze_team(team_id: int, *, force: bool = False) -> AnalysisResult:
    """Update the suggestions of the team. Returns the new dashboards that the model wants generated.

    Without new metric names and without a change in the bank, nothing runs, unless `force` is set. Without AI
    consent or without a gateway, only the templates that most of the team's metrics fit are suggested.
    """
    team = Team.objects.select_related("organization").get(id=team_id)
    catalog = MetricCatalog.load(team)
    entries = catalog.entries(limit=CATALOG_LIMIT)
    names = sorted(entry.name for entry in entries)
    revision = bank_revision()
    state = MetricsDashboardDiscovery.objects.for_team(team.id).first()
    new_names = set(names) - set(state.analyzed_metric_names if state else [])
    if not force and state is not None and not new_names and state.bank_revision == revision:
        return AnalysisResult(analyzed=False)
    if not names:
        _record_analysis(team, names, revision)
        return AnalysisResult(analyzed=True)

    templates = list(MetricsDashboardTemplate.objects.filter(status=MetricsDashboardTemplate.Status.APPROVED))
    scored = [(template, match_template(template.key, _panels(template), catalog)) for template in templates]
    candidates = [(template, match) for template, match in scored if match.is_candidate]
    matches = {template.key: (str(template.id), match) for template, match in candidates}

    answer: EvaluationAnswer | None = None
    if team.organization.is_ai_data_processing_approved:
        try:
            answer = ask_model(
                team_id=team.id,
                stage="evaluate",
                system=prompts.EVALUATION_SYSTEM,
                content=[text_block(prompts.evaluation_input(metric_families(entries), candidates))],
                answer_type=EvaluationAnswer,
            )
        except (ModelUnavailable, ModelFailed) as error:
            logger.warning("metrics_suggested_dashboards_evaluation_skipped", team_id=team.id, reason=str(error))

    if answer is not None:
        suggested = {item.key: item.reason for item in answer.suggested if item.key in matches}
    else:
        suggested = {template.key: "" for template, match in candidates if match.is_strong}
    count = _save_suggestions(team, suggested, matches)

    requests: tuple[GenerationRequest, ...] = ()
    if answer is not None:
        covered = {name for key in suggested for name in matches[key][1].matched_metric_names}
        requests = _proposals(answer, catalog, covered)
    _record_analysis(team, names, revision)
    return AnalysisResult(analyzed=True, suggestion_count=count, generation_requests=requests)
