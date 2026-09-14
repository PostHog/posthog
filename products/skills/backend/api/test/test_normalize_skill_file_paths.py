from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from products.skills.backend.management.commands.normalize_skill_file_paths import plan_skill_paths
from products.skills.backend.marketplace.adapters import SkillBundle, build_skill_bundle
from products.skills.backend.models import LLMSkill, LLMSkillFile


class TestPlanSkillPaths(SimpleTestCase):
    @parameterized.expand(
        [
            ("separator", [("a", "refs\\guide.md")], [("a", "refs\\guide.md", "refs/guide.md")], [], []),
            ("already_canonical", [("a", "refs/guide.md")], [], [], []),
            (
                "collision_with_stored_path",
                [("a", "refs\\guide.md"), ("b", "refs/Guide.md")],
                [],
                [("refs\\guide.md", "refs/guide.md")],
                [],
            ),
            (
                "collision_between_rewrites",
                [("a", "refs\\guide.md"), ("b", "Refs\\Guide.md")],
                [("a", "refs\\guide.md", "refs/guide.md")],
                [("Refs\\Guide.md", "Refs/Guide.md")],
                [],
            ),
            ("trailing_slash", [("a", "refs/")], [], [], ["refs/"]),
            ("absolute", [("a", "/refs/guide.md")], [], [], ["/refs/guide.md"]),
        ]
    )
    def test_plan(self, _name, rows, rewrites, collisions, unfixable) -> None:
        plan = plan_skill_paths(rows)

        assert plan.rewrites == rewrites
        assert plan.collisions == collisions
        assert [path for path, _ in plan.unfixable] == unfixable


class TestNormalizeSkillFilePathsCommand(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="legacy-skill",
            description="A skill stored before the path validator.",
            body="# Legacy",
            created_by=self.user,
        )
        self.file = LLMSkillFile.objects.create(skill=self.skill, path="references\\guide.md", content="# Guide")

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("normalize_skill_file_paths", *args, stdout=out)
        return out.getvalue()

    def _bundle(self) -> SkillBundle:
        return build_skill_bundle(self.team, self.user, LLMSkill.objects.all(), content="full")

    def test_dry_run_reports_without_writing(self) -> None:
        output = self._run()

        self.file.refresh_from_db()
        assert self.file.path == "references\\guide.md"
        assert "references/guide.md" in output

    def test_apply_returns_the_skill_to_the_bundle(self) -> None:
        assert self._bundle().included == []

        self._run("--apply")

        self.file.refresh_from_db()
        assert self.file.path == "references/guide.md"
        assert self._bundle().included == ["legacy-skill"]

    def test_apply_leaves_the_skill_updated_at_alone(self) -> None:
        before = LLMSkill.objects.get(pk=self.skill.pk).updated_at

        self._run("--apply")

        assert LLMSkill.objects.get(pk=self.skill.pk).updated_at == before

    def test_team_id_scopes_the_rewrite(self) -> None:
        self._run("--apply", "--team-id", str(self.team.id + 1))

        self.file.refresh_from_db()
        assert self.file.path == "references\\guide.md"
