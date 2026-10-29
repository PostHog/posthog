"""The staff review of templates, and the dashboards that teams create from their suggestions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from django.db import transaction
from django.utils import timezone

from pydantic import ValidationError

from posthog.schema import MetricsDashboardVariable, MetricsDashboardVariableSelection, MetricsDashboardVariableSource

from posthog.event_usage import report_user_action
from posthog.models import Team, User

from products.dashboards.backend.facade.api import unknown_dashboard_ids
from products.dashboards.backend.facade.dashboard_creation import (
    delete_unlisted_dashboard,
    read_dashboard_metric_variables,
    read_dashboard_tiles,
)
from products.metrics.backend.dashboard_import.catalog import MetricCatalog
from products.metrics.backend.dashboard_import.spec import GridLayout
from products.metrics.backend.models import MetricsDashboardSuggestion, MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards.dashboards import (
    create_dashboard,
    drop_preview,
    panels_from_tiles,
    referenced_variables,
)
from products.metrics.backend.suggested_dashboards.llm import MODEL
from products.metrics.backend.suggested_dashboards.matching import template_metric_names
from products.metrics.backend.suggested_dashboards.spec import GenerationRecord, TemplatePanel, template_panels


class TemplateNotReviewable(Exception):
    """The template is in a state that the action does not apply to. The message is safe to show."""


class SuggestionGone(Exception):
    """An analysis or a review removed the suggestion while the user created its dashboard."""


class NoPanelsWithData(Exception):
    """The team sends none of the metrics of the template, so no dashboard was created."""


def _capture_reviewed(user: User, template: MetricsDashboardTemplate) -> None:
    report_user_action(
        user,
        "metrics dashboard template reviewed",
        {"template_id": str(template.id), "template_source": template.source, "decision": template.status},
    )


def _awaits_review(template: MetricsDashboardTemplate) -> bool:
    return template.source != MetricsDashboardTemplate.Source.CURATED and template.status in (
        MetricsDashboardTemplate.Status.PENDING_REVIEW,
        MetricsDashboardTemplate.Status.REJECTED,
    )


def open_preview(*, template: MetricsDashboardTemplate, team: Team, user: User) -> int:
    """The unlisted preview dashboard of the template in this team, built now when it does not exist."""
    # Only a review clears the preview, so a template that waits for no review gets none.
    if not _awaits_review(template):
        raise TemplateNotReviewable("Only a dashboard that waits for review has a preview.")
    if template.preview_team_id == team.id and template.preview_dashboard_id:
        if read_dashboard_tiles(team_id=team.id, dashboard_id=template.preview_dashboard_id):
            return template.preview_dashboard_id
    catalog = MetricCatalog.load(team)
    catalog.look_up(team, template.metric_names)
    created, built = create_dashboard(
        team=team,
        user=user,
        name=template.name,
        description=template.description,
        panels=template_panels(template.panels),
        catalog=catalog,
        idempotency_key=f"metrics-template-review:{template.id}:{uuid.uuid4()}",
        unlisted=True,
        variables=template.variables or [],
        # The panels keep their boxes, so the ones that the preview leaves out can go back in place on approve.
        refill=False,
    )
    if created is None:
        raise NoPanelsWithData("This project sends none of the metrics of this dashboard.")
    with transaction.atomic():
        locked = MetricsDashboardTemplate.objects.select_for_update().get(id=template.id)
        if not _awaits_review(locked):
            # A review committed while the preview was built. That review dropped the previews it knew of.
            delete_unlisted_dashboard(team_id=team.id, dashboard_id=created.id)
            raise TemplateNotReviewable("This dashboard was reviewed while its preview was built.")
        drop_preview(locked)
        locked.preview_team_id = team.id
        locked.preview_dashboard_id = created.id
        locked.preview_unbuilt_keys = list(built.dropped_keys)
        locked.save(update_fields=["preview_team_id", "preview_dashboard_id", "preview_unbuilt_keys", "updated_at"])
    return created.id


def _overlaps(a: GridLayout, b: GridLayout) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def _restore_unbuilt(
    edited: list[TemplatePanel], original: list[TemplatePanel], unbuilt: set[str]
) -> list[TemplatePanel]:
    """The edited panels, with the panels that the preview could not show added again.

    A reviewer can remove a panel from the preview, but cannot see or remove a panel that the preview left
    out. Such a panel stays in the template.
    """
    missing = [panel for panel in original if panel.key in unbuilt]
    # The preview kept the gaps of the missing panels. Unless the reviewer filled them, they go back in place.
    if any(_overlaps(panel.layout, other.layout) for panel in missing for other in edited):
        bottom = max((panel.layout.y + panel.layout.h for panel in edited), default=0)
        shift = bottom - min(panel.layout.y for panel in missing)
        missing = [
            panel.model_copy(
                update={
                    "layout": GridLayout(x=panel.layout.x, y=panel.layout.y + shift, w=panel.layout.w, h=panel.layout.h)
                }
            )
            for panel in missing
        ]
    # Keys must stay unique: panels_from_tiles numbers by tile position and skips tiles it cannot use.
    return [panel.model_copy(update={"key": f"p{index + 1}"}) for index, panel in enumerate([*edited, *missing])]


def _shared_variables(edited: Sequence[Any], original: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The variables of the preview, safe to give to every project, then the template's variables that it lacks.

    A definition that does not parse is left out, so the template keeps its own. So is a custom list, because its
    values come from the preview's project, not from the project that opens the dashboard. A selection can name a
    host or a service of the preview's project, so every variable selects All.
    """
    shared: list[dict[str, Any]] = []
    for item in edited:
        try:
            variable = MetricsDashboardVariable.model_validate(item)
        except ValidationError:
            continue
        if variable.source == MetricsDashboardVariableSource.CUSTOM or variable.customValues:
            continue
        variable = variable.model_copy(
            update={"includeAll": True, "current": MetricsDashboardVariableSelection(values=[], all=True)}
        )
        shared.append(variable.model_dump(mode="json", exclude_none=True))
    names = {variable["name"] for variable in shared}
    return [*shared, *(variable for variable in original if variable.get("name") not in names)]


def approve(*, template: MetricsDashboardTemplate, user: User) -> MetricsDashboardTemplate:
    """Approve the template. Changes made on its preview dashboard, by hand or with PostHog AI, become the template."""
    with transaction.atomic():
        locked = MetricsDashboardTemplate.objects.select_for_update().get(id=template.id)
        if locked.source == MetricsDashboardTemplate.Source.CURATED:
            raise TemplateNotReviewable("A curated dashboard comes from the code. Add its file to bring it back.")
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
                panels = _restore_unbuilt(panels, template_panels(locked.panels), set(locked.preview_unbuilt_keys))
                locked.panels = [panel.model_dump(mode="json") for panel in panels]
                locked.metric_names = template_metric_names(panels)
                # The preview has only the variables of the panels that it shows. The panels it left out keep theirs.
                shared = _shared_variables(
                    read_dashboard_metric_variables(
                        team_id=locked.preview_team_id, dashboard_id=locked.preview_dashboard_id
                    ),
                    locked.variables or [],
                )
                locked.variables = referenced_variables(
                    (panel.query for panel in panels if panel.query is not None), shared
                )
        drop_preview(locked)
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
        if locked.status == MetricsDashboardTemplate.Status.GENERATING:
            raise TemplateNotReviewable("This dashboard is still being generated. Review it when it is ready.")
        drop_preview(locked)
        locked.status = MetricsDashboardTemplate.Status.REJECTED
        locked.reviewed_by = user
        locked.reviewed_at = timezone.now()
        locked.save()
        # Suggestions that a team has not acted on go away with the template.
        MetricsDashboardSuggestion.objects.unscoped().filter(template_id=locked.id, dashboard_id__isnull=True).delete()
    _capture_reviewed(user, locked)
    return locked


_REGENERABLE = frozenset(
    {
        MetricsDashboardTemplate.Status.PENDING_REVIEW,
        MetricsDashboardTemplate.Status.REJECTED,
        MetricsDashboardTemplate.Status.FAILED,
    }
)


def regenerate(*, template: MetricsDashboardTemplate, user: User) -> MetricsDashboardTemplate:
    """Discard the panels and the preview of a generated template, and set it to generate again.

    The caller starts the generation. The template keeps its key, so the same metrics never make a second one.
    """
    with transaction.atomic():
        locked = MetricsDashboardTemplate.objects.select_for_update().get(id=template.id)
        if locked.source != MetricsDashboardTemplate.Source.GENERATED:
            raise TemplateNotReviewable("Only a generated dashboard can be generated again.")
        if locked.status not in _REGENERABLE:
            raise TemplateNotReviewable(
                "This dashboard is still being generated."
                if locked.status == MetricsDashboardTemplate.Status.GENERATING
                else "Reject this dashboard before you generate it again."
            )
        source_team = Team.objects.select_related("organization").filter(id=locked.source_team_id).first()
        if source_team is None:
            raise TemplateNotReviewable("The project that this dashboard came from no longer exists.")
        if not source_team.organization.is_ai_data_processing_approved:
            raise TemplateNotReviewable("The organization of the source project does not allow AI data processing.")
        record = GenerationRecord.model_validate(locked.generation or {})
        drop_preview(locked)
        locked.name = record.requested_name or locked.name
        locked.metric_names = record.requested_metric_names or locked.metric_names
        locked.panels = []
        locked.variables = []
        locked.generation = GenerationRecord(
            model=MODEL, requested_name=locked.name, requested_metric_names=locked.metric_names
        ).model_dump(mode="json")
        locked.status = MetricsDashboardTemplate.Status.GENERATING
        locked.reviewed_by = None
        locked.reviewed_at = None
        locked.save()
        MetricsDashboardSuggestion.objects.unscoped().filter(template_id=locked.id, dashboard_id__isnull=True).delete()
    report_user_action(user, "metrics dashboard template regenerated", {"template_id": str(locked.id)})
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
        locked = (
            MetricsDashboardSuggestion.objects.for_team(team.id)
            # Locks only the suggestion row. Other teams create from the same template at the same time.
            .select_for_update(of=("self",))
            .filter(id=suggestion.id, template__status=MetricsDashboardTemplate.Status.APPROVED)
            .first()
        )
        if locked is None:
            raise SuggestionGone("This suggestion does not exist anymore.")
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
            variables=template.variables or [],
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
            "variable_count": len(built.variable_names),
        },
        team=team,
    )
    return created.id
