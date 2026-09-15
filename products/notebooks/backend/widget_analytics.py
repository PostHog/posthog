from collections.abc import Mapping
from dataclasses import asdict
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.event_usage import EventSource, get_event_source, report_user_or_team_action
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated

if TYPE_CHECKING:
    from rest_framework.request import Request

    from products.notebooks.backend.models import GeneratedWidget


WidgetOperation = Literal[
    "publish", "attach", "fork", "save_version", "discard", "restore", "demo_data_update", "generate"
]


# ActivityDetailEncoder serializes context through __dict__.
@frozen(slots=False)
class ReusableWidgetActivityContext(ActivityContextBase):
    operation: WidgetOperation
    widget_id: str
    version_id: str | None
    origin: str
    notebook_id: str | None
    node_id: str | None
    is_rebind: bool
    bindings_use_hog: bool
    previous_version_id: str | None
    source_widget_id: str | None
    generation_id: str | None
    generation_operation: str | None


def reusable_widget_origin(request: "Request", *, automatic: bool = False) -> str:
    if automatic:
        return "auto_attach"
    source = get_event_source(request)
    return "ui" if source == EventSource.WEB else source.value


def record_reusable_widget_operation(
    *,
    widget: "GeneratedWidget",
    operation: WidgetOperation,
    version_id: UUID | None,
    user_id: int | None,
    origin: str,
    notebook_id: UUID | None = None,
    node_id: str | None = None,
    input_bindings: Mapping[str, object] | None = None,
    is_rebind: bool = False,
    previous_version_id: UUID | None = None,
    source_widget_id: UUID | None = None,
    generation_id: UUID | None = None,
    generation_operation: str | None = None,
) -> None:
    context = ReusableWidgetActivityContext(
        operation=operation,
        widget_id=str(widget.id),
        version_id=str(version_id) if version_id is not None else None,
        origin=origin,
        notebook_id=str(notebook_id) if notebook_id is not None else None,
        node_id=node_id,
        is_rebind=is_rebind,
        bindings_use_hog=any(
            isinstance(binding, dict) and bool(binding.get("hog")) for binding in (input_bindings or {}).values()
        ),
        previous_version_id=str(previous_version_id) if previous_version_id is not None else None,
        source_widget_id=str(source_widget_id) if source_widget_id is not None else None,
        generation_id=str(generation_id) if generation_id is not None else None,
        generation_operation=generation_operation,
    )
    team_id = widget.team_id
    name = widget.name
    was_impersonated = get_was_impersonated()

    def record() -> None:
        team = Team.objects.select_related("organization").get(id=team_id)
        user = User.objects.filter(id=user_id).first() if user_id is not None else None
        # Business operations span several rows, including hard-deleted drafts; model signals cannot describe them.
        if operation in {"publish", "save_version", "discard", "restore", "demo_data_update"}:
            field = {
                "publish": "publication_status",
                "save_version": "current_version_id",
                "discard": "pending_version_id",
                "restore": "current_version_id",
                "demo_data_update": "demo_data",
            }[operation]
            before = context.previous_version_id
            after = context.version_id
            if operation == "publish":
                before, after = "private", "published"
            elif operation == "discard":
                before, after = context.version_id, None
            elif operation == "demo_data_update":
                before, after = None, None
            log_activity(
                organization_id=team.organization_id,
                team_id=team_id,
                user=user,
                was_impersonated=was_impersonated,
                item_id=context.widget_id,
                scope="GeneratedWidget",
                activity="updated",
                detail=Detail(
                    name=name,
                    context=context,
                    changes=[Change(type="GeneratedWidget", action="changed", field=field, before=before, after=after)],
                ),
            )
        report_user_or_team_action(
            "reusable widget operation", asdict(context), user=user, team=team, organization=team.organization
        )

    # A later failure in the caller's transaction must not leave a success event or audit entry.
    transaction.on_commit(record, robust=True)
