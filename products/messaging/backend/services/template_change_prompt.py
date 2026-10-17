"""The prompt that asks a coding agent to change the file of a template managed by code.

The web page copies it, and agents read it from the API, so every caller hands the agent the same text.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol
from uuid import UUID

from posthog.utils import absolute_uri

from products.messaging.backend.facade.contracts import TemplateChangePrompt, TemplateManagedBy

LIQUID_MARKUP: Final = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
VARIABLE: Final = re.compile(r"(?<![\w.])variables\.([A-Za-z_][\w-]*)")
COMMIT_SHA: Final = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
SHORT_SHA_LENGTH: Final = 7

FILE_CONTRACT: Final = (
    "The file is the whole email. The subject is the first `<title>`. The inbox preview text is the `content` of "
    '`<meta name="preheader">`. Everything in the file is the HTML that PostHog sends.'
)
PERSONALIZATION: Final = (
    "Personalize only with `{{ variables.<name> }}`. The values come from the `data` the app passes to "
    "`posthog.emails.send`."
)


class PromptedTemplate(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def key(self) -> str | None: ...

    @property
    def managed_by(self) -> str | None: ...

    @property
    def content(self) -> dict[str, Any]: ...

    @property
    def source_repository(self) -> str | None: ...

    @property
    def source_path(self) -> str | None: ...

    @property
    def source_ref(self) -> str | None: ...


def change_prompt(team_id: int, template: PromptedTemplate) -> TemplateChangePrompt | None:
    if template.managed_by != TemplateManagedBy.CODE or not template.key:
        return None
    lines = [
        _identity(template, template.key),
        FILE_CONTRACT,
        _personalization(template.content),
        _how_it_goes_live(template.key),
        f"The template in PostHog: {_template_link(team_id, template.id)}",
    ]
    return TemplateChangePrompt(
        starter=_starter(template, template.key),
        context="\n".join(["About this file:", *(f"- {line}" for line in lines)]),
    )


def _template_link(team_id: int, template_id: UUID) -> str:
    return absolute_uri(f"/project/{team_id}/workflows/library/templates/{template_id}")


def _starter(template: PromptedTemplate, key: str) -> str:
    if template.source_path:
        return f"In `{template.source_path}`, change "
    return f"In the HTML file of the `{key}` email template, change "


def _identity(template: PromptedTemplate, key: str) -> str:
    if template.source_path:
        sentence = f"It is the PostHog email template with the key `{key}`"
    else:
        sentence = f"Find the HTML file that the app loads with `posthog.emails.templateFile()` for the key `{key}`"
    if template.source_repository:
        sentence += f", in the repository `{template.source_repository}`"
    if template.source_ref:
        sentence += f", last uploaded from {_ref(template.source_ref)}"
    return f"{sentence}."


def _ref(ref: str) -> str:
    if COMMIT_SHA.match(ref):
        return f"commit `{ref[:SHORT_SHA_LENGTH]}`"
    return f"`{ref}`"


def _personalization(content: Mapping[str, Any]) -> str:
    variables = _variables_in_order_of_first_use(_published_parts(content))
    if not variables:
        return PERSONALIZATION
    return f"{PERSONALIZATION} This file uses {_join([f'`{{{{ variables.{name} }}}}`' for name in variables])}."


def _published_parts(content: Mapping[str, Any]) -> list[str]:
    email = content.get("email") or {}
    return [part for part in (email.get(name) for name in ("subject", "preheader", "html")) if isinstance(part, str)]


def _variables_in_order_of_first_use(parts: Sequence[str]) -> list[str]:
    names = (name for part in parts for markup in LIQUID_MARKUP.findall(part) for name in VARIABLE.findall(markup))
    return list(dict.fromkeys(names))


def _join(items: Sequence[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _how_it_goes_live(key: str) -> str:
    return (
        "Do not upload the file by hand. If the app sends it with `posthog.emails.templateFile()`, the next send "
        f"uploads the changed file. If the app sends it by the key `{key}`, upload the file again after the change "
        f"(PUT /api/projects/@current/messaging_templates/by_key/{key}/ or the PostHog MCP upload tool)."
    )
