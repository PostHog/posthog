from typing import Literal

from pydantic import BaseModel, Field

from products.reaper_hog.backend.facade.enums import ArtefactType, RootKind, ScoutName

EvidenceValue = str | int | float | bool | None


class Hit(BaseModel):
    kind: Literal["hit"] = "hit"
    scout: ScoutName
    root_kind: RootKind
    root: str
    files: list[str] = Field(default_factory=list)
    reference_count: int = 0
    line_count: int = 0
    decisive: bool = False
    summary: str
    evidence: dict[str, EvidenceValue] = Field(default_factory=dict)


class Note(BaseModel):
    kind: Literal["note"] = "note"
    author: str
    body: str


ArtefactContent = Hit | Note

_TYPE_BY_KIND: dict[str, ArtefactType] = {
    "hit": ArtefactType.HIT,
    "note": ArtefactType.NOTE,
}


def artefact_type_for(content: ArtefactContent) -> ArtefactType:
    return _TYPE_BY_KIND[content.kind]


def parse_artefact(type: str, raw: str) -> ArtefactContent:
    if type == ArtefactType.HIT:
        return Hit.model_validate_json(raw)
    if type == ArtefactType.NOTE:
        return Note.model_validate_json(raw)
    raise ValueError(f"Unknown artefact type {type!r}")
