from __future__ import annotations

import sys
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

PATCH_TARGET = "products.tasks.backend.services.local_skills.subprocess.run"


def _ok(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


class TestLocalSkills(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base_dir = Path(self._tmp.name)
        self._make_fake_repo()
        self.cache = LocalSkillsCache(self.base_dir)

    def _make_fake_repo(self) -> None:
        """Lay out a minimal synthetic repo that LocalSkillsCache can hash.

        One product skill plus a stub build_skills.py so the hash covers
        both source classes the production code cares about.
        """
        skill_dir = self.base_dir / "products" / "alpha" / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# skill body\n")

        scripts_dir = self.base_dir / "products" / "posthog_ai" / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "build_skills.py").write_text("# stub renderer\n")

    def _seed_dist(self, filename: str = "placeholder.md") -> Path:
        """Pre-populate dist/skills/ as if a prior build had produced output."""
        self.cache.dist_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache.dist_dir / filename
        target.write_text("rendered content")
        return target

    def test_ensure_built_hash_hit_short_circuits(self) -> None:
        self._seed_dist()
        self.cache.hash_file.write_text(self.cache._compute_source_hash())

        with patch(PATCH_TARGET) as run_mock:
            result = self.cache.ensure_built()

        self.assertEqual(result, self.cache.dist_dir)
        run_mock.assert_not_called()

    def test_ensure_built_build_success_writes_hash(self) -> None:
        def fake_run(*args, **kwargs):
            self.cache.dist_dir.mkdir(parents=True, exist_ok=True)
            (self.cache.dist_dir / "built.md").write_text("rendered")
            return _ok()

        with patch(PATCH_TARGET, side_effect=fake_run) as run_mock:
            result = self.cache.ensure_built()

        run_mock.assert_called_once()
        self.assertEqual(result, self.cache.dist_dir)
        self.assertEqual(self.cache.hash_file.read_text(), self.cache._compute_source_hash())

    def test_ensure_built_build_failure_with_populated_dist_pins_hash(self) -> None:
        # Regression test for the "missing hash after fallback" bug: the
        # fallback branch must pin the hash so subsequent runs hit the cache
        # instead of re-invoking the failing subprocess every time.
        self._seed_dist()
        expected_hash = self.cache._compute_source_hash()

        with patch(PATCH_TARGET, return_value=_ok(returncode=1, stderr="boom")):
            result = self.cache.ensure_built()

        self.assertEqual(result, self.cache.dist_dir)
        self.assertEqual(self.cache.hash_file.read_text(), expected_hash)

    def test_ensure_built_build_failure_with_empty_dist_raises(self) -> None:
        with patch(PATCH_TARGET, return_value=_ok(returncode=1, stderr="boom")):
            with self.assertRaisesRegex(RuntimeError, "hogli build:skills"):
                self.cache.ensure_built()

        self.assertFalse(self.cache.hash_file.exists())

    def test_hash_reacts_to_relevant_changes_only(self) -> None:
        skill_file = self.base_dir / "products" / "alpha" / "skills" / "my-skill" / "SKILL.md"
        builder_script = self.base_dir / "products" / "posthog_ai" / "scripts" / "build_skills.py"

        baseline = self.cache._compute_source_hash()

        # Editing a skill file must bust the cache.
        original_skill = skill_file.read_text()
        skill_file.write_text(original_skill + "edit\n")
        self.assertNotEqual(self.cache._compute_source_hash(), baseline)
        skill_file.write_text(original_skill)
        self.assertEqual(self.cache._compute_source_hash(), baseline)

        # Editing the renderer script must bust the cache.
        original_builder = builder_script.read_text()
        builder_script.write_text(original_builder + "edit\n")
        self.assertNotEqual(self.cache._compute_source_hash(), baseline)
        builder_script.write_text(original_builder)
        self.assertEqual(self.cache._compute_source_hash(), baseline)

        # Irrelevant files must not bust the cache: ambient __pycache__
        # entries and files outside products/*/skills/ should be ignored
        # so git state and stale bytecode don't trigger needless rebuilds.
        pycache = skill_file.parent / "__pycache__"
        pycache.mkdir()
        (pycache / "x.pyc").write_bytes(b"\x00\x01")
        unrelated = self.base_dir / "products" / "alpha" / "other"
        unrelated.mkdir()
        (unrelated / "y.md").write_text("irrelevant")
        self.assertEqual(self.cache._compute_source_hash(), baseline)

    def test_build_subprocess_argv_is_stable(self) -> None:
        def fake_run(*args, **kwargs):
            self.cache.dist_dir.mkdir(parents=True, exist_ok=True)
            (self.cache.dist_dir / "built.md").write_text("x")
            return _ok()

        with patch(PATCH_TARGET, side_effect=fake_run) as run_mock:
            self.cache.ensure_built()

        args, kwargs = run_mock.call_args
        argv = args[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertTrue(argv[1].endswith("products/posthog_ai/scripts/build_skills.py"))
        self.assertEqual(kwargs["cwd"], str(self.base_dir))
        self.assertEqual(kwargs["timeout"], 300)
        self.assertEqual(kwargs["env"]["DJANGO_SETTINGS_MODULE"], "posthog.settings")

    def test_populate_skills_directory_copies_nested_layout(self) -> None:
        dist_dir = self.base_dir / BUILT_SKILLS_RELATIVE_PATH
        skill_refs = dist_dir / "my-skill" / "references"
        skill_refs.mkdir(parents=True)
        (skill_refs / "foo.md").write_text("ref body")

        # __pycache__ under the source must not be mirrored.
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
        with self.assertLogs("products.tasks.backend.services.local_skills", level="WARNING") as captured:
            populate_skills_directory(destination, base_dir=self.base_dir)

        self.assertTrue(not destination.exists() or not any(destination.iterdir()))
        self.assertTrue(any("No rendered skills" in msg for msg in captured.output))

    def test_populate_skills_directory_noop_when_dist_empty(self) -> None:
        (self.base_dir / BUILT_SKILLS_RELATIVE_PATH).mkdir(parents=True)
        destination = self.base_dir / "mount"
        with self.assertLogs("products.tasks.backend.services.local_skills", level="WARNING") as captured:
            populate_skills_directory(destination, base_dir=self.base_dir)

        self.assertTrue(not destination.exists() or not any(destination.iterdir()))
        self.assertTrue(any("No rendered skills" in msg for msg in captured.output))

    def test_module_constants_are_stable(self) -> None:
        # These are referenced from docker_sandbox, modal_sandbox, and the
        # eval harness conftest — a rename here should be explicit.
        self.assertEqual(BUILD_HASH_FILENAME, ".build-hash")
        self.assertEqual(BUILT_SKILLS_RELATIVE_PATH, Path("products/posthog_ai/dist/skills"))
