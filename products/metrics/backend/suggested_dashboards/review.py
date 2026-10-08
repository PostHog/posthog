"""The staff review of templates, and the dashboards that teams create from their suggestions."""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from posthog.models import Team, User

from products.dashboards.backend.facade.dashboard_creation import delete_unlisted_dashboard, read_dashboard_tiles
from products.metrics.backend.dashboard_import.catalog import MetricCatalog
from products.metrics.backend.models import MetricsDashboardSuggestion, MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards.dashboards import create_dashboard, panels_from_tiles
from products.metrics.backend.suggested_dashboards.matching import template_metric_names
from products.metrics.backend.suggested_dashboards.spec import TemplatePanel


class TemplateNotReviewable(Exception):
    """The template is in a state that the action does not apply to. The message is safe to show."""


class NoPanelsWithData(Exception):
    """The team sends none of the metrics of the template, so no dashboard was created."""


def _panels(template: MetricsDashboardTemplate) -> list[TemplatePanel]:
    return [TemplatePanel.model_validate(panel) for panel in template.panels or []]


def _drop_preview(template: MetricsDashboardTemplate) -> None:
    if template.preview_team_id and template.preview_dashboard_id:
        delete_unlisted_dashboard(team_id=template.preview_team_id, dashboard_id=template.preview_dashboard_id)
    template.preview_team_id = None
    template.preview_dashboard_id = None


def open_preview(*, template: MetricsDashboardTemplate, team: Team, user: User) -> int:
    """The unlisted preview dashboard of the template in this team, built now when it does not exist."""
    if template.preview_team_id == team.id and template.preview_dashboard_id:
        if read_dashboard_tiles(team_id=team.id, dashboard_id=template.preview_dashboard_id):
            return template.preview_dashboard_id
    catalog = MetricCatalog.load(team)
    catalog.look_up(team, template.metric_names)
    created, _ = create_dashboard(
        team=team,
        user=user,
        name=template.name,
        description=template.description,
        panels=_panels(template),
        catalog=catalog,
        idempotency_key=f"metrics-template-review:{template.id}:{uuid.uuid4()}",
        unlisted=True,
    )
    if created is None:
        raise NoPanelsWithData("This project sends none of the metrics of this dashboard.")
    with transaction.atomic():
        locked = MetricsDashboardTemplate.objects.select_for_update().get(id=template.id)
        _drop_preview(locked)
        locked.preview_team_id = team.id
        locked.preview_dashboard_id = created.id
        locked.save(update_fields=["preview_team_id", "preview_dashboard_id", "updated_at"])
    return created.id


def approve(*, template: MetricsDashboardTemplate, user: User) -> MetricsDashboardTemplate:
    """Approve the template. Changes made on its preview dashboard, by hand or with PostHog AI, become the template."""
    with transaction.atomic():
        locked = MetricsDashboardTemplate.objects.select_for_update().get(id=template.id)
        if locked.status not in (
            MetricsDashboardTemplate.Status.PENDING_REVIEW,
            MetricsDashboardTemplate.Status.REJECTED,
        ):
            raise TemplateNotReviewable("Only a dashboard that waits for review, or a rejected one, can be approved.")
        if locked.preview_team_id and locked.preview_dashboard_id:
            panels = panels_from_tiles(
                read_dashboard_tiles(team_id=locked.preview_team_id, dashboard_id=locked.preview_dashboard_id)
            )
            if panels:
                locked.panels = [panel.model_dump(mode="json") for panel in panels]
                locked.metric_names = template_metric_names(panels)
        _drop_preview(locked)
        locked.status = MetricsDashboardTemplate.Status.APPROVED
        locked.reviewed_by = user
        locked.reviewed_at = timezone.now()
        locked.save()
    return locked


def reject(*, template: MetricsDashboardTemplate, user: User) -> MetricsDashboardTemplate:
    with transaction.atomic():
        locked = MetricsDashboardTemplate.objects.select_for_update().get(id=template.id)
        if locked.source == MetricsDashboardTemplate.Source.CURATED:
            raise TemplateNotReviewable("A curated dashboard comes from the code. Remove its file to withdraw it.")
        _drop_preview(locked)
        locked.status = MetricsDashboardTemplate.Status.REJECTED
        locked.reviewed_by = user
        locked.reviewed_at = timezone.now()
        locked.save()
        # Suggestions that a team has not acted on go away with the template.
        MetricsDashboardSuggestion.objects.unscoped().filter(template_id=locked.id, dashboard_id__isnull=True).delete()
    return locked


def create_from_suggestion(*, suggestion: MetricsDashboardSuggestion, team: Team, user: User) -> int:
    """Create the suggested dashboard in the team, as the user. A second call opens the same dashboard."""
    if suggestion.dashboard_id is not None:
        return suggestion.dashboard_id
    template = suggestion.template
    catalog = MetricCatalog.load(team)
    catalog.look_up(team, template.metric_names)
    try:
        created, _ = create_dashboard(
            team=team,
            user=user,
            name=template.name,
            description=template.description,
            panels=_panels(template),
            catalog=catalog,
            idempotency_key=f"metrics-suggestion:{suggestion.id}",
        )
    except ValueError:
        # The idempotency key collided: another request created this dashboard first.
        existing = (
            MetricsDashboardSuggestion.objects.for_team(team.id)
            .filter(id=suggestion.id)
            .values_list("dashboard_id", flat=True)
            .first()
        )
        if existing is not None:
            return existing
        raise
    if created is None:
        raise NoPanelsWithData("This project no longer sends the metrics of this dashboard.")
    MetricsDashboardSuggestion.objects.for_team(team.id).filter(id=suggestion.id).update(
        dashboard_id=created.id, updated_at=timezone.now()
    )
    return created.id
