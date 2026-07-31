from dataclasses import dataclass

import pytest

from products.review_hog.backend.reviewer.constants import SINGLE_CHUNK_GATE_ADDITIONS
from products.review_hog.backend.reviewer.models.github_meta import PRFile, PRFileUpdate, PRMetadata
from products.review_hog.backend.reviewer.models.perspective_selection import (
    ChunkPerspectiveSelection,
    PerspectiveSelection,
)
from products.review_hog.backend.reviewer.models.split_pr_into_chunks import Chunk, FileInfo
from products.review_hog.backend.reviewer.tools.select_perspectives import (
    ChunkSelectionDTO,
    PerspectiveSelectionDTO,
    apply_selection,
    generate_selection_prompt,
    normalize_selection,
)


@dataclass
class _Perspective:
    skill_name: str
    description: str = "judges things"


LOGIC = _Perspective("s-logic")
SEC = _Perspective("s-sec")
# Empty description → not prunable: the selector can't judge it, so it must always run.
NO_DESC = _Perspective("s-custom", description="  ")
ROSTER = [LOGIC, SEC, NO_DESC]
PRUNABLE_ONLY = [LOGIC, SEC]


def _units(
    selection: PerspectiveSelectionDTO | None,
    *,
    perspectives: list[_Perspective] = ROSTER,
    chunk_ids: tuple[int, ...] = (1, 2),
    blind_spot_runs: bool = True,
) -> list[tuple[str, int]]:
    return [
        (p.skill_name, c)
        for p, c in apply_selection(perspectives, list(chunk_ids), selection, blind_spot_runs=blind_spot_runs)
    ]


class TestApplySelection:
    def test_none_selection_runs_the_dense_product(self):
        # The fail-open contract: a failed/skipped selector must reproduce today's behavior exactly.
        assert _units(None) == [(p.skill_name, c) for p in ROSTER for c in (1, 2)]

    @pytest.mark.parametrize(
        "name,chunks,expected",
        [
            (
                "sparse_honored_and_undescribed_always_kept",
                [
                    ChunkSelectionDTO(chunk_id=1, perspectives=["s-logic"]),
                    ChunkSelectionDTO(chunk_id=2, perspectives=["s-sec"]),
                ],
                [("s-logic", 1), ("s-sec", 2), ("s-custom", 1), ("s-custom", 2)],
            ),
            (
                "unknown_names_dropped",
                [
                    ChunkSelectionDTO(chunk_id=1, perspectives=["nonexistent"]),
                    ChunkSelectionDTO(chunk_id=2, perspectives=["s-logic"]),
                ],
                [("s-logic", 2), ("s-custom", 1), ("s-custom", 2)],
            ),
            (
                "uncovered_chunk_runs_everything",
                [ChunkSelectionDTO(chunk_id=1, perspectives=["s-logic"])],
                [("s-logic", 1), ("s-logic", 2), ("s-sec", 2), ("s-custom", 1), ("s-custom", 2)],
            ),
            (
                "duplicate_chunk_entries_union",
                [
                    ChunkSelectionDTO(chunk_id=1, perspectives=["s-logic"]),
                    ChunkSelectionDTO(chunk_id=1, perspectives=["s-sec"]),
                    ChunkSelectionDTO(chunk_id=2, perspectives=["s-logic"]),
                ],
                [("s-logic", 1), ("s-logic", 2), ("s-sec", 1), ("s-custom", 1), ("s-custom", 2)],
            ),
        ],
    )
    def test_selection_is_normalized_defensively(self, name, chunks, expected):
        # A sloppy or hostile selection must never expand beyond the roster nor silently drop
        # coverage guarantees (always-kept lenses, uncovered chunks defaulting to everything).
        units = _units(PerspectiveSelectionDTO(chunks=chunks))
        assert sorted(units) == sorted(expected)

    def test_zero_selected_chunk_runs_nothing_when_blind_spot_covers_it(self):
        selection = PerspectiveSelectionDTO(
            chunks=[
                ChunkSelectionDTO(chunk_id=1, perspectives=["s-logic"]),
                ChunkSelectionDTO(chunk_id=2, perspectives=[]),
            ]
        )
        assert _units(selection, perspectives=PRUNABLE_ONLY) == [("s-logic", 1)]

    def test_zero_selected_chunk_runs_everything_without_a_blind_spot(self):
        # The coverage invariant: no chunk goes unreviewed. If no blind-spot pass will run, honoring
        # a zero selection would ship an unreviewed chunk — selection loses for that chunk instead.
        selection = PerspectiveSelectionDTO(
            chunks=[
                ChunkSelectionDTO(chunk_id=1, perspectives=["s-logic"]),
                ChunkSelectionDTO(chunk_id=2, perspectives=[]),
            ]
        )
        units = _units(selection, perspectives=PRUNABLE_ONLY, blind_spot_runs=False)
        assert sorted(units) == [("s-logic", 1), ("s-logic", 2), ("s-sec", 2)]


class TestNormalizeSelection:
    def test_normalizes_raw_llm_output_into_the_runnable_plan(self):
        # The persisted artefact drives the progress estimate and the skipped-perspective UI, so it
        # must be the plan the fan-out actually runs: unknown names/chunks gone, always-kept lenses
        # re-added, duplicate entries merged, uncovered chunks running everything.
        raw = PerspectiveSelection(
            chunks=[
                ChunkPerspectiveSelection(chunk_id=1, perspectives=["s-sec", "nonexistent"], reason="r1"),
                ChunkPerspectiveSelection(chunk_id=1, perspectives=["s-logic"], reason="dupe, ignored"),
                ChunkPerspectiveSelection(chunk_id=99, perspectives=["s-logic"], reason="unknown chunk"),
            ]
        )
        normalized = normalize_selection(ROSTER, [1, 2], raw)
        assert [c.chunk_id for c in normalized.chunks] == [1, 2]
        assert normalized.chunks[0].perspectives == ["s-logic", "s-sec", "s-custom"]  # roster order
        assert normalized.chunks[0].reason == "r1"
        assert normalized.chunks[1].perspectives == ["s-logic", "s-sec", "s-custom"]  # uncovered → all
        assert normalized.chunks[1].reason == ""

    def test_zero_selection_survives_normalization(self):
        # An intentionally empty pick must stay empty (modulo always-kept), not inflate to all-on.
        raw = PerspectiveSelection(chunks=[ChunkPerspectiveSelection(chunk_id=1, perspectives=[], reason="docs")])
        normalized = normalize_selection(PRUNABLE_ONLY, [1], raw)
        assert normalized.chunks[0].perspectives == []
        assert normalized.chunks[0].reason == "docs"


def _file(filename: str, additions: int) -> PRFile:
    return PRFile(
        filename=filename,
        status="modified",
        additions=additions,
        deletions=0,
        changes=[PRFileUpdate(type="addition", new_start_line=1, new_end_line=1, code="SENTINEL_DIFF_LINE")],
    )


class TestGenerateSelectionPrompt:
    @pytest.mark.parametrize(
        "total_additions,expect_diff",
        [
            (SINGLE_CHUNK_GATE_ADDITIONS, True),  # deterministic-path PRs get the raw changes
            (SINGLE_CHUNK_GATE_ADDITIONS + 1, False),  # chunked PRs get metadata only (cost gate)
        ],
    )
    def test_diffs_gated_by_pr_size(self, pr_metadata: PRMetadata, total_additions: int, expect_diff: bool):
        files = [_file("a.py", total_additions)]
        chunks = [Chunk(chunk_id=1, files=[FileInfo(filename="a.py")])]
        prompt = generate_selection_prompt(pr_metadata, chunks, files, ROSTER)
        assert ("SENTINEL_DIFF_LINE" in prompt) is expect_diff
        assert '"additions"' in prompt  # per-file stats carry the signal either way

    def test_menu_lists_only_prunable_perspectives(self, pr_metadata: PRMetadata):
        # An undescribed perspective must stay OFF the menu — offering it would let the selector
        # prune a lens it cannot actually judge.
        files = [_file("a.py", 10)]
        chunks = [Chunk(chunk_id=1, files=[FileInfo(filename="a.py")], chunk_type="tests", key_changes=["Adds x"])]
        prompt = generate_selection_prompt(pr_metadata, chunks, files, ROSTER)
        assert "`s-logic`" in prompt
        assert "`s-sec`" in prompt
        assert "s-custom" not in prompt
        assert pr_metadata.title in prompt
        assert '"chunk_type": "tests"' in prompt
        assert "<output_schema>" in prompt
