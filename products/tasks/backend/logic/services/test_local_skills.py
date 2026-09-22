from __future__ import annotations

import os
import shutil
import tempfile
import subprocess
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.tasks.backend.facade.agents import create_skill_isolation_environment
from products.tasks.backend.facade.api import list_sandbox_environments
from products.tasks.backend.logic.services.local_skills import (
    BUILD_HASH_FILENAME,
    BUILT_SKILLS_RELATIVE_PATH,
    LocalSkillsCache,
    bundled_skills_disabled,
    populate_skills_directory,
    snapshot_local_task_skills,
)
from products.tasks.backend.models import SandboxEnvironment

PATCH_TARGET = "products.posthog_ai.scripts.build_skills.SkillBuilder"


def _mock_builder(cache: LocalSkillsCache, *, produce_files: bool = True):
    """Return a mock SkillBuilder whose build_all populates dist_dir."""
    mock_cls = MagicMock()
    manifest = MagicMock()

    if produce_files:
        manifest.resources = [MagicMock()]

        def side_effect(*_args, **_kwargs):
            cache.dist_dir.mkdir(parents=True, exist_ok=True)
            (cache.dist_dir / "built.md").write_text("rendered")
            return manifest

        mock_cls.return_value.build_all.side_effect = side_effect
    else:
        manifest.resources = []
        mock_cls.return_value.build_all.return_value = manifest

    return mock_cls


class TestLocalSkills(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base_dir = Path(self._tmp.name)
        self._make_fake_repo()
        self.cache = LocalSkillsCache(self.base_dir)

    def test_skill_isolation_environment_disables_bundled_skills_and_stays_internal(self) -> None:
        environment_id = create_skill_isolation_environment(
            team_id=self.team.id, user_id=self.user.id, name="Eval skill isolation"
        )

        environment = SandboxEnvironment.objects.get(team_id=self.team.id, id=environment_id)
        assert bundled_skills_disabled(environment.environment_variables)
        assert environment.created_by_id == self.user.id
        assert list_sandbox_environments(self.team.id, self.user.id) == []

    def _make_fake_repo(self) -> None:
        skill_dir = self.base_dir / "products" / "alpha" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# skill body\n")

        scripts_dir = self.base_dir / "products" / "posthog_ai" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "build_skills.py").write_text("# stub renderer\n")

    def _seed_dist(self, filename: str = "placeholder.md") -> Path:
        self.cache.dist_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache.dist_dir / filename
        target.write_text("rendered content")
        return target

    def test_ensure_built_hash_hit_short_circuits(self) -> None:
        self._seed_dist()
        self.cache.hash_file.write_text(self.cache._compute_source_hash())

        with patch(PATCH_TARGET) as mock_cls:
            result = self.cache.ensure_built()

        self.assertEqual(result, self.cache.dist_dir)
        mock_cls.assert_not_called()

    def test_ensure_built_build_success_writes_hash(self) -> None:
        mock_cls = _mock_builder(self.cache)

        with patch(PATCH_TARGET, mock_cls):
            result = self.cache.ensure_built()

        mock_cls.return_value.build_all.assert_called_once()
        self.assertEqual(result, self.cache.dist_dir)
        self.assertEqual(self.cache.hash_file.read_text(), self.cache._compute_source_hash())

    def test_ensure_built_build_failure_with_populated_dist_pins_hash(self) -> None:
        self._seed_dist()
        expected_hash = self.cache._compute_source_hash()

        mock_cls = MagicMock()
        mock_cls.return_value.build_all.side_effect = RuntimeError("boom")

        with patch(PATCH_TARGET, mock_cls):
            result = self.cache.ensure_built()

        self.assertEqual(result, self.cache.dist_dir)
        self.assertEqual(self.cache.hash_file.read_text(), expected_hash)

    def test_ensure_built_build_failure_with_empty_dist_raises(self) -> None:
        mock_cls = MagicMock()
        mock_cls.return_value.build_all.side_effect = RuntimeError("boom")

        with patch(PATCH_TARGET, mock_cls):
            with self.assertRaisesRegex(RuntimeError, "hogli build:skills"):
                self.cache.ensure_built()

        self.assertFalse(self.cache.hash_file.exists())

    def test_strict_build_does_not_accept_or_pin_stale_skills(self) -> None:
        self._seed_dist()
        with patch(PATCH_TARGET) as mock_cls:
            mock_cls.return_value.build_all.side_effect = RuntimeError("broken template")
            with self.assertRaisesRegex(RuntimeError, "broken template"):
                self.cache.ensure_built(allow_stale=False)
        self.assertFalse(self.cache.hash_file.exists())

    def test_ensure_built_empty_manifest_raises(self) -> None:
        mock_cls = _mock_builder(self.cache, produce_files=False)

        with patch(PATCH_TARGET, mock_cls):
            with self.assertRaisesRegex(RuntimeError, "hogli build:skills"):
                self.cache.ensure_built()

    def test_hash_reacts_to_relevant_changes_only(self) -> None:
        skill_file = self.base_dir / "products" / "alpha" / "skills" / "my-skill" / "SKILL.md"
        builder_script = self.base_dir / "products" / "posthog_ai" / "scripts" / "build_skills.py"

        baseline = self.cache._compute_source_hash()

        original_skill = skill_file.read_text()
        skill_file.write_text(original_skill + "edit\n")
        self.assertNotEqual(self.cache._compute_source_hash(), baseline)
        skill_file.write_text(original_skill)
        self.assertEqual(self.cache._compute_source_hash(), baseline)

        original_builder = builder_script.read_text()
        builder_script.write_text(original_builder + "edit\n")
        self.assertNotEqual(self.cache._compute_source_hash(), baseline)
        builder_script.write_text(original_builder)
        self.assertEqual(self.cache._compute_source_hash(), baseline)

        helper = builder_script.parent / "schema_helpers.py"
        helper.write_text("schema helper")
        self.assertNotEqual(self.cache._compute_source_hash(), baseline)
        helper.unlink()

        pycache = skill_file.parent / "__pycache__"
        pycache.mkdir()
        (pycache / "x.pyc").write_bytes(b"\x00\x01")
        unrelated = self.base_dir / "products" / "alpha" / "other"
        unrelated.mkdir()
        (unrelated / "y.md").write_text("irrelevant")
        self.assertEqual(self.cache._compute_source_hash(), baseline)

    def test_build_invokes_skill_builder_correctly(self) -> None:
        mock_cls = _mock_builder(self.cache)

        with patch(PATCH_TARGET, mock_cls):
            self.cache.ensure_built()

        mock_cls.assert_called_once_with(
            self.base_dir,
            self.base_dir / "products",
            self.base_dir / "products" / "posthog_ai",
        )
        mock_cls.return_value.build_all.assert_called_once()

    def test_populate_skills_directory_copies_nested_layout(self) -> None:
        dist_dir = self.base_dir / BUILT_SKILLS_RELATIVE_PATH
        skill_refs = dist_dir / "my-skill" / "references"
        skill_refs.mkdir(parents=True)
        (skill_refs / "foo.md").write_text("ref body")

        pycache = dist_dir / "my-skill" / "__pycache__"
        pycache.mkdir()
        (pycache / "x.pyc").write_bytes(b"\x00")

        destination = self.base_dir / "mount"
        populate_skills_directory(destination, base_dir=self.base_dir)

        self.assertEqual(
            (destination / "my-skill" / "references" / "foo.md").read_text(),
            "ref body",
        )
        self.assertFalse((destination / "my-skill" / "__pycache__").exists())

    def test_populate_skills_directory_noop_when_dist_missing(self) -> None:
        destination = self.base_dir / "mount"
        populate_skills_directory(destination, base_dir=self.base_dir)
        self.assertTrue(not destination.exists() or not any(destination.iterdir()))

    def test_populate_skills_directory_noop_when_dist_empty(self) -> None:
        (self.base_dir / BUILT_SKILLS_RELATIVE_PATH).mkdir(parents=True)
        destination = self.base_dir / "mount"
        populate_skills_directory(destination, base_dir=self.base_dir)
        self.assertTrue(not destination.exists() or not any(destination.iterdir()))

    def test_module_constants_are_stable(self) -> None:
        self.assertEqual(BUILD_HASH_FILENAME, ".build-hash")
        self.assertEqual(BUILT_SKILLS_RELATIVE_PATH, Path("products/posthog_ai/dist/skills"))

    def test_task_snapshots_stay_fixed_and_do_not_share_desktop_build_output(self) -> None:
        source = self.base_dir / "products" / "alpha" / "skills" / "my-skill" / "SKILL.md"
        desktop_skill = self._seed_dist()
        first_snapshot = self.base_dir / "first-run"
        next_snapshot = self.base_dir / "next-run"
        with patch(PATCH_TARGET) as mock_cls:

            def render() -> MagicMock:
                output = mock_cls.call_args.args[2] / "dist" / "skills" / "my-skill"
                output.mkdir(parents=True, exist_ok=True)
                (output / "SKILL.md").write_text(source.read_text())
                return MagicMock(resources=[MagicMock()])

            mock_cls.return_value.build_all.side_effect = render
            snapshot_local_task_skills(first_snapshot, self.base_dir)
            source.write_text("new instructions")
            snapshot_local_task_skills(next_snapshot, self.base_dir)
            snapshot_local_task_skills(self.base_dir / "cached-run", self.base_dir)

            self.assertEqual(mock_cls.return_value.build_all.call_count, 2)
        self.assertEqual((first_snapshot / "my-skill" / "SKILL.md").read_text(), "# skill body\n")
        self.assertEqual((next_snapshot / "my-skill" / "SKILL.md").read_text(), "new instructions")
        self.assertEqual(desktop_skill.read_text(), "rendered content")
        self.assertFalse((next_snapshot / BUILD_HASH_FILENAME).exists())

    def test_installer_updates_all_agents_and_restores_only_its_overrides(self) -> None:
        script = Path(__file__).parents[2] / "sandbox" / "images" / "install-local-skills.sh"
        home = self.base_dir / "home"
        plugin = self.base_dir / "plugin"
        targets = [plugin / "skills", home / ".agents" / "skills", home / ".claude" / "skills"]
        source = self.base_dir / "local"
        for target in targets:
            (target / "shared" / "references").mkdir(parents=True)
            (target / "shared" / "SKILL.md").write_text("production")
            (target / "shared" / "references" / "old.md").write_text("old reference")
            (target / "unrelated").mkdir()
            (target / "unrelated" / "SKILL.md").write_text("keep")
        for name in ["shared", "local-only"]:
            (source / name).mkdir(parents=True)
            (source / name / "SKILL.md").write_text("checkout")

        def install(source_arg: str) -> None:
            subprocess.run(
                ["bash", str(script), source_arg, str(plugin)],
                env={**os.environ, "HOME": str(home)},
                check=True,
                capture_output=True,
            )

        install(str(source))
        for target in targets:
            self.assertEqual((target / "shared" / "SKILL.md").read_text(), "checkout")
            self.assertFalse((target / "shared" / "references" / "old.md").exists())
            (target / "unrelated" / "SKILL.md").write_text("user edit")

        shutil.rmtree(source / "local-only")
        (source / "shared" / "SKILL.md").write_text("updated checkout")
        install(str(source))
        for target in targets:
            self.assertFalse((target / "local-only").exists())
            self.assertEqual((target / "shared" / "SKILL.md").read_text(), "updated checkout")

        install("--restore")
        for target in targets:
            self.assertEqual((target / "shared" / "SKILL.md").read_text(), "production")
            self.assertTrue((target / "shared" / "references" / "old.md").exists())
            self.assertEqual((target / "unrelated" / "SKILL.md").read_text(), "user edit")
