import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models import User

from products.review_hog.backend.models import ReviewSkillConfig
from products.review_hog.backend.reviewer.lazy_seed import (
    REVIEW_HOG_SEEDED_BY,
    REVIEW_HOG_SKILL_CATEGORY,
    CanonicalSkill,
    discover_canonical_perspectives,
    sync_canonical_perspectives,
)
from products.review_hog.backend.reviewer.skill_loader import (
    CANONICAL_PERSPECTIVE_SKILL_NAMES,
    PERSPECTIVES,
    REVIEW_HOG_PERSPECTIVE_PREFIX,
    REVIEW_HOG_VALIDATION_SKILL_NAME,
    NoEnabledPerspectivesError,
    load_perspectives_for_run,
    register_missing_perspective_configs,
)
from products.review_hog.backend.temporal.activities import _sync_review_skills
from products.skills.backend.models.skills import LLMSkill

_LOGIC = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}logic-correctness"
_CUSTOM = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}custom-x"


def _author_perspective_skill(team, name: str) -> LLMSkill:
    return LLMSkill.objects.create(
        team=team, name=name, description="custom", body="x" * 250, version=1, is_latest=True
    )


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
        removed = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}contracts-security"
        updated_at_before = LLMSkill.objects.get(team=self.team, name=removed).updated_at
        # A canonical that no longer exists on disk (only logic-correctness remains) → its seeded row
        # is soft-deleted when pruning.
        with patch(
            "products.review_hog.backend.reviewer.lazy_seed.discover_canonical_perspectives",
            return_value=(_changed_canonical(_LOGIC),),
        ):
            result = sync_canonical_perspectives(self.team, prune=True)

        assert removed in result.pruned_skill_names
        assert not LLMSkill.objects.filter(team=self.team, name=removed, deleted=False, is_latest=True).exists()
        # The queryset tombstone bypasses auto_now — it must bump updated_at itself, or the
        # marketplace plugin version (Max(updated_at) over all rows) never advances and the cached
        # repo keeps serving the pruned skill.
        assert LLMSkill.objects.get(team=self.team, name=removed).updated_at > updated_at_before

    def test_resync_resurrects_an_archived_canonical(self) -> None:
        # Archiving a canonical via the general Skills UI must not stick: the config toggle is the
        # opt-out, so the next sync restores the skill instead of leaving reviews permanently broken.
        sync_canonical_perspectives(self.team)
        LLMSkill.objects.filter(team=self.team, name=_LOGIC).update(deleted=True, is_latest=False)

        result = sync_canonical_perspectives(self.team)

        assert _LOGIC in result.resurrected_skill_names
        revived = LLMSkill.objects.get(team=self.team, name=_LOGIC, deleted=False, is_latest=True)
        assert revived.version == 2
        assert revived.metadata["seeded_by"] == REVIEW_HOG_SEEDED_BY


class TestRegisterMissingPerspectiveConfigs(BaseTest):
    def test_seeds_only_canonicals_enabled_and_is_idempotent(self) -> None:
        # Seeding enables the 3 canonicals for the user and must NOT auto-create a config for a custom
        # perspective (customs are user-enabled only). Re-running must not duplicate rows.
        _author_perspective_skill(self.team, _CUSTOM)
        register_missing_perspective_configs(self.team.id, self.user.id)
        register_missing_perspective_configs(self.team.id, self.user.id)

        rows = ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id)
        assert {r.skill_name for r in rows} == set(CANONICAL_PERSPECTIVE_SKILL_NAMES)
        assert all(r.enabled for r in rows)

    def test_does_not_re_enable_a_disabled_canonical(self) -> None:
        # A user who switched a canonical off must not have it silently flipped back on by the next run.
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id, skill_name=_LOGIC).update(
            enabled=False
        )

        register_missing_perspective_configs(self.team.id, self.user.id)

        config = ReviewSkillConfig.objects.for_team(self.team.id).get(user_id=self.user.id, skill_name=_LOGIC)
        assert config.enabled is False


class TestLoadPerspectivesForRun(BaseTest):
    def test_cold_user_gets_the_canonicals_pinned(self) -> None:
        # A user who never toggled anything: seeding enables the 3 canonicals, the loader resolves them
        # sorted, pass_number a contiguous per-run index, version pinned to the synced latest.
        sync_canonical_perspectives(self.team)

        loaded = load_perspectives_for_run(self.team.id, self.user.id)

        assert [lp.skill_name for lp in loaded] == sorted(CANONICAL_PERSPECTIVE_SKILL_NAMES)
        assert [lp.pass_number for lp in loaded] == [1, 2, 3]
        assert all(lp.version == 1 for lp in loaded)

    def test_pins_the_latest_version(self) -> None:
        sync_canonical_perspectives(self.team)
        with patch(
            "products.review_hog.backend.reviewer.lazy_seed.discover_canonical_perspectives",
            return_value=(_changed_canonical(_LOGIC),),
        ):
            sync_canonical_perspectives(self.team)

        loaded = {lp.skill_name: lp.version for lp in load_perspectives_for_run(self.team.id, self.user.id)}
        assert loaded[_LOGIC] == 2

    def test_returns_only_enabled_and_reindexes_pass_number(self) -> None:
        # Disabling one perspective drops it from the run and re-indexes pass_number contiguously over
        # what's left — so finding ids never reference a perspective that didn't run.
        sync_canonical_perspectives(self.team)
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id, skill_name=_LOGIC).update(
            enabled=False
        )

        loaded = load_perspectives_for_run(self.team.id, self.user.id)

        assert [lp.skill_name for lp in loaded] == sorted(set(CANONICAL_PERSPECTIVE_SKILL_NAMES) - {_LOGIC})
        assert [lp.pass_number for lp in loaded] == [1, 2]

    def test_includes_an_enabled_custom_perspective(self) -> None:
        # The core "author a custom perspective and run it" path: an enabled custom prefixed skill is
        # loaded alongside the canonicals, with its own pass_number.
        sync_canonical_perspectives(self.team)
        _author_perspective_skill(self.team, _CUSTOM)
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name=_CUSTOM, enabled=True
        )

        loaded = load_perspectives_for_run(self.team.id, self.user.id)

        assert _CUSTOM in {lp.skill_name for lp in loaded}
        assert [lp.pass_number for lp in loaded] == [1, 2, 3, 4]

    def test_ignores_an_enabled_validator_row(self) -> None:
        # Perspectives and validators share one config table; an enabled validator row must not be
        # loaded as a review perspective (the loader's prefix filter scopes the query).
        sync_canonical_perspectives(self.team)
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name=REVIEW_HOG_VALIDATION_SKILL_NAME, enabled=True
        )

        loaded = load_perspectives_for_run(self.team.id, self.user.id)

        assert REVIEW_HOG_VALIDATION_SKILL_NAME not in {lp.skill_name for lp in loaded}
        assert [lp.skill_name for lp in loaded] == sorted(CANONICAL_PERSPECTIVE_SKILL_NAMES)

    def test_raises_when_user_has_zero_enabled(self) -> None:
        sync_canonical_perspectives(self.team)
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id).update(enabled=False)

        with pytest.raises(NoEnabledPerspectivesError):
            load_perspectives_for_run(self.team.id, self.user.id)

    def test_raises_when_no_enabled_perspective_has_a_live_skill(self) -> None:
        # Configs seed enabled, but no skills were synced — nothing resolves, surfaced loudly.
        with pytest.raises(NoEnabledPerspectivesError):
            load_perspectives_for_run(self.team.id, self.user.id)

    def test_skips_a_dead_perspective_leaving_its_slot_as_a_hole(self) -> None:
        # An archived custom must drop out of the run (not fail it) WITHOUT shifting the survivors'
        # pass numbers: (pass_number, chunk_id) is the same-head_sha resume key, so a reindex would
        # make a surviving perspective silently reuse the dead one's persisted review on resume.
        # Sorted enabled set: contracts(1), custom-x(2, dead), logic(3), performance(4).
        sync_canonical_perspectives(self.team)
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name=_CUSTOM, enabled=True
        )

        loaded = load_perspectives_for_run(self.team.id, self.user.id)

        assert [lp.skill_name for lp in loaded] == sorted(CANONICAL_PERSPECTIVE_SKILL_NAMES)
        assert [lp.pass_number for lp in loaded] == [1, 3, 4]

    def test_enablement_is_per_user(self) -> None:
        # Disabling a perspective for one user must not affect another user's run — enablement is per-USER.
        sync_canonical_perspectives(self.team)
        other = User.objects.create(email="other-perspectives@example.com")
        register_missing_perspective_configs(self.team.id, self.user.id)
        ReviewSkillConfig.objects.for_team(self.team.id).filter(user_id=self.user.id, skill_name=_LOGIC).update(
            enabled=False
        )

        mine = load_perspectives_for_run(self.team.id, self.user.id)
        theirs = load_perspectives_for_run(self.team.id, other.id)

        assert _LOGIC not in {lp.skill_name for lp in mine}
        assert _LOGIC in {lp.skill_name for lp in theirs}


class TestColdStartSync(BaseTest):
    def test_seeds_perspectives_and_prunes_disk_removed_canonicals(self) -> None:
        # The run path is the ONLY sync moment: it must both seed and prune (flipping prune back off
        # would leave a disk-removed canonical live on every team forever).
        _sync_review_skills(self.team.id)
        assert LLMSkill.objects.filter(team=self.team, name=_LOGIC, is_latest=True).exists()

        with patch(
            "products.review_hog.backend.reviewer.lazy_seed.discover_canonical_perspectives",
            return_value=(_changed_canonical(_LOGIC),),
        ):
            _sync_review_skills(self.team.id)

        removed = f"{REVIEW_HOG_PERSPECTIVE_PREFIX}contracts-security"
        assert not LLMSkill.objects.filter(team=self.team, name=removed, deleted=False, is_latest=True).exists()
