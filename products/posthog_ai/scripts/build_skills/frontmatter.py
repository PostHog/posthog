"""Parsing and validating the YAML frontmatter of a skill entry point."""

from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

_MAX_SKILL_DESCRIPTION_LENGTH = 1024

# A skill name becomes a directory under dist/skills and .agents/skills, so it must stay one path segment.
SKILL_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]*$"

# Name prefixes the signals scout harness and the PostHog Review pipeline seed into team skill rows
# and read through `skill-get`. The published bundle still ships these skills, so every plugin user
# would pay for their descriptions in the agent's skill listing unless they opt out of model
# invocation. Mirrors the discovery prefixes in `products/signals/backend/scout_harness/skill_loader.py`
# and `products/review_hog/backend/reviewer/skill_loader.py`; `review-hog-authoring` is user-facing.
RUNTIME_SKILL_PREFIXES = (
    "signals-scout-",
    "review-hog-perspective-",
    "review-hog-blind-spots-",
    "review-hog-validation-",
    "review-hog-resolution-",
)


class SkillFrontmatter(BaseModel):
    name: str = Field(pattern=SKILL_NAME_PATTERN)
    description: str = Field(max_length=_MAX_SKILL_DESCRIPTION_LENGTH)
    disable_model_invocation: bool = Field(default=False, alias="disable-model-invocation")

    @model_validator(mode="after")
    def _runtime_skills_stay_out_of_the_listing(self) -> SkillFrontmatter:
        if self.name.startswith(RUNTIME_SKILL_PREFIXES) and not self.disable_model_invocation:
            raise ValueError(
                f"'{self.name}' is a runtime-internal skill, so it must set "
                "`disable-model-invocation: true` to keep its description out of users' skill listings"
            )
        return self


def validate_frontmatter(text: str, source_label: str = "<unknown>") -> SkillFrontmatter:
    """Parse and validate frontmatter from rendered skill text.

    Raises ``ValueError`` if frontmatter is missing or invalid.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"Missing YAML frontmatter in {source_label}")
    raw_yaml = match.group(1)
    try:
        parsed = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter in {source_label}: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"Frontmatter must be a YAML mapping in {source_label}")
    try:
        return SkillFrontmatter.model_validate(parsed)
    except ValidationError as e:
        raise ValueError(f"Invalid frontmatter in {source_label}: {e}") from e


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract YAML frontmatter and body from a skill file.

    Returns (metadata_dict, body_without_frontmatter).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_yaml = match.group(1)
    body = text[match.end() :]
    parsed = yaml.safe_load(raw_yaml)
    if not isinstance(parsed, dict):
        return {}, text

    metadata: dict[str, str] = {str(k): str(v) for k, v in parsed.items()}
    return metadata, body
