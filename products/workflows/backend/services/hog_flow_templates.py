from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db.models import Q, QuerySet

from posthog.cdp.flag_gated_templates import hidden_gated_template_ids

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.contracts import (
    FunctionTemplateSchema,
    WorkflowTemplate,
    WorkflowTemplateNotFound,
)
from products.workflows.backend.facade.enums import HogFlowTemplateExitCondition, HogFlowTemplateScope
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate
from products.workflows.backend.templates import get_global_template_by_id, load_global_templates

if TYPE_CHECKING:
    from posthog.models import Team

WRITABLE_TEMPLATE_FIELDS = frozenset(
    {
        "name",
        "description",
        "image_url",
        "tags",
        "scope",
        "trigger",
        "trigger_masking",
        "conversion",
        "exit_condition",
        "edges",
        "actions",
        "abort_action",
        "variables",
    }
)


def _to_template(template: HogFlowTemplate) -> WorkflowTemplate:
    return WorkflowTemplate(
        id=template.id,
        team_id=template.team_id,
        name=template.name,
        description=template.description,
        image_url=template.image_url,
        tags=template.tags,
        scope=HogFlowTemplateScope(template.scope),
        created_at=template.created_at,
        created_by=template.created_by,
        updated_at=template.updated_at,
        trigger=template.trigger,
        trigger_masking=template.trigger_masking,
        conversion=template.conversion,
        exit_condition=HogFlowTemplateExitCondition(template.exit_condition),
        edges=template.edges,
        actions=template.actions,
        abort_action=template.abort_action,
        variables=template.variables,
    )


def _visible_templates(team_id: int, organization_id: UUID) -> QuerySet[HogFlowTemplate]:
    # A team sees its own templates plus the organization-scoped templates of every team in the
    # organization. Global templates live in code, so a global row in the table is never served.
    return (
        HogFlowTemplate.objects.filter(
            Q(team_id=team_id) | Q(scope=HogFlowTemplateScope.ORGANIZATION, team__organization_id=organization_id)
        )
        .exclude(scope=HogFlowTemplateScope.GLOBAL)
        .select_related("created_by")
    )


def list_templates(*, team_id: int, organization_id: UUID) -> list[WorkflowTemplate]:
    return [_to_template(t) for t in _visible_templates(team_id, organization_id).order_by("-updated_at")]


def get_template(*, team_id: int, organization_id: UUID, template_id: str) -> WorkflowTemplate | None:
    try:
        template_uuid = UUID(template_id)
    except ValueError:
        return None
    template = _visible_templates(team_id, organization_id).filter(id=template_uuid).first()
    return _to_template(template) if template is not None else None


def create_template(*, team_id: int, created_by_id: int, fields: Mapping[str, Any]) -> WorkflowTemplate:
    values = {key: value for key, value in fields.items() if key in WRITABLE_TEMPLATE_FIELDS}
    if not values.get("scope"):
        values["scope"] = HogFlowTemplateScope.ONLY_TEAM
    template = HogFlowTemplate.objects.create(team_id=team_id, created_by_id=created_by_id, **values)
    return _to_template(template)


def update_template(
    *, template_id: UUID, team_id: int, organization_id: UUID, fields: Mapping[str, Any]
) -> WorkflowTemplate:
    """Apply the changed fields. The editing team becomes the owner, so an organization template
    edited from another project moves to that project."""
    template = _visible_templates(team_id, organization_id).filter(id=template_id).first()
    if template is None:
        raise WorkflowTemplateNotFound()
    for key, value in fields.items():
        if key in WRITABLE_TEMPLATE_FIELDS:
            setattr(template, key, value)
    template.team_id = team_id
    template.save()
    return _to_template(template)


def delete_template(*, template_id: UUID, team_id: int, organization_id: UUID) -> None:
    _visible_templates(team_id, organization_id).filter(id=template_id).delete()


def list_global_templates() -> list[dict[str, Any]]:
    # A copy, so a caller that sorts the list cannot reorder the shared cache.
    return list(load_global_templates())


def _uses_any_function_template(template: Mapping[str, Any], function_template_ids: set[str]) -> bool:
    return any(
        isinstance(action.get("config"), dict) and action["config"].get("template_id") in function_template_ids
        for action in template.get("actions") or []
    )


# A team that cannot use a flag-gated step would get a workflow it cannot save, so the
# templates built on that step stay hidden until its flag is on.
def list_global_templates_for_team(team: "Team") -> list[dict[str, Any]]:
    hidden = set(hidden_gated_template_ids(team))
    return [template for template in load_global_templates() if not _uses_any_function_template(template, hidden)]


def get_global_template_for_team(template_id: str, team: "Team") -> dict[str, Any] | None:
    template = get_global_template_by_id(template_id)
    if template is None or _uses_any_function_template(template, set(hidden_gated_template_ids(team))):
        return None
    return template


def function_template_exists(template_id: str) -> bool:
    return HogFunctionTemplate.get_template(template_id) is not None


def get_function_template_schema(template_id: str) -> FunctionTemplateSchema | None:
    template = HogFunctionTemplate.get_template(template_id)
    if template is None:
        return None
    return FunctionTemplateSchema(type=template.type, inputs_schema=template.inputs_schema)
