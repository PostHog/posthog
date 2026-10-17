"""Which writes a template managed by code still takes.

Its content comes from a file that code uploads, so an edit made in PostHog would be lost on the next upload. The
policy names the actions it allows and refuses every other write, so a write action added later stays refused until
someone decides otherwise. An action on the template's file, such as a change request, needs a template managed by
code.
"""

from typing import Final, Protocol

from products.messaging.backend.facade.contracts import (
    TemplateChangeRefused,
    TemplateManagedBy,
    TemplateManagedByCode,
    TemplateWriteIntent,
)
from products.messaging.backend.services.template_change_prompt import shaped_path, shaped_repository

# These act on the template's file, so a template without one refuses them.
FILE_ACTIONS: Final = frozenset({"request_change"})
# Operating a template does not change its content, so the file has no opinion on these.
ALLOWED_ACTIONS: Final = frozenset({"upload", "send", "make_transactional", *FILE_ACTIONS})


class OwnedTemplate(Protocol):
    @property
    def managed_by(self) -> str | None: ...

    @property
    def source_repository(self) -> str | None: ...

    @property
    def source_path(self) -> str | None: ...


def patches_only(intent: TemplateWriteIntent, field: str) -> bool:
    """A PATCH whose only field is `field`. Matched on the whole body, so a form spread into a PATCH never matches."""
    return intent.action == "partial_update" and set(intent.payload.keys()) == {field}


def is_release(intent: TemplateWriteIntent) -> bool:
    """A PATCH whose only field is `managed_by: gui`."""
    return patches_only(intent, "managed_by") and intent.payload["managed_by"] == TemplateManagedBy.GUI


def check_write(template: OwnedTemplate, intent: TemplateWriteIntent) -> None:
    """Raise TemplateManagedByCode unless the template takes this write, and TemplateChangeRefused for an action on
    the file of a template without one. Check the row read under the write's lock too, because an upload can claim
    the template between an earlier read and the lock."""
    if template.managed_by != TemplateManagedBy.CODE:
        if intent.action in FILE_ACTIONS:
            raise not_managed_by_code()
        return
    if intent.action in ALLOWED_ACTIONS or is_release(intent):
        return
    raise TemplateManagedByCode(
        detail="This template is managed by code, so it can't be changed in PostHog.",
        why="Its content comes from a file in a repository. The next upload of that file replaces changes made here.",
        fix="When the repository is in your workspace, or you run outside PostHog Code and can check it out, edit "
        f"{_template_file(template)} there, as the template's "
        "`change_prompt_context` describes. It also says how the change goes live. Inside PostHog Code, such as "
        "PostHog AI or the Slack bot, share the template's link instead: on its page, the person clicks Edit with your "
        "agent, then Run with PostHog Code. Otherwise, ask PostHog Code to open a pull request with the change: call "
        "the `workflows-request-email-template-change` tool, or POST an `instruction` to this template's "
        "`request_change/` route. To edit the template in PostHog instead, stop managing it in code first: send a "
        "PATCH whose only field is `managed_by` set to `gui`.",
    )


def not_managed_by_code() -> TemplateChangeRefused:
    return TemplateChangeRefused(
        code="template_not_managed_by_code",
        detail="This template is not managed by code, so it has no file for PostHog Code to change.",
        why="Only a template uploaded from a file in a repository has a file to change.",
        fix="Edit the template in PostHog instead: in the template editor, or with a PATCH to the template.",
    )


def _template_file(template: OwnedTemplate) -> str:
    path, repository = shaped_path(template.source_path), shaped_repository(template.source_repository)
    if path and repository:
        return f"`{path}` in `{repository}`"
    if path:
        return f"`{path}`"
    if repository:
        return f"the template's file in `{repository}`"
    return "the template's file"
