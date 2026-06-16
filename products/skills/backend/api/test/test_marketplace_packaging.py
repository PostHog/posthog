import io
import json
import zipfile

import pytest

import yaml

from products.skills.backend.marketplace.git_smart_http import GitSynthesisError, synthesize_repo
from products.skills.backend.marketplace.packaging import (
    SkillExport,
    SkillFileExport,
    build_marketplace_tree,
    build_skill_tree,
    build_skill_zip,
    compute_plugin_version,
    render_frontmatter,
    render_skill_md,
    validate_for_export,
)

# These tests are intentionally DB-free — the packaging core takes plain dataclasses.


def _skill(**overrides) -> SkillExport:
    base: dict = {
        "name": "make-fractals",
        "description": "Render fractal images. Use when asked to visualize fractals.",
        "body": "# make-fractals\n\nDo the thing.\n",
        "version": 3,
        "license": "MIT",
        "compatibility": "",
        "allowed_tools": ["Bash", "Write"],
        "metadata": {"author": "posthog"},
        "files": [SkillFileExport(path="scripts/mandelbrot.py", content="print('hi')\n", content_type="text/x-python")],
    }
    base.update(overrides)
    return SkillExport(**base)


class TestFrontmatter:
    def test_frontmatter_is_valid_yaml_with_required_fields(self):
        block = render_frontmatter(_skill())
        assert block.startswith("---\n") and block.rstrip().endswith("---")
        parsed = yaml.safe_load(block.strip().strip("-"))
        assert parsed["name"] == "make-fractals"
        assert parsed["description"].startswith("Render fractal images")

    def test_allowed_tools_serialized_as_spec_space_string(self):
        parsed = yaml.safe_load(render_frontmatter(_skill()).strip().strip("-"))
        assert parsed["allowed-tools"] == "Bash Write"
        assert "allowed_tools" not in parsed

    def test_version_lives_under_metadata_not_top_level(self):
        parsed = yaml.safe_load(render_frontmatter(_skill(version=7)).strip().strip("-"))
        assert "version" not in parsed
        assert parsed["metadata"]["version"] == "7"
        assert parsed["metadata"]["author"] == "posthog"

    def test_stored_metadata_version_cannot_clobber_platform_version(self):
        parsed = yaml.safe_load(render_frontmatter(_skill(version=7, metadata={"version": "hax"})).strip().strip("-"))
        assert parsed["metadata"]["version"] == "7"

    def test_blank_optional_fields_are_omitted(self):
        parsed = yaml.safe_load(
            render_frontmatter(_skill(license="", compatibility="", allowed_tools=[])).strip().strip("-")
        )
        assert "license" not in parsed
        assert "compatibility" not in parsed
        assert "allowed-tools" not in parsed

    def test_render_skill_md_appends_body_after_frontmatter(self):
        out = render_skill_md(_skill())
        assert "---\n" in out
        assert out.rstrip().endswith("Do the thing.")


class TestExportValidation:
    def test_description_over_spec_limit_is_flagged(self):
        problems = validate_for_export(_skill(description="x" * 1025))
        assert any("1024" in p for p in problems)

    def test_empty_description_is_flagged(self):
        assert any("non-empty" in p for p in validate_for_export(_skill(description="   ")))

    def test_clean_skill_has_no_problems(self):
        assert validate_for_export(_skill()) == []


class TestSkillTreeAndZip:
    def test_skill_tree_contains_skill_md_and_bundled_files(self):
        tree = build_skill_tree(_skill())
        assert "SKILL.md" in tree
        assert tree["scripts/mandelbrot.py"] == "print('hi')\n"

    def test_zip_nests_under_directory_named_after_skill(self):
        with zipfile.ZipFile(io.BytesIO(build_skill_zip(_skill()))) as archive:
            names = set(archive.namelist())
        assert "make-fractals/SKILL.md" in names
        assert "make-fractals/scripts/mandelbrot.py" in names


class TestMarketplaceTree:
    def _tree(self, skills=None):
        return build_marketplace_tree(
            plugin_name="posthog-skills",
            plugin_description="Team skills",
            plugin_version="1.0.42",
            owner_name="PostHog",
            marketplace_name="posthog-skills-marketplace",
            skills=skills if skills is not None else [_skill()],
        )

    def test_marketplace_json_lists_the_plugin_with_version(self):
        manifest = json.loads(self._tree()[".claude-plugin/marketplace.json"])
        assert manifest["name"] == "posthog-skills-marketplace"
        assert manifest["owner"]["name"] == "PostHog"
        plugin = manifest["plugins"][0]
        assert plugin["name"] == "posthog-skills"
        assert plugin["source"] == "./plugins/posthog-skills"
        assert plugin["version"] == "1.0.42"

    def test_plugin_json_present_and_versioned(self):
        plugin = json.loads(self._tree()["plugins/posthog-skills/.claude-plugin/plugin.json"])
        assert plugin["name"] == "posthog-skills"
        assert plugin["version"] == "1.0.42"

    def test_skill_files_nested_under_plugin_skill_dir(self):
        tree = self._tree()
        assert "plugins/posthog-skills/skills/make-fractals/SKILL.md" in tree
        assert "plugins/posthog-skills/skills/make-fractals/scripts/mandelbrot.py" in tree

    def test_empty_team_still_produces_a_valid_marketplace(self):
        manifest = json.loads(self._tree(skills=[])[".claude-plugin/marketplace.json"])
        assert manifest["plugins"][0]["name"] == "posthog-skills"


class TestPluginVersion:
    def test_version_is_monotonic_with_change_time(self):
        assert compute_plugin_version(1700000000) < compute_plugin_version(1700009999)

    def test_same_change_time_yields_same_version(self):
        assert compute_plugin_version(1700000000) == compute_plugin_version(1700000000)


class TestGitTreeSafety:
    def _synth(self, files: dict[str, str]):
        return synthesize_repo(files, author="PostHog", message="m")

    def test_valid_nested_tree_synthesizes(self):
        assert self._synth({"SKILL.md": "a", "scripts/x.sh": "b"}).head_sha

    @pytest.mark.parametrize(
        "files",
        [
            {"a/": "x"},  # trailing slash → empty filename
            {"a//b.md": "x"},  # empty path segment
            {"scripts": "a", "scripts/x.sh": "b"},  # path used as both a file and a directory
            {"a.md": "x", "A.md": "y"},  # case-only collision (breaks clone on case-insensitive FS)
        ],
    )
    def test_corrupt_tree_is_rejected(self, files):
        # A bad path must raise rather than emit a corrupt tree that breaks the whole team's clone.
        with pytest.raises(GitSynthesisError):
            self._synth(files)
