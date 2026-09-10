from typing import Literal

from pydantic import BaseModel, Field

from products.reaper_hog.backend.facade.enums import ArtefactType, Confidence, RootKind, ScoutName

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


class SearchRun(BaseModel):
    purpose: str = Field(description="What the search was meant to rule in or out")
    command: str = Field(description="The exact rg command, runnable from the repository root")
    hits: int = Field(description="Number of matching lines")


class Verdict(BaseModel):
    is_dead: bool = Field(description="True only when nothing reachable at runtime still depends on the root")
    confidence: Confidence = Field(
        description="high when every required search ran and every hit is inside the cluster"
    )
    files_to_delete: list[str] = Field(default_factory=list, description="Files that go away entirely")
    files_to_edit: list[str] = Field(default_factory=list, description="Files that lose a reference but stay")
    deletion_plan: str = Field(
        description="Markdown: what to remove where, mechanical enough to follow without judgment"
    )
    searches: list[SearchRun] = Field(default_factory=list)
    argumentation: str = Field(description="Labeled bullets: Checked, Found, Impact, each anchored with file:line")
    could_not_prove: list[str] = Field(default_factory=list, description="Open questions a human must settle")


class VerdictRecord(BaseModel):
    kind: Literal["verdict"] = "verdict"
    head_sha: str
    model: str | None = None
    verdict: Verdict


class Note(BaseModel):
    kind: Literal["note"] = "note"
    author: str
    body: str


ArtefactContent = Hit | VerdictRecord | Note

_TYPE_BY_KIND: dict[str, ArtefactType] = {
    "hit": ArtefactType.HIT,
    "verdict": ArtefactType.VERDICT,
    "note": ArtefactType.NOTE,
}


def artefact_type_for(content: ArtefactContent) -> ArtefactType:
    return _TYPE_BY_KIND[content.kind]


def parse_artefact(type: str, raw: str) -> ArtefactContent:
    if type == ArtefactType.HIT:
        return Hit.model_validate_json(raw)
    if type == ArtefactType.VERDICT:
        return VerdictRecord.model_validate_json(raw)
    if type == ArtefactType.NOTE:
        return Note.model_validate_json(raw)
    raise ValueError(f"Unknown artefact type {type!r}")
