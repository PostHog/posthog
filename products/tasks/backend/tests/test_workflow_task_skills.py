from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.logic.services.workflow_task_skills import (
    MANIFEST_DESCRIPTION_MAX_CHARS,
    MAX_ATTACHED_SKILLS,
    AttachedSkill,
    render_skills_manifest,
    select_skill_names,
)


def _skill(name: str, version: int = 1, description: str = "Does a thing.") -> AttachedSkill:
    return AttachedSkill(name=name, version=version, description=description)


class TestSelectSkillNames(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", [], []),
            ("order_preserved", ["beta", "alpha"], ["beta", "alpha"]),
            ("duplicates_collapse_to_first_position", ["beta", "alpha", "beta"], ["beta", "alpha"]),
        ]
    )
    def test_selection_shapes(self, _name: str, names: list[str] | None, expected: list[str]) -> None:
        self.assertEqual(select_skill_names(names), expected)

    def test_selection_is_capped(self) -> None:
        names = [f"skill-{index}" for index in range(MAX_ATTACHED_SKILLS + 5)]

        selected = select_skill_names(names)

        self.assertEqual(len(selected), MAX_ATTACHED_SKILLS)
        self.assertEqual(selected, names[:MAX_ATTACHED_SKILLS])


class TestRenderSkillsManifest(SimpleTestCase):
    def test_no_skills_renders_nothing(self) -> None:
        self.assertEqual(render_skills_manifest([]), "")

    def test_each_skill_gets_one_line_with_its_pinned_version(self) -> None:
        manifest = render_skills_manifest(
            [_skill("error-triage", version=4, description="Triage a production error spike.")]
        )

        self.assertIn("- `error-triage` (v4): Triage a production error spike.", manifest)

    def test_skills_keep_the_order_they_were_attached_in(self) -> None:
        manifest = render_skills_manifest([_skill("beta"), _skill("alpha")])

        self.assertLess(manifest.index("`beta`"), manifest.index("`alpha`"))

    def test_the_agent_is_told_to_fetch_a_body_over_mcp(self) -> None:
        manifest = render_skills_manifest([_skill("error-triage", version=4)])

        # Single-exec mode is the only shape the task sandbox's PostHog MCP accepts.
        self.assertIn("call skill-get", manifest)
        self.assertIn("body_next_offset", manifest)

    @parameterized.expand(
        [
            ("newline", "First line.\nSecond line."),
            ("carriage_return", "First line.\r\nSecond line."),
            ("tab", "First line.\tSecond line."),
        ]
    )
    def test_a_description_cannot_break_out_of_its_line(self, _name: str, description: str) -> None:
        # One line per skill is what tells the model where a name ends. A description
        # carrying a newline would make the tail read as another skill's name.
        manifest = render_skills_manifest([_skill("error-triage", description=description), _skill("db-runbook")])

        lines = [line for line in manifest.splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 2)
        self.assertIn("First line. Second line.", lines[0])

    @parameterized.expand(
        [
            ("newline", "error\ntriage", "`error triage`"),
            ("backtick", "error`triage", "`error\\`triage`"),
        ]
    )
    def test_a_name_cannot_break_out_of_its_line(self, _name: str, skill_name: str, expected: str) -> None:
        manifest = render_skills_manifest([_skill(skill_name), _skill("db-runbook")])

        lines = [line for line in manifest.splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 2)
        self.assertIn(expected, lines[0])

    def test_a_long_description_is_clamped(self) -> None:
        manifest = render_skills_manifest([_skill("error-triage", description="x" * 900)])

        (line,) = [line for line in manifest.splitlines() if line.startswith("- ")]
        self.assertIn("x" * MANIFEST_DESCRIPTION_MAX_CHARS, line)
        self.assertNotIn("x" * (MANIFEST_DESCRIPTION_MAX_CHARS + 1), line)

    @parameterized.expand([("empty", ""), ("whitespace_only", "   \n  ")])
    def test_a_skill_without_a_description_has_no_dangling_colon(self, _name: str, description: str) -> None:
        manifest = render_skills_manifest([_skill("error-triage", version=2, description=description)])

        (line,) = [line for line in manifest.splitlines() if line.startswith("- ")]
        self.assertEqual(line, "- `error-triage` (v2)")
