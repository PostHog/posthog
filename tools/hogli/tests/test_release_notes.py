from __future__ import annotations

import tomllib
from pathlib import Path

from parameterized import parameterized
from release_notes import DEFAULT_CHANGELOG, extract_section

CHANGELOG = """\
# Changelog

## 0.3.0

- newest

{heading}

- the body
- more body

## 0.1.0

- oldest
"""


class TestExtractSection:
    @parameterized.expand(
        [
            ("bare", "## 0.2.0"),
            ("linked", "## [0.2.0]"),
            ("dated", "## 0.2.0 - 2026-08-25"),
            ("linked_and_dated", "## [0.2.0] - 2026-08-25"),
        ]
    )
    def test_reads_body_for_heading_variant(self, _name: str, heading: str) -> None:
        assert extract_section(CHANGELOG.format(heading=heading), "0.2.0") == "- the body\n- more body"

    def test_stops_before_the_next_version(self) -> None:
        assert "oldest" not in extract_section(CHANGELOG.format(heading="## 0.2.0"), "0.2.0")

    def test_absent_version_reads_empty(self) -> None:
        assert extract_section(CHANGELOG.format(heading="## 0.2.0"), "9.9.9") == ""

    def test_version_is_not_matched_as_a_prefix(self) -> None:
        assert extract_section("## 0.2.10\n\n- ten\n", "0.2.1") == ""


def test_packaged_version_has_a_changelog_section() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert extract_section(DEFAULT_CHANGELOG.read_text(), version), (
        f"CHANGELOG.md has no '## {version}' section; publish-hogli.yml fails on a tag without one"
    )
