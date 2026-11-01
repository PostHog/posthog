import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final, Protocol
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.utils import absolute_uri

from products.messaging.backend.facade.contracts import TemplateChangePrompt, TemplateManagedBy

LIQUID_DELIMITERS: Final = (("{{", "}}"), ("{%", "%}"))
VARIABLE: Final = re.compile(r"(?<![\w.])variables\.([A-Za-z_][\w-]*)")
COMMIT_SHA: Final = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)
SOURCE_REPOSITORY: Final = re.compile(r"[\w.-]+(?:/[\w.-]+)+")
SOURCE_PATH: Final = re.compile(r"[\w.@+~,=()\[\]-]+(?:/[\w.@+~,=()\[\]-]+)*")
SOURCE_REF: Final = re.compile(r"[\w./-]+")
SHORT_SHA_LENGTH: Final = 7

FILE_CONTRACT: Final = (
    "If the app loads the file with `posthog.emails.templateFile()`, the file is the whole email: the subject is "
    'the first `<title>`, and the inbox preview text is the `content` of `<meta name="preheader">`. If the app '
    "uploads it by key, change the subject and preview text where its upload code sets them. PostHog sends the HTML "
    "as it is."
)
LOADED_OR_UPLOADED: Final = " The app loads it with `posthog.emails.templateFile()` or uploads it by that key."
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


@frozen
class PromptSource:
    repository: str | None
    path: str | None
    ref: str | None

    @classmethod
    def of(cls, template: PromptedTemplate) -> "PromptSource":
        return cls(
            repository=_unless_it_could_instruct_the_agent(template.source_repository, SOURCE_REPOSITORY),
            path=_inside_the_repository(_unless_it_could_instruct_the_agent(template.source_path, SOURCE_PATH)),
            ref=_unless_it_could_instruct_the_agent(template.source_ref, SOURCE_REF),
        )


def change_prompt(team_id: int, template: PromptedTemplate) -> TemplateChangePrompt | None:
    if template.managed_by != TemplateManagedBy.CODE or not template.key:
        return None
    source = PromptSource.of(template)
    variables = _variables_in_order_of_first_use(_published_parts(template.content))
    lines = [
        _identity(source, template.key),
        FILE_CONTRACT,
        _personalization(variables),
        _how_it_goes_live(template.key),
        f"The template in PostHog: {_template_link(team_id, template.id)}",
    ]
    return TemplateChangePrompt(
        starter=_starter(source, template.key),
        context="\n".join(["About this file:", *(f"- {line}" for line in lines)]),
        variables=tuple(variables),
    )


def _template_link(team_id: int, template_id: UUID) -> str:
    return absolute_uri(f"/project/{team_id}/workflows/library/templates/{template_id}")


def _unless_it_could_instruct_the_agent(value: str | None, shape: re.Pattern[str]) -> str | None:
    return value if value and shape.fullmatch(value) else None


def _inside_the_repository(path: str | None) -> str | None:
    if path is None:
        return None
    segments = path.split("/")
    return None if segments[0].startswith("~") or ".." in segments else path


def _starter(source: PromptSource, key: str) -> str:
    if source.path:
        return f"In `{source.path}`, change "
    return f"In the HTML file of the `{key}` email template, change "


def _identity(source: PromptSource, key: str) -> str:
    if source.path:
        sentence = f"`{source.path}` is the PostHog email template with the key `{key}`"
    else:
        sentence = f"Find the HTML file of the email template with the key `{key}`"
    if source.repository:
        sentence += f", in the repository `{source.repository}`"
    if source.ref:
        sentence += f", last uploaded from {_ref(source.ref)}"
    return f"{sentence}." if source.path else f"{sentence}.{LOADED_OR_UPLOADED}"


def _ref(ref: str) -> str:
    if COMMIT_SHA.match(ref):
        return f"commit `{ref[:SHORT_SHA_LENGTH]}`"
    return f"`{ref}`"


def _personalization(variables: Sequence[str]) -> str:
    if not variables:
        return PERSONALIZATION
    return f"{PERSONALIZATION} This file uses {_join([f'`{{{{ variables.{name} }}}}`' for name in variables])}."


def _published_parts(content: Mapping[str, Any]) -> list[str]:
    email = content.get("email") or {}
    return [part for part in (email.get(name) for name in ("subject", "preheader", "html")) if isinstance(part, str)]


def _variables_in_order_of_first_use(parts: Sequence[str]) -> list[str]:
    names = (
        name for part in parts for markup in _liquid_markups_in_one_pass(part) for name in VARIABLE.findall(markup)
    )
    return list(dict.fromkeys(names))


def _liquid_markups_in_one_pass(text: str) -> Iterator[str]:
    next_opener = {opener: text.find(opener) for opener, _ in LIQUID_DELIMITERS}
    while True:
        open_delimiters = [
            (at, opener, closer) for opener, closer in LIQUID_DELIMITERS if (at := next_opener[opener]) >= 0
        ]
        if not open_delimiters:
            return
        start, opener, closer = min(open_delimiters)
        end = text.find(closer, start + len(opener))
        if end == -1:
            next_opener[opener] = -1
            continue
        yield text[start : end + len(closer)]
        position = end + len(closer)
        for other, _ in LIQUID_DELIMITERS:
            if 0 <= next_opener[other] < position:
                next_opener[other] = text.find(other, position)


def _join(items: Sequence[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _how_it_goes_live(key: str) -> str:
    return (
        "Publish only after the change is reviewed and merged, because an upload replaces the published template at "
        "once. If the app sends the file with `posthog.emails.templateFile()`, its first send after the release "
        f"uploads the changed file. If the app sends it by the key `{key}`, upload the file again after the merge "
        f"(PUT /api/projects/@current/messaging_templates/by_key/{key}/ or the PostHog MCP upload tool)."
    )
