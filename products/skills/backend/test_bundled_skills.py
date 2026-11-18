from pathlib import Path
from tempfile import mkdtemp

from django.test import SimpleTestCase

from parameterized import parameterized

from products.skills.backend.bundled_skills import _declared_name, bundled_skill_names


class TestBundledSkills(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", "name: a-skill\ndescription: d", "a-skill"),
            # YAML semantics, the way the build reads the block. Raw text after `name:` would
            # record `a-skill # note`, and a store skill could then take `a-skill`.
            ("trailing_comment", "name: a-skill # note", "a-skill"),
            ("quoted", 'name: "a-skill"', "a-skill"),
            # Longer than the bounded first read, so the rest of the file has to be read.
            ("long_frontmatter", "description: " + "x" * 5000 + "\nname: a-skill", "a-skill"),
            ("no_name", "description: d", None),
            ("non_string_name", "name: 42", None),
        ]
    )
    def test_declared_name_reads_the_frontmatter_the_build_reads(self, _label, frontmatter, expected):
        entry_point = self._write(f"---\n{frontmatter}\n---\n# Body\n")

        assert _declared_name(entry_point) == expected

    def test_declared_name_is_none_without_frontmatter(self):
        assert _declared_name(self._write("# Body only\n")) is None

    def test_bundled_skill_names_holds_the_tree_and_the_omnibus_names(self):
        # A walk rooted at the wrong directory returns the omnibus names alone and silently stops
        # guarding every skill in the tree.
        names = bundled_skill_names()

        assert "signals-scout-logs" in names
        assert "instrument-logs" in names

    def _write(self, content: str) -> Path:
        entry_point = Path(mkdtemp()) / "SKILL.md"
        entry_point.write_text(content)
        return entry_point
