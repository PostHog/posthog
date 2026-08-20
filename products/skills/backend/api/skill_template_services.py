"""Server-side rendering for templated skills.

A skill is a *template* when its `metadata.variables` declares one or more variables. The body and
bundled files carry `{{ variable }}` placeholders that get bound to user-supplied values when the
skill is instantiated (installed) into a team. Rendering is deliberately plain string substitution —
never a template engine — so a community-published template can't execute logic against tenant data.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .skill_services import MAX_SKILL_BODY_BYTES, MAX_SKILL_FILE_BYTES

# `{{ name }}` with optional surrounding whitespace. Names are Python-identifier-like.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# A single supplied value, and all resolved bindings together. Bindings are persisted verbatim on
# the installed skill's metadata, so these bound that row independently of what the values render
# into — an unused variable never reaches the render-size checks below.
MAX_TEMPLATE_VARIABLE_BYTES = 10_000
MAX_TEMPLATE_BINDINGS_BYTES = 100_000

# Every rendered file and the body together. The per-file limit alone bounds nothing in aggregate:
# a template of 200 small files that each repeat a placeholder renders to 200 MB while every
# individual file stays under its own 1 MB cap.
MAX_RENDERED_SKILL_BYTES = 5_000_000


def _iter_placeholder_tokens(text: str) -> Iterator[str]:
    r"""Yield every `{{ ... }}` token, shortest-match, in one forward pass.

    Deliberately not a regex: `\{\{.*?\}\}` rescans the rest of the input for every unmatched `{{`,
    so a template carrying kilobytes of unclosed delimiters costs quadratic time and ties up an
    installer's worker. Both indices here only move forward, so a hostile template costs one pass.
    An unclosed trailing `{{` yields nothing and stays literal, matching the regex it replaces.
    """
    pos = 0
    while True:
        start = text.find("{{", pos)
        if start == -1:
            return
        end = text.find("}}", start + 2)
        if end == -1:
            return
        yield text[start : end + 2]
        pos = end + 2


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


class TemplateVariableTooLargeError(TemplateRenderError):
    """A supplied value, or all of them together, exceeded the template variable size limit."""

    def __init__(self, what: str, limit: int) -> None:
        super().__init__(f"Template variable {what} exceeds the {limit} byte size limit.")


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
    the default. Supplying a value for an undeclared variable is an error (likely a typo), and a
    value (or a whole binding set) past the size caps is rejected before anything is persisted.
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

    total = 0
    for name, value in bindings.items():
        size = len(value.encode("utf-8"))
        if size > MAX_TEMPLATE_VARIABLE_BYTES:
            raise TemplateVariableTooLargeError(f"'{name}'", MAX_TEMPLATE_VARIABLE_BYTES)
        total += size
    if total > MAX_TEMPLATE_BINDINGS_BYTES:
        raise TemplateVariableTooLargeError("values in total", MAX_TEMPLATE_BINDINGS_BYTES)
    return bindings


def _validate_and_project(text: str, bindings: dict[str, str], binding_sizes: dict[str, int]) -> int:
    """Check every placeholder is declared and return the exact rendered byte size, allocating nothing.

    Validation runs against the source `text` only — a supplied value may legitimately contain
    literal `{{ }}` and must not be re-interpreted as a placeholder. Sizing the output without
    building it is what lets the caller reject an amplifying template before it allocates: every
    token here is a strict placeholder, so summing the substitution deltas is exact.
    """
    projected = len(text.encode("utf-8"))
    for token in _iter_placeholder_tokens(text):
        strict = _PLACEHOLDER_RE.fullmatch(token)
        if strict is None:
            # A `{{ ... }}` whose name the strict pattern can't match (e.g. a hyphen) — fail loudly
            # rather than install a skill with a dangling placeholder.
            raise UnknownTemplatePlaceholderError(token.strip())
        name = strict.group(1)
        if name not in bindings:
            raise UnknownTemplatePlaceholderError(name)
        projected += binding_sizes[name] - len(token.encode("utf-8"))
    return projected


def _substitute(text: str, bindings: dict[str, str]) -> str:
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
    TemplateVariableTooLargeError when a supplied value is oversized, and TemplateRenderTooLargeError
    when a user-supplied value expands output past the size limit.
    """
    bindings = resolve_bindings(variables, supplied)
    binding_sizes = {name: len(value.encode("utf-8")) for name, value in bindings.items()}

    # Size the whole skill before substituting any of it, so an amplifying template is rejected
    # rather than allocated: peak memory here is the aggregate cap, not the sum of the per-file ones.
    total = _validate_and_project(body, bindings, binding_sizes)
    if total > MAX_SKILL_BODY_BYTES:
        raise TemplateRenderTooLargeError("skill body", MAX_SKILL_BODY_BYTES)
    for file in files:
        size = _validate_and_project(file["content"], bindings, binding_sizes)
        if size > MAX_SKILL_FILE_BYTES:
            raise TemplateRenderTooLargeError(f"file '{file['path']}'", MAX_SKILL_FILE_BYTES)
        total += size
        if total > MAX_RENDERED_SKILL_BYTES:
            raise TemplateRenderTooLargeError("skill", MAX_RENDERED_SKILL_BYTES)

    rendered_files = [{**file, "content": _substitute(file["content"], bindings)} for file in files]
    return RenderedTemplate(body=_substitute(body, bindings), files=rendered_files, bindings=bindings)
