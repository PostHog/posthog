from typing import Final, Protocol

from products.messaging.backend.facade.contracts import TemplateManagedBy, TemplateManagedByCode, TemplateWriteIntent

CONTENT_NEUTRAL_ACTIONS: Final = frozenset({"upload", "send", "make_transactional"})
OPERATIONAL_FIELDS: Final = ("sensitive", "tags")


class OwnedTemplate(Protocol):
    @property
    def managed_by(self) -> str | None: ...

    @property
    def source_repository(self) -> str | None: ...

    @property
    def source_path(self) -> str | None: ...


def patches_only(intent: TemplateWriteIntent, field: str) -> bool:
    return intent.action == "partial_update" and set(intent.payload.keys()) == {field}


def is_release(intent: TemplateWriteIntent) -> bool:
    return patches_only(intent, "managed_by") and intent.payload["managed_by"] == TemplateManagedBy.GUI


def check_write(template: OwnedTemplate, intent: TemplateWriteIntent) -> None:
    if template.managed_by != TemplateManagedBy.CODE:
        return
    if (
        intent.action in CONTENT_NEUTRAL_ACTIONS
        or is_release(intent)
        or any(patches_only(intent, f) for f in OPERATIONAL_FIELDS)
    ):
        return
    raise TemplateManagedByCode(
        detail="This template is managed by code, so it can't be changed in PostHog.",
        why="Its content comes from a file in a repository. The next upload of that file replaces changes made here.",
        fix=f"Change {_template_file(template)} and upload it again. To edit the template in PostHog instead, stop "
        "managing it in code first: send a PATCH whose only field is `managed_by` set to `gui`.",
    )


def _template_file(template: OwnedTemplate) -> str:
    path, repository = template.source_path, template.source_repository
    if path and repository:
        return f"`{path}` in `{repository}`"
    if path:
        return f"`{path}`"
    if repository:
        return f"the template's file in `{repository}`"
    return "the template's file"
