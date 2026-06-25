import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SEEDED_BY,
    REVIEW_HOG_SKILL_CATEGORY,
    CanonicalSkill,
    discover_canonical_perspectives,
    sync_canonical_perspectives,
)
from products.review_hog.backend.reviewer.models.issues_review import PerspectiveType
from products.review_hog.backend.reviewer.skill_loader import (
    PERSPECTIVES,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    PerspectiveSkillNotFoundError,
    load_perspectives_for_run,
)
from products.skills.backend.models.skills import LLMSkill

_LOGIC = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness"


def test_registry_order_matches_perspective_type_enum() -> None:
    # combine_issues recovers a finding's perspective by ordinal (list(PerspectiveType)[pass - 1]),
    # so the registry order MUST equal the enum declaration order — a reorder would silently
    # mis-attribute every finding. Names must also carry the canonical prefix.
    assert tuple(p for p, _ in PERSPECTIVES) == tuple(PerspectiveType)
    assert all(name.startswith(REVIEW_HOG_PERSPECTIVE_PREFIX) for _, name in PERSPECTIVES)


def test_discover_finds_the_three_canonical_perspectives() -> None:
    # The on-disk SKILL.md set must parse and match the registry names exactly.
    discovered = {s.name for s in discover_canonical_perspectives()}
    assert discovered == {name for _, name in PERSPECTIVES}


def _changed_canonical(name: str) -> CanonicalSkill:
    return CanonicalSkill(
        name=name,
        description="changed description",
        body="# Changed body\n\nDifferent content.",
        allowed_tools=(),
        files=(),
        source_path=None,  # type: ignore[arg-type]
    )


class TestSyncCanonicalPerspectives(BaseTest):
    def test_creates_a_seeded_row_per_perspective(self) -> None:
        result = sync_canonical_perspectives(self.team)

        assert set(result.created_skill_names) == {name for _, name in PERSPECTIVES}
        rows = LLMSkill.objects.filter(team=self.team, deleted=False, is_latest=True)
        assert rows.count() == len(PERSPECTIVES)
        row = rows.get(name=_LOGIC)
        assert row.version == 1
        assert row.category == REVIEW_HOG_SKILL_CATEGORY
        assert row.metadata["seeded_by"] == REVIEW_HOG_SEEDED_BY
        assert row.metadata.get("canonical_hash")
        assert len(row.body) > 200  # the perspective focus moved out of jinja, not an empty stub

    def test_resync_is_idempotent(self) -> None:
        # Re-running with unchanged disk content must not bump versions or create rows.
        sync_canonical_perspectives(self.team)
        result = sync_canonical_perspectives(self.team)

        assert result.created_skill_names == ()
        assert result.updated_skill_names == ()
        assert LLMSkill.objects.filter(team=self.team, name=_LOGIC).count() == 1

    def test_updates_unedited_row_when_canonical_changes(self) -> None:
        sync_canonical_perspectives(self.team)
        with patch(
            "products.review_hog.backend.reviewer.lazy_seed.discover_canonical_perspectives",
            return_value=(_changed_canonical(_LOGIC),),
        ):
            result = sync_canonical_perspectives(self.team)

        assert result.updated_skill_names == (_LOGIC,)
        latest = LLMSkill.objects.get(team=self.team, name=_LOGIC, is_latest=True)
        assert latest.version == 2
        assert latest.body == "# Changed body\n\nDifferent content."

    def test_resync_retags_a_drifted_category(self) -> None:
        # The sync owns the category tag: a seeded row whose category drifted (e.g. the canonical
        # category was renamed) must be re-stamped, or it strands under no Skills-UI tab.
        sync_canonical_perspectives(self.team)
        LLMSkill.objects.filter(team=self.team, name=_LOGIC).update(category="stale_category")

        sync_canonical_perspectives(self.team)

        assert LLMSkill.objects.get(team=self.team, name=_LOGIC, is_latest=True).category == REVIEW_HOG_SKILL_CATEGORY

    def test_leaves_team_edited_row_alone(self) -> None:
        sync_canonical_perspectives(self.team)
        edited = LLMSkill.objects.get(team=self.team, name=_LOGIC, is_latest=True)
        edited.body = "the team rewrote this perspective"
        edited.save(update_fields=["body"])

        result = sync_canonical_perspectives(self.team)

        assert _LOGIC in result.diverged_skill_names
        assert _LOGIC not in result.updated_skill_names
        # No new version minted — the edit is preserved.
        assert LLMSkill.objects.get(team=self.team, name=_LOGIC, is_latest=True).version == 1

    def test_prune_tombstones_a_removed_canonical(self) -> None:
        sync_canonical_perspectives(self.team)
        # A canonical that no longer exists on disk (only logic-correctness remains) → its seeded row
        # is soft-deleted when pruning.
        with patch(
            "products.review_hog.backend.reviewer.lazy_seed.discover_canonical_perspectives",
            return_value=(_changed_canonical(_LOGIC),),
        ):
            result = sync_canonical_perspectives(self.team, prune=True)

        removed = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}contracts-security"
        assert removed in result.pruned_skill_names
        assert not LLMSkill.objects.filter(team=self.team, name=removed, deleted=False, is_latest=True).exists()


class TestLoadPerspectivesForRun(BaseTest):
    def test_resolves_pinned_versions_after_sync(self) -> None:
        sync_canonical_perspectives(self.team)

        loaded = load_perspectives_for_run(self.team.id)

        assert [lp.pass_number for lp in loaded] == [1, 2, 3]
        assert [lp.perspective for lp in loaded] == list(PerspectiveType)
        assert [lp.skill_name for lp in loaded] == [name for _, name in PERSPECTIVES]
        assert all(lp.version == 1 for lp in loaded)

    def test_pins_the_latest_version(self) -> None:
        sync_canonical_perspectives(self.team)
        with patch(
            "products.review_hog.backend.reviewer.lazy_seed.discover_canonical_perspectives",
            return_value=(_changed_canonical(_LOGIC),),
        ):
            sync_canonical_perspectives(self.team)

        loaded = {lp.skill_name: lp.version for lp in load_perspectives_for_run(self.team.id)}
        assert loaded[_LOGIC] == 2

    def test_raises_when_a_perspective_is_missing(self) -> None:
        # No sync ran, so the team has no perspective rows — a real setup error, not a soft miss.
        with pytest.raises(PerspectiveSkillNotFoundError):
            load_perspectives_for_run(self.team.id)


class TestSyncCommand(BaseTest):
    def test_team_id_seeds_the_team(self) -> None:
        call_command("sync_review_hog_skills", team_id=self.team.id)
        assert LLMSkill.objects.filter(team=self.team, name=_LOGIC, is_latest=True).exists()

    def test_dry_run_writes_nothing(self) -> None:
        call_command("sync_review_hog_skills", team_id=self.team.id, dry_run=True)
        assert not LLMSkill.objects.filter(team=self.team, name__startswith=REVIEW_HOG_PERSPECTIVE_PREFIX).exists()

    def test_team_id_and_all_teams_are_mutually_exclusive(self) -> None:
        with pytest.raises(CommandError):
            call_command("sync_review_hog_skills", team_id=self.team.id, all_teams=True)
