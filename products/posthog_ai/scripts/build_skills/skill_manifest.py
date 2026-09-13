"""The manifest models that describe a built skill bundle."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, model_validator

MANIFEST_VERSION = "1.0.0"


class DiscoveredSkill(BaseModel):
    name: str
    source_file: Path
    product_dir: Path
    depth: int


class SkillFile(BaseModel):
    path: str
    content: str


class SkillResource(BaseModel):
    name: str
    description: str
    files: list[SkillFile]
    source: str


class SkillManifest(BaseModel):
    version: str = MANIFEST_VERSION
    resources: list[SkillResource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _reject_duplicate_names(self) -> SkillManifest:
        """Every resource writes to ``dist/skills/<name>``, so two resources sharing a
        name merge into one directory and the later entry point overwrites the earlier
        one. The lint deduplicates the source names, which the rendered frontmatter name
        can differ from, so the collision is only visible here.
        """
        seen: dict[str, str] = {}
        for resource in self.resources:
            if resource.name in seen:
                raise ValueError(f"Duplicate skill name '{resource.name}': {seen[resource.name]} and {resource.source}")
            seen[resource.name] = resource.source
        return self
