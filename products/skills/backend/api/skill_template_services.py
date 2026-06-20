"""Server-side rendering for templated skills.

A skill is a *template* when its `metadata.variables` declares one or more variables. The body and
bundled files carry `{{ variable }}` placeholders that get bound to user-supplied values when the
skill is instantiated (installed) into a team. Rendering is deliberately plain string substitution —
never a template engine — so a community-published template can't execute logic against tenant data.
"""

import re
from dataclasses import dataclass
from typing import Any

from .skill_services import MAX_SKILL_BODY_BYTES, MAX_SKILL_FILE_BYTES

# `{{ name }}` with optional surrounding whitespace. Names are Python-identifier-like.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
# Any residual `{{ ... }}` after substitution — catches placeholders whose declared name isn't a
# valid identifier (e.g. `{{ repo-name }}`), which the strict pattern above silently skips.
_LOOSE_PLACEHOLDER_RE = re.compile(r"\{\{.*?\}\}", re.DOTALL)


@dataclass(frozen=True)
class TemplateVariable:
    name: str
    prompt: str
    required: bool
    default: str


class TemplateRenderError(Exception):
    """Base class for failures while rendering a templated skill."""


class MissingTemplateVariableError(TemplateRenderError):
    """A required variable had no supplied value and no default."""

    def __init__(self, variable: TemplateVariable) -> None:
        self.variable = variable
        super().__init__(f"Missing required template variable '{variable.name}': {variable.prompt}")


class UnknownTemplatePlaceholderError(TemplateRenderError):
    """The body or a file referenced a `{{ placeholder }}` with no declared variable."""

    def __init__(self, placeholder: str) -> None:
        self.placeholder = placeholder
        super().__init__(f"Template references undeclared variable '{placeholder}'.")


class TemplateRenderTooLargeError(TemplateRenderError):
    """Rendering expanded the body or a file past the skill size limit."""

    def __init__(self, what: str, limit: int) -> None:
        super().__init__(f"Rendered {what} exceeds the {limit} byte size limit.")


class UnknownSuppliedVariableError(TemplateRenderError):
    """The caller supplied values for variables the template doesn't declare (likely a typo)."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(f"Unknown template variable(s) supplied: {', '.join(names)}.")


def parse_template_variables(metadata: dict[str, Any] | None) -> list[TemplateVariable]:
    """Read the `variables` schema out of a skill's frontmatter metadata.

    Tolerant of malformed entries from synced/external content: a non-dict metadata or anything
    without a usable string `name` is skipped rather than raising, so a bad row never breaks
    discovery or install.
    """
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get("variables")
    if not isinstance(raw, list):
        return []

    variables: list[TemplateVariable] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)
        default = item.get("default", "")
        variables.append(
            TemplateVariable(
                name=name,
                prompt=str(item.get("prompt", "")),
                # Default to required unless a default is supplied or `required` is explicitly false.
                required=bool(item.get("required", "default" not in item)),
                default=str(default) if default is not None else "",
            )
        )
    return variables


def is_template(metadata: dict[str, Any] | None) -> bool:
    return len(parse_template_variables(metadata)) > 0


def resolve_bindings(variables: list[TemplateVariable], supplied: dict[str, str] | None) -> dict[str, str]:
    """Build the final {name: value} map, applying defaults and enforcing required variables.

    An explicitly supplied value (including "") is used verbatim — only an absent key falls back to
    the default. Supplying a value for an undeclared variable is an error (likely a typo).
    """
    supplied = supplied or {}
    unknown = sorted(set(supplied) - {v.name for v in variables})
    if unknown:
        raise UnknownSuppliedVariableError(unknown)

    bindings: dict[str, str] = {}
    for variable in variables:
        if variable.name in supplied:
            value = supplied[variable.name]
            if value == "" and variable.required:
                raise MissingTemplateVariableError(variable)
        elif variable.default:
            value = variable.default
        elif variable.required:
            raise MissingTemplateVariableError(variable)
        else:
            value = ""
        bindings[variable.name] = value
    return bindings


def render_text(text: str, bindings: dict[str, str]) -> str:
    """Substitute every `{{ name }}` placeholder, erroring on any undeclared/unrenderable name.

    Validation runs against the source `text` only, before substitution — a supplied value may
    legitimately contain literal `{{ }}` and must not be re-interpreted as a placeholder.
    """
    for match in _LOOSE_PLACEHOLDER_RE.finditer(text):
        token = match.group(0)
        strict = _PLACEHOLDER_RE.fullmatch(token)
        if strict is None:
            # A `{{ ... }}` whose name the strict pattern can't match (e.g. a hyphen) — fail loudly
            # rather than install a skill with a dangling placeholder.
            raise UnknownTemplatePlaceholderError(token.strip())
        if strict.group(1) not in bindings:
            raise UnknownTemplatePlaceholderError(strict.group(1))

    return _PLACEHOLDER_RE.sub(lambda m: bindings[m.group(1)], text)


@dataclass(frozen=True)
class RenderedTemplate:
    body: str
    files: list[dict[str, str]]
    bindings: dict[str, str]


def render_template_skill(
    *,
    variables: list[TemplateVariable],
    body: str,
    files: list[dict[str, str]],
    supplied: dict[str, str] | None,
) -> RenderedTemplate:
    """Resolve user-supplied values against the declared variables and render body + files.

    `variables` is the already-parsed schema (see `parse_template_variables`) so the caller can
    parse once and reuse the result. Raises MissingTemplateVariableError when a required value is
    absent, UnknownTemplatePlaceholderError when a placeholder has no matching declared variable,
    and TemplateRenderTooLargeError when a user-supplied value expands output past the size limit.
    """
    bindings = resolve_bindings(variables, supplied)

    rendered_body = render_text(body, bindings)
    if len(rendered_body.encode("utf-8")) > MAX_SKILL_BODY_BYTES:
        raise TemplateRenderTooLargeError("skill body", MAX_SKILL_BODY_BYTES)

    rendered_files: list[dict[str, str]] = []
    for file in files:
        content = render_text(file["content"], bindings)
        if len(content.encode("utf-8")) > MAX_SKILL_FILE_BYTES:
            raise TemplateRenderTooLargeError(f"file '{file['path']}'", MAX_SKILL_FILE_BYTES)
        rendered_files.append({**file, "content": content})

    return RenderedTemplate(body=rendered_body, files=rendered_files, bindings=bindings)
