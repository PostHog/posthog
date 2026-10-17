"""Which writes a template managed by code still takes.

Its content comes from a file that code uploads, so an edit made in PostHog would be lost on the next upload. The
policy names the actions it allows and refuses every other write, so a write action added later stays refused until
someone decides otherwise.
"""

from typing import Final, Protocol

from products.messaging.backend.facade.contracts import TemplateManagedBy, TemplateManagedByCode, TemplateWriteIntent

# Operating a template does not change its content, so the file has no opinion on these.
ALLOWED_ACTIONS: Final = frozenset({"upload", "send", "make_transactional"})


class OwnedTemplate(Protocol):
    @property
    def managed_by(self) -> str | None: ...

    @property
    def source_repository(self) -> str | None: ...

    @property
    def source_path(self) -> str | None: ...


def is_release(intent: TemplateWriteIntent) -> bool:
    """A PATCH whose only field is `managed_by: gui`."""
    return intent.patches_only("managed_by") and intent.payload["managed_by"] == TemplateManagedBy.GUI


def check_write(template: OwnedTemplate, intent: TemplateWriteIntent) -> None:
    """Raise TemplateManagedByCode unless the template takes this write. Check the row read under the write's lock
    too, because an upload can claim the template between an earlier read and the lock."""
    if template.managed_by != TemplateManagedBy.CODE:
        return
    if intent.action in ALLOWED_ACTIONS or is_release(intent):
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
