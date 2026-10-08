"""Reads and actions behind the facade: the suggestions of a team, and the templates of the bank for the staff review."""

from __future__ import annotations

from django.db.models import Count, QuerySet

import structlog

from posthog.models import Team, User

from products.exports.backend.facade.api import read_export_asset_content
from products.metrics.backend.facade.contracts import (
    DashboardTemplateRound,
    DashboardTemplateSummary,
    SuggestedDashboard,
    SuggestedDashboardError,
    SuggestedDashboardNotFound,
)
from products.metrics.backend.facade.enums import DashboardTemplateSource, DashboardTemplateStatus
from products.metrics.backend.models import MetricsDashboardSuggestion, MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards import review
from products.metrics.backend.suggested_dashboards.spec import GenerationRecord, TemplatePanel
from products.metrics.backend.temporal import schedule

logger = structlog.get_logger(__name__)

MAX_LISTED_TEMPLATES = 200


def _suggestion(suggestion: MetricsDashboardSuggestion) -> SuggestedDashboard:
    template = suggestion.template
    return SuggestedDashboard(
        id=str(suggestion.id),
        template_id=str(template.id),
        name=template.name,
        description=template.description,
        reason=suggestion.reason,
        panel_count=sum(1 for panel in template.panels or [] if panel.get("query")),
        matched_metric_count=len(suggestion.matched_metric_names),
        coverage=suggestion.coverage,
        dashboard_id=suggestion.dashboard_id,
    )


def list_suggestions(team: Team) -> list[SuggestedDashboard]:
    suggestions = (
        MetricsDashboardSuggestion.objects.for_team(team.id)
        .filter(template__status=MetricsDashboardTemplate.Status.APPROVED)
        .select_related("template")
        .order_by("-coverage", "template__name")
    )
    return [_suggestion(suggestion) for suggestion in suggestions]


def _get_suggestion(team: Team, suggestion_id: str) -> MetricsDashboardSuggestion:
    suggestion = (
        MetricsDashboardSuggestion.objects.for_team(team.id)
        .filter(id=suggestion_id, template__status=MetricsDashboardTemplate.Status.APPROVED)
        .select_related("template")
        .first()
    )
    if suggestion is None:
        raise SuggestedDashboardNotFound("This suggestion does not exist.")
    return suggestion


def create_from_suggestion(team: Team, user: User, suggestion_id: str) -> int:
    try:
        return review.create_from_suggestion(suggestion=_get_suggestion(team, suggestion_id), team=team, user=user)
    except review.NoPanelsWithData as error:
        raise SuggestedDashboardError(str(error)) from error


def _summary(template: MetricsDashboardTemplate, suggestion_count: int = 0) -> DashboardTemplateSummary:
    record = GenerationRecord.model_validate(template.generation or {})
    panels = [TemplatePanel.model_validate(panel) for panel in template.panels or []]
    reviewer = template.reviewed_by
    return DashboardTemplateSummary(
        id=str(template.id),
        key=template.key,
        name=template.name,
        description=template.description,
        source=DashboardTemplateSource(template.source),
        status=DashboardTemplateStatus(template.status),
        metric_names=tuple(template.metric_names),
        panel_titles=tuple(panel.title for panel in panels if panel.query),
        created_at=template.created_at,
        suggestion_count=suggestion_count,
        source_team_id=template.source_team_id,
        preview_team_id=template.preview_team_id,
        preview_dashboard_id=template.preview_dashboard_id,
        rounds=tuple(
            DashboardTemplateRound(
                round=item.round,
                has_picture=item.asset_id is not None,
                looks_good=item.looks_good,
                problems=tuple(item.problems),
                revised=item.revised,
            )
            for item in sorted(record.rounds, key=lambda item: item.round)
        ),
        dropped_panels=tuple(record.dropped_panels),
        error=record.error,
        reviewed_by=(reviewer.first_name or reviewer.email) if reviewer else None,
        reviewed_at=template.reviewed_at,
    )


def _suggestion_count(template: MetricsDashboardTemplate) -> int:
    return int(getattr(template, "active_suggestions", 0))


def _templates() -> QuerySet[MetricsDashboardTemplate]:
    return MetricsDashboardTemplate.objects.select_related("reviewed_by").annotate(
        active_suggestions=Count("suggestions")
    )


def list_templates(status: DashboardTemplateStatus | None) -> list[DashboardTemplateSummary]:
    templates = _templates().order_by("-created_at")
    if status is not None:
        templates = templates.filter(status=status.value)
    return [_summary(template, _suggestion_count(template)) for template in templates[:MAX_LISTED_TEMPLATES]]


def _get_template(template_id: str) -> MetricsDashboardTemplate:
    template = _templates().filter(id=template_id).first()
    if template is None:
        raise SuggestedDashboardNotFound("This dashboard template does not exist.")
    return template


def get_template(template_id: str) -> DashboardTemplateSummary:
    template = _get_template(template_id)
    return _summary(template, _suggestion_count(template))


def open_preview(team: Team, user: User, template_id: str) -> int:
    try:
        return review.open_preview(template=_get_template(template_id), team=team, user=user)
    except review.NoPanelsWithData as error:
        raise SuggestedDashboardError(str(error)) from error


def approve(user: User, template_id: str) -> DashboardTemplateSummary:
    try:
        template = review.approve(template=_get_template(template_id), user=user)
    except review.TemplateNotReviewable as error:
        raise SuggestedDashboardError(str(error)) from error
    # Every team gets the new template at its next sweep. The team it came from gets it now.
    if template.source_team_id is not None:
        try:
            schedule.start_team_analysis(template.source_team_id, force=True)
        except Exception:
            logger.warning("metrics_suggested_dashboards_analysis_not_started", team_id=template.source_team_id)
    return get_template(str(template.id))


def reject(user: User, template_id: str) -> DashboardTemplateSummary:
    try:
        template = review.reject(template=_get_template(template_id), user=user)
    except review.TemplateNotReviewable as error:
        raise SuggestedDashboardError(str(error)) from error
    return get_template(str(template.id))


def picture(template_id: str, round_number: int) -> bytes | None:
    template = _get_template(template_id)
    record = GenerationRecord.model_validate(template.generation or {})
    item = next((item for item in record.rounds if item.round == round_number), None)
    if item is None or item.asset_id is None or template.source_team_id is None:
        return None
    return read_export_asset_content(team_id=template.source_team_id, asset_id=item.asset_id)
