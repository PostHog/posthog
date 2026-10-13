"""The staff review of templates, and the dashboards that teams create from their suggestions."""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from posthog.event_usage import report_user_action
from posthog.models import Team, User

from products.dashboards.backend.facade.api import unknown_dashboard_ids
from products.dashboards.backend.facade.dashboard_creation import delete_unlisted_dashboard, read_dashboard_tiles
from products.metrics.backend.dashboard_import.catalog import MetricCatalog
from products.metrics.backend.dashboard_import.spec import GridLayout
from products.metrics.backend.models import MetricsDashboardSuggestion, MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards.dashboards import build_tiles, create_dashboard, panels_from_tiles
from products.metrics.backend.suggested_dashboards.matching import template_metric_names
from products.metrics.backend.suggested_dashboards.spec import TemplatePanel, template_panels


class TemplateNotReviewable(Exception):
    """The template is in a state that the action does not apply to. The message is safe to show."""


class NoPanelsWithData(Exception):
    """The team sends none of the metrics of the template, so no dashboard was created."""


def _capture_reviewed(user: User, template: MetricsDashboardTemplate) -> None:
    report_user_action(
        user,
        "metrics dashboard template reviewed",
        {"template_id": str(template.id), "template_source": template.source, "decision": template.status},
    )


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
        panels=template_panels(template.panels),
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


def _unbuilt_panel_keys(template: MetricsDashboardTemplate) -> set[str]:
    """The panels that the preview left out, because its project does not send their metrics."""
    if not template.preview_team_id:
        return set()
    team = Team.objects.filter(id=template.preview_team_id).first()
    if team is None:
        return set()
    catalog = MetricCatalog.load(team)
    catalog.look_up(team, template.metric_names)
    return set(build_tiles(template_panels(template.panels), catalog).dropped_keys)


def _restore_unbuilt(
    edited: list[TemplatePanel], original: list[TemplatePanel], unbuilt: set[str]
) -> list[TemplatePanel]:
    """The edited panels, with the panels that the preview could not show added again below them.

    A reviewer can remove a panel from the preview, but cannot see or remove a panel that the preview left
    out. Such a panel stays in the template.
    """
    missing = [panel for panel in original if panel.key in unbuilt]
    if not missing:
        return edited
    bottom = max((panel.layout.y + panel.layout.h for panel in edited), default=0)
    shift = bottom - min(panel.layout.y for panel in missing)
    restored = [
        panel.model_copy(
            update={
                "key": f"p{len(edited) + index + 1}",
                "layout": GridLayout(x=panel.layout.x, y=panel.layout.y + shift, w=panel.layout.w, h=panel.layout.h),
            }
        )
        for index, panel in enumerate(missing)
    ]
    return [*edited, *restored]


def approve(*, template: MetricsDashboardTemplate, user: User) -> MetricsDashboardTemplate:
    """Approve the template. Changes made on its preview dashboard, by hand or with PostHog AI, become the template."""
    unbuilt = _unbuilt_panel_keys(template)
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
                panels = _restore_unbuilt(panels, template_panels(locked.panels), unbuilt)
                locked.panels = [panel.model_dump(mode="json") for panel in panels]
                locked.metric_names = template_metric_names(panels)
        _drop_preview(locked)
        locked.status = MetricsDashboardTemplate.Status.APPROVED
        locked.reviewed_by = user
        locked.reviewed_at = timezone.now()
        locked.save()
    _capture_reviewed(user, locked)
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
    _capture_reviewed(user, locked)
    return locked


def create_from_suggestion(*, suggestion: MetricsDashboardSuggestion, team: Team, user: User) -> int:
    """Create the suggested dashboard in the team, as the user. A second call opens the same dashboard.

    When the user deleted the dashboard, the next call creates it again.
    """
    template = suggestion.template
    catalog = MetricCatalog.load(team)
    catalog.look_up(team, template.metric_names)
    with transaction.atomic():
        # Concurrent requests wait here, so a double click creates one dashboard.
        locked = MetricsDashboardSuggestion.objects.for_team(team.id).select_for_update().get(id=suggestion.id)
        previous = locked.dashboard_id
        if previous is not None and not unknown_dashboard_ids([previous], team_id=team.id):
            return previous
        created, built = create_dashboard(
            team=team,
            user=user,
            name=template.name,
            description=template.description,
            panels=template_panels(template.panels),
            catalog=catalog,
            # A deleted dashboard keeps its insights' ids, so a new one needs a new key.
            idempotency_key=f"metrics-suggestion:{suggestion.id}" + (f":after-{previous}" if previous else ""),
        )
        if created is None:
            raise NoPanelsWithData("This project no longer sends the metrics of this dashboard.")
        locked.dashboard_id = created.id
        locked.save(update_fields=["dashboard_id", "updated_at"])
    report_user_action(
        user,
        "metrics suggested dashboard created",
        {
            "template_id": str(template.id),
            "template_source": template.source,
            "dashboard_id": created.id,
            "coverage": suggestion.coverage,
            "dropped_panel_count": len(built.dropped),
        },
        team=team,
    )
    return created.id
