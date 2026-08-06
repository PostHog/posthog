from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync

from posthog.models import Team

from products.skills.backend.models.skills import LLMSkill, LLMSkillFile
from products.skills.backend.tools.skills import (
    ArchiveLLMSkillTool,
    CreateLLMSkillTool,
    GetLLMSkillFileTool,
    GetLLMSkillTool,
    ListLLMSkillsTool,
    UpdateLLMSkillTool,
)

from ee.hogai.tool_errors import MaxToolFatalError


def _run(tool, **kwargs):
    return async_to_sync(tool._arun_impl)(**kwargs)


class TestListLLMSkillsTool(BaseTest):
    def _create_skill(self, name: str, description: str, body: str = "body") -> LLMSkill:
        return LLMSkill.objects.create(
            team=self.team,
            name=name,
            description=description,
            body=body,
            created_by=self.user,
        )

    def test_empty_team_returns_friendly_message(self):
        tool = ListLLMSkillsTool(team=self.team, user=self.user)
        result, artifact = _run(tool)
        assert "No shared skills" in result
        assert artifact is None

    def test_lists_skills_with_descriptions(self):
        self._create_skill("audit-error-tracking", "Audit recent error tracking issues.")
        self._create_skill("make-fractals", "Render fractal images.")
        tool = ListLLMSkillsTool(team=self.team, user=self.user)

        result, artifact = _run(tool)

        assert "audit-error-tracking" in result
        assert "Audit recent error tracking issues." in result
        assert "make-fractals" in result
        assert artifact is None

    def test_search_filters_by_name_and_description(self):
        self._create_skill("audit-error-tracking", "Audit recent error tracking issues.")
        self._create_skill("make-fractals", "Render fractal images.")

        tool = ListLLMSkillsTool(team=self.team, user=self.user)
        result, _ = _run(tool, search="fractal")

        assert "make-fractals" in result
        assert "audit-error-tracking" not in result

    def test_search_with_no_matches(self):
        self._create_skill("make-fractals", "Render fractal images.")
        tool = ListLLMSkillsTool(team=self.team, user=self.user)

        result, _ = _run(tool, search="nonexistent")

        assert "No shared skills matched" in result
        assert "nonexistent" in result

    def test_does_not_list_other_teams_skills(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        other_team_skill = self._create_skill("private-skill", "Other team's skill.")
        other_team_skill.team = other_team
        other_team_skill.save()

        tool = ListLLMSkillsTool(team=self.team, user=self.user)
        result, _ = _run(tool)

        assert "private-skill" not in result


class TestGetLLMSkillTool(BaseTest):
    def _create_skill_with_file(self) -> LLMSkill:
        skill = LLMSkill.objects.create(
            team=self.team,
            name="make-fractals",
            description="Render fractals.",
            body="# make-fractals\n\nFollow these steps:",
            license="MIT",
            compatibility="Python 3.10+",
            allowed_tools=["Bash", "Write"],
            metadata={"author": "posthog"},
            created_by=self.user,
        )
        LLMSkillFile.objects.create(
            skill=skill,
            path="scripts/mandelbrot.py",
            content="print('mandelbrot')",
            content_type="text/x-python",
        )
        return skill

    def test_returns_full_skill_with_file_manifest(self):
        self._create_skill_with_file()
        tool = GetLLMSkillTool(team=self.team, user=self.user)

        result, artifact = _run(tool, skill_name="make-fractals")

        assert artifact is None
        assert "make-fractals" in result
        assert "Render fractals." in result
        assert "License: MIT" in result
        assert "Compatibility: Python 3.10+" in result
        assert "Allowed tools: Bash, Write" in result
        assert "scripts/mandelbrot.py (text/x-python)" in result
        assert "Follow these steps:" in result
        # Body content is loaded but the file content is NOT — manifest only.
        assert "print('mandelbrot')" not in result

    def test_unknown_skill_returns_message_not_error(self):
        tool = GetLLMSkillTool(team=self.team, user=self.user)

        result, _ = _run(tool, skill_name="missing")

        assert "not found" in result
        assert "missing" in result


class TestGetLLMSkillFileTool(BaseTest):
    def _create_skill_with_file(self) -> LLMSkill:
        skill = LLMSkill.objects.create(
            team=self.team,
            name="make-fractals",
            description="Render fractals.",
            body="body",
            created_by=self.user,
        )
        LLMSkillFile.objects.create(
            skill=skill,
            path="scripts/mandelbrot.py",
            content="print('mandelbrot')",
            content_type="text/x-python",
        )
        return skill

    def test_returns_file_content(self):
        self._create_skill_with_file()
        tool = GetLLMSkillFileTool(team=self.team, user=self.user)

        result, _ = _run(tool, skill_name="make-fractals", file_path="scripts/mandelbrot.py")

        assert "scripts/mandelbrot.py" in result
        assert "text/x-python" in result
        assert "print('mandelbrot')" in result

    def test_unknown_file_returns_message(self):
        self._create_skill_with_file()
        tool = GetLLMSkillFileTool(team=self.team, user=self.user)

        result, _ = _run(tool, skill_name="make-fractals", file_path="scripts/missing.py")

        assert "not found" in result
        assert "scripts/missing.py" in result

    def test_rejects_path_traversal(self):
        tool = GetLLMSkillFileTool(team=self.team, user=self.user)

        result, _ = _run(tool, skill_name="any", file_path="../etc/passwd")

        assert "Invalid file path" in result


class TestCreateLLMSkillTool(BaseTest):
    def test_creates_skill_with_files(self):
        tool = CreateLLMSkillTool(team=self.team, user=self.user)

        result, _ = _run(
            tool,
            name="make-fractals",
            description="Render fractals.",
            body="# make-fractals\n\nFollow these steps.",
            files=[
                {"path": "scripts/mandelbrot.py", "content": "print('m')", "content_type": "text/x-python"},
            ],
        )

        assert "make-fractals" in result
        assert "v1" in result
        skill = LLMSkill.objects.get(team=self.team, name="make-fractals", is_latest=True)
        assert skill.description == "Render fractals."
        assert skill.files.count() == 1
        first_file = skill.files.first()
        assert first_file is not None
        assert first_file.path == "scripts/mandelbrot.py"

    def test_duplicate_name_raises_fatal(self):
        LLMSkill.objects.create(team=self.team, name="dup", description="d", body="b")

        tool = CreateLLMSkillTool(team=self.team, user=self.user)

        with self.assertRaisesRegex(MaxToolFatalError, "already exists"):
            _run(tool, name="dup", description="d2", body="b2")


class TestUpdateLLMSkillTool(BaseTest):
    def _create_skill(self) -> LLMSkill:
        return LLMSkill.objects.create(
            team=self.team,
            name="make-fractals",
            description="Render fractals.",
            body="# Step 1\nDo a thing.\n# Step 2\nDo another.",
            created_by=self.user,
        )

    def test_full_body_replacement(self):
        existing = self._create_skill()
        tool = UpdateLLMSkillTool(team=self.team, user=self.user)

        result, _ = _run(
            tool,
            skill_name="make-fractals",
            base_version=existing.version,
            body="# brand new\nbody",
        )

        assert "v2" in result
        latest = LLMSkill.objects.get(team=self.team, name="make-fractals", is_latest=True)
        assert latest.body == "# brand new\nbody"
        assert latest.version == 2

    def test_incremental_edits(self):
        existing = self._create_skill()
        tool = UpdateLLMSkillTool(team=self.team, user=self.user)

        result, _ = _run(
            tool,
            skill_name="make-fractals",
            base_version=existing.version,
            edits=[{"old": "Do a thing.", "new": "Do the better thing."}],
        )

        assert "v2" in result
        latest = LLMSkill.objects.get(team=self.team, name="make-fractals", is_latest=True)
        assert "Do the better thing." in latest.body
        assert "Do a thing." not in latest.body

    def test_version_conflict_raises(self):
        existing = self._create_skill()
        tool = UpdateLLMSkillTool(team=self.team, user=self.user)

        with self.assertRaisesRegex(MaxToolFatalError, "modified"):
            _run(
                tool,
                skill_name="make-fractals",
                base_version=existing.version + 5,
                body="new body",
            )

    def test_body_and_edits_are_mutually_exclusive(self):
        existing = self._create_skill()
        tool = UpdateLLMSkillTool(team=self.team, user=self.user)

        with self.assertRaisesRegex(MaxToolFatalError, r"either `body` or `edits`"):
            _run(
                tool,
                skill_name="make-fractals",
                base_version=existing.version,
                body="full",
                edits=[{"old": "a", "new": "b"}],
            )


class TestArchiveLLMSkillTool(BaseTest):
    def test_archives_all_versions(self):
        LLMSkill.objects.create(
            team=self.team, name="make-fractals", description="d", body="b1", version=1, is_latest=False
        )
        LLMSkill.objects.create(
            team=self.team, name="make-fractals", description="d", body="b2", version=2, is_latest=True
        )
        tool = ArchiveLLMSkillTool(team=self.team, user=self.user)

        result, _ = _run(tool, skill_name="make-fractals")

        assert "Archived skill 'make-fractals'" in result
        assert "2 version(s) hidden" in result
        assert LLMSkill.objects.filter(team=self.team, name="make-fractals", deleted=False).count() == 0

    def test_unknown_skill_raises_fatal(self):
        tool = ArchiveLLMSkillTool(team=self.team, user=self.user)

        with self.assertRaisesRegex(MaxToolFatalError, "missing"):
            _run(tool, skill_name="missing")
