from __future__ import annotations

import tempfile
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.tasks.backend.services.local_skills import (
    BUILD_HASH_FILENAME,
    BUILT_SKILLS_RELATIVE_PATH,
    LocalSkillsCache,
    populate_skills_directory,
)

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
