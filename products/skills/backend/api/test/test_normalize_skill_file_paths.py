import json
from io import StringIO
from uuid import UUID

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.test import SimpleTestCase

from parameterized import parameterized

from products.skills.backend.management.commands.normalize_skill_file_paths import plan_skill_paths
from products.skills.backend.marketplace.adapters import SkillBundle, build_skill_bundle, build_team_marketplace_tree
from products.skills.backend.marketplace.git_smart_http import synthesize_repo
from products.skills.backend.models import LLMSkill, LLMSkillFile

ROW_A = UUID("0198f000-0000-7000-8000-00000000000a")
ROW_B = UUID("0198f000-0000-7000-8000-00000000000b")


class TestPlanSkillPaths(SimpleTestCase):
    @parameterized.expand(
        [
            ("separator", [(ROW_A, "refs\\guide.md")], [(ROW_A, "refs\\guide.md", "refs/guide.md")], [], [], False),
            ("already_canonical", [(ROW_A, "refs/guide.md")], [], [], [], False),
            (
                "collision_with_stored_path",
                [(ROW_A, "refs\\guide.md"), (ROW_B, "refs/Guide.md")],
                [],
                [("refs\\guide.md", "refs/Guide.md")],
                [],
                False,
            ),
            (
                "collision_between_rewrites",
                [(ROW_A, "refs\\guide.md"), (ROW_B, "Refs\\Guide.md")],
                [],
                [("Refs\\Guide.md", "refs\\guide.md"), ("refs\\guide.md", "Refs\\Guide.md")],
                [],
                False,
            ),
            ("trailing_slash", [(ROW_A, "refs/")], [], [], ["refs/"], False),
            ("absolute", [(ROW_A, "/refs/guide.md")], [], [], ["/refs/guide.md"], False),
            (
                "rewrite_would_shadow_a_stored_file",
                [(ROW_A, "assets"), (ROW_B, "assets\\logo.png")],
                [],
                [],
                [],
                True,
            ),
            ("rewrite_would_shadow_the_generated_sidecar", [(ROW_A, "Agents\\OpenAI.yaml")], [], [], [], True),
        ]
    )
    def test_plan(self, _name, rows, rewrites, collisions, unfixable, unsafe) -> None:
        plan = plan_skill_paths(rows)

        assert plan.rewrites == rewrites
        assert plan.collisions == collisions
        assert [path for path, _ in plan.unfixable] == unfixable
        assert plan.unsafe == unsafe

    def test_plan_does_not_depend_on_row_order(self) -> None:
        rows = [(ROW_A, "refs\\guide.md"), (ROW_B, "Refs\\Guide.md")]

        assert plan_skill_paths(rows) == plan_skill_paths(list(reversed(rows)))


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

    def _published_version_millis(self) -> int:
        marketplace = build_team_marketplace_tree(self.team)[".claude-plugin/marketplace.json"]
        return int(json.loads(marketplace)["plugins"][0]["version"].rsplit(".", 1)[1])

    def test_dry_run_reports_without_writing(self) -> None:
        output = self._run()

        self.file.refresh_from_db()
        assert self.file.path == "references\\guide.md"
        assert "references/guide.md" in output
        assert f"team_id={self.team.id}" in output
        assert "name='legacy-skill'" in output

    def test_apply_returns_the_skill_to_the_bundle(self) -> None:
        assert self._bundle().included == []

        self._run("--apply")

        self.file.refresh_from_db()
        assert self.file.path == "references/guide.md"
        assert self._bundle().included == ["legacy-skill"]

    def test_apply_advances_the_published_marketplace_version(self) -> None:
        before = self._published_version_millis()

        self._run("--apply")

        assert self._published_version_millis() > before

    def test_dry_run_leaves_the_published_marketplace_version_alone(self) -> None:
        before = self._published_version_millis()

        self._run()

        assert self._published_version_millis() == before

    def test_team_id_scopes_the_rewrite(self) -> None:
        self._run("--apply", "--team-id", str(self.team.id + 1))

        self.file.refresh_from_db()
        assert self.file.path == "references\\guide.md"

    def test_apply_leaves_a_skill_whose_rewrite_would_break_the_clone(self) -> None:
        shadowed = LLMSkill.objects.create(
            team=self.team,
            name="shadowed-skill",
            description="A skill whose rewrite would shadow a stored file.",
            body="# Shadowed",
            created_by=self.user,
        )
        LLMSkillFile.objects.create(skill=shadowed, path="assets", content="not a directory")
        logo = LLMSkillFile.objects.create(skill=shadowed, path="assets\\logo.png", content="png")

        self._run("--apply")

        logo.refresh_from_db()
        assert logo.path == "assets\\logo.png"
        synthesize_repo(build_team_marketplace_tree(self.team), author="a <a@example.com>", message="m")
