import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from products.review_hog.backend.reviewer.constants import SINGLE_CHUNK_GATE_ADDITIONS
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRMetadata
from products.review_hog.backend.reviewer.models.perspective_selection import (
    ChunkPerspectiveSelection,
    PerspectiveSelection,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk
from products.review_hog.backend.reviewer.tools.prompt_helpers import format_pr_intent, load_template_and_schema
from products.review_hog.backend.reviewer.tools.split_pr_into_chunks import count_reviewable_additions

SELECTION_SYSTEM_PROMPT = """You are a code review planner deciding which review perspectives are worth running on each chunk of a GitHub PR.
Focus on:
- Judging relevance from what each chunk actually changes
- Skipping a perspective only when it is clearly irrelevant; keeping it whenever in doubt
- Following the specific output format requirements

IMPORTANT: Return ONLY valid JSON output without any markdown formatting or explanatory text."""


class SelectablePerspective(Protocol):
    """The two attributes selection needs — satisfied by both `LoadedPerspective` and its DTO."""

    skill_name: str
    description: str


_PerspectiveT = TypeVar("_PerspectiveT", bound=SelectablePerspective)


@dataclass
class ChunkSelectionDTO:
    chunk_id: int
    perspectives: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class PerspectiveSelectionDTO:
    """Dataclass twin of `PerspectiveSelection` for the Temporal boundary.

    Activity payloads stay dataclasses (the worker's data converter only handles pydantic models
    behind a deploy-dependent flag); the pydantic model remains the LLM/persistence shape.
    """

    chunks: list[ChunkSelectionDTO] = field(default_factory=list)

    @classmethod
    def from_model(cls, selection: PerspectiveSelection) -> "PerspectiveSelectionDTO":
        return cls(
            chunks=[
                ChunkSelectionDTO(chunk_id=c.chunk_id, perspectives=list(c.perspectives), reason=c.reason)
                for c in selection.chunks
            ]
        )


def prunable_perspectives(perspectives: Sequence[_PerspectiveT]) -> list[_PerspectiveT]:
    """The perspectives the selector may skip: only those whose description gives it something to judge.

    A perspective with an empty description (possible for custom skills) never enters the menu and is
    always kept — the selector cannot rule out a lens it cannot read.
    """
    return [p for p in perspectives if p.description.strip()]


def _format_perspective_menu(perspectives: Sequence[SelectablePerspective]) -> str:
    return "\n".join(f"- `{p.skill_name}` — {p.description.strip()}" for p in perspectives)


def generate_selection_prompt(
    pr_metadata: PRMetadata,
    chunks: Sequence[Chunk],
    pr_files: list[PRFile],
    perspectives: Sequence[SelectablePerspective],
) -> str:
    """Render the perspective-selection prompt: the prunable-perspective menu plus per-chunk context.

    Chunk context mirrors what's cheaply available: on the LLM-chunked path the chunker's own
    metadata (files + stats + type + key_changes) carries the signal without re-paying for the diff;
    on the deterministic single-chunk path no metadata exists, so the raw file changes go in —
    bounded small by the same `SINGLE_CHUNK_GATE_ADDITIONS` gate that chose that path.
    """
    prompt_template, output_schema = load_template_and_schema("perspective_selection")
    include_diffs = count_reviewable_additions(pr_files) <= SINGLE_CHUNK_GATE_ADDITIONS
    files_by_name = {f.filename: f for f in pr_files}
    chunk_payloads: list[dict[str, object]] = []
    for chunk in chunks:
        files: list[dict[str, object]] = []
        for info in chunk.files:
            pr_file = files_by_name.get(info.filename)
            if pr_file is None:
                files.append({"filename": info.filename})
                continue
            files.append(pr_file.model_dump(mode="json", exclude=None if include_diffs else {"changes"}))
        payload: dict[str, object] = {"chunk_id": chunk.chunk_id, "files": files}
        if chunk.chunk_type:
            payload["chunk_type"] = chunk.chunk_type
        if chunk.key_changes:
            payload["key_changes"] = chunk.key_changes
        chunk_payloads.append(payload)
    return prompt_template.render(
        PR_INTENT=format_pr_intent(pr_metadata),
        PERSPECTIVES=_format_perspective_menu(prunable_perspectives(perspectives)),
        CHUNKS=json.dumps(chunk_payloads, indent=2),
        INCLUDE_DIFFS=include_diffs,
        OUTPUT_SCHEMA=output_schema,
    )


def normalize_selection(
    perspectives: Sequence[SelectablePerspective],
    chunk_ids: Sequence[int],
    selection: PerspectiveSelection,
) -> PerspectiveSelection:
    """Rewrite the raw LLM selection into the exact plan the fan-out will run.

    Unknown skill names and unknown chunks are dropped, non-prunable perspectives are re-added to
    every chunk, duplicate chunk entries merge by union (the inclusion-biased merge), and a chunk the
    LLM didn't cover runs everything. Persisting the normalized form means the progress estimate and
    the skipped-perspective UI read the real plan, not the model's raw (possibly sloppy) output.
    """
    roster = [p.skill_name for p in perspectives]
    known = set(roster)
    always_kept = known - {p.skill_name for p in prunable_perspectives(perspectives)}
    chunk_id_set = set(chunk_ids)
    names_by_chunk: dict[int, set[str]] = {}
    reason_by_chunk: dict[int, str] = {}
    for entry in selection.chunks:
        if entry.chunk_id not in chunk_id_set:
            continue
        names_by_chunk.setdefault(entry.chunk_id, set()).update(name for name in entry.perspectives if name in known)
        reason_by_chunk.setdefault(entry.chunk_id, entry.reason)
    normalized: list[ChunkPerspectiveSelection] = []
    for chunk_id in chunk_ids:
        if chunk_id in names_by_chunk:
            names = names_by_chunk[chunk_id] | always_kept
            reason = reason_by_chunk.get(chunk_id, "")
        else:
            names, reason = known, ""
        normalized.append(
            ChunkPerspectiveSelection(
                chunk_id=chunk_id,
                perspectives=[name for name in roster if name in names],
                reason=reason,
            )
        )
    return PerspectiveSelection(chunks=normalized)


def apply_selection(
    perspectives: Sequence[_PerspectiveT],
    chunk_ids: Sequence[int],
    selection: PerspectiveSelectionDTO | None,
    *,
    blind_spot_runs: bool,
) -> list[tuple[_PerspectiveT, int]]:
    """Filter the (perspective × chunk) fan-out down to the selector's picks — fail-open everywhere.

    `None` (selection failed or was skipped) means the dense product, today's behavior. Otherwise,
    per chunk: the selected names (unknown ones dropped), plus every non-prunable perspective; a
    chunk the selection doesn't cover runs everything. Coverage invariant: a chunk must end with at
    least one review unit of any kind, so when no blind-spot pass will run (`blind_spot_runs=False`),
    a zero-selected chunk ignores the selection and runs all perspectives instead.
    """
    if selection is None:
        return [(p, c) for p in perspectives for c in chunk_ids]
    known = {p.skill_name for p in perspectives}
    always_kept = known - {p.skill_name for p in prunable_perspectives(perspectives)}
    chunk_id_set = set(chunk_ids)
    # Duplicate chunk entries union together — with an inclusion bias, more selected is the safe merge.
    selected_by_chunk: dict[int, set[str]] = {}
    for entry in selection.chunks:
        if entry.chunk_id not in chunk_id_set:
            continue
        selected_by_chunk.setdefault(entry.chunk_id, set()).update(name for name in entry.perspectives if name in known)
    run_names_by_chunk: dict[int, set[str]] = {}
    for chunk_id in chunk_ids:
        if chunk_id not in selected_by_chunk:
            run_names_by_chunk[chunk_id] = known
            continue
        run_names = selected_by_chunk[chunk_id] | always_kept
        if not run_names and not blind_spot_runs:
            run_names = known
        run_names_by_chunk[chunk_id] = run_names
    return [(p, c) for p in perspectives for c in chunk_ids if p.skill_name in run_names_by_chunk[c]]
