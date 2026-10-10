from collections.abc import Mapping
from typing import Any
from uuid import UUID

from django.db.models import Q, QuerySet

from posthog.cdp.flag_gated_templates import hidden_gated_template_ids
from posthog.dataclasses import frozen
from posthog.models import Team

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.workflows.backend.facade.contracts import (
    FunctionTemplateSchema,
    WorkflowTemplate,
    WorkflowTemplateNotFound,
)
from products.workflows.backend.facade.enums import HogFlowTemplateExitCondition, HogFlowTemplateScope
from products.workflows.backend.models.hog_flow.hog_flow_template import HogFlowTemplate
from products.workflows.backend.templates import get_global_template_by_id, load_global_templates

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


def get_global_template(template_id: str) -> dict[str, Any] | None:
    return get_global_template_by_id(template_id)


def function_template_exists(template_id: str) -> bool:
    return HogFunctionTemplate.get_template(template_id) is not None


def get_function_template_schema(template_id: str) -> FunctionTemplateSchema | None:
    template = HogFunctionTemplate.get_template(template_id)
    if template is None:
        return None
    return FunctionTemplateSchema(type=template.type, inputs_schema=template.inputs_schema)


@frozen
class StepTemplate:
    template_id: str
    name: str
    description: str


# The editor offers these as built-in steps, so they are in the step catalog although their status is hidden.
_BUILT_IN_STEP_TEMPLATE_IDS = frozenset(
    {
        "template-slack",
        "template-webhook",
        "template-posthog-capture",
        "template-posthog-update-person-properties",
        "template-posthog-group-identify",
        "template-posthog-set-variable",
    }
)

# Email, SMS and push have step types of their own, so they are not catalog steps.
_OWN_STEP_TYPE_TEMPLATE_IDS = frozenset({"template-email", "template-twilio", "template-native-push"})


def list_step_templates(team: Team) -> list[StepTemplate]:
    """The function templates a workflow step can use, as the editor's step picker offers them."""
    excluded_ids = set(hidden_gated_template_ids(team)) | _OWN_STEP_TYPE_TEMPLATE_IDS
    latest: dict[str, HogFunctionTemplate] = {}
    for template in (
        HogFunctionTemplate.objects.filter(type="destination")
        .exclude(status__in=["deprecated", "coming_soon"])
        .order_by("template_id", "-created_at")
    ):
        if template.template_id in latest or template.template_id in excluded_ids:
            continue
        if template.status == "hidden" and template.template_id not in _BUILT_IN_STEP_TEMPLATE_IDS:
            continue
        # The worker does not apply mappings, so a mapping destination with a secret input cannot run as a step.
        if template.mapping_templates and any(item.get("secret") for item in template.inputs_schema or []):
            continue
        latest[template.template_id] = template
    return [
        StepTemplate(template_id=template_id, name=template.name, description=template.description or "")
        for template_id, template in latest.items()
    ]
