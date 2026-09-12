"""The manifest models that describe a built skill bundle."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

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
