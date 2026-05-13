from posthog.test.base import BaseTest

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.llm_analytics.backend.models.skills import LLMSkill, LLMSkillFile
from products.llm_analytics.backend.tools.manage_skills import (
    ArchiveLLMSkillTool,
    CreateLLMSkillTool,
    DuplicateLLMSkillTool,
    GetLLMSkillFileTool,
    GetLLMSkillTool,
    ListLLMSkillsTool,
    UpdateLLMSkillTool,
)

INVALID_SKILL_NAMES = [
    ("uppercase", "Bad_Name"),
    ("consecutive_hyphens", "foo--bar"),
    ("leading_hyphen", "-foo"),
    ("trailing_hyphen", "foo-"),
    ("reserved_new", "new"),
    ("too_long", "a" * 65),
    ("contains_space", "foo bar"),
    ("contains_underscore", "foo_bar"),
]


def _run(tool, **kwargs):
    return async_to_sync(tool._arun_impl)(**kwargs)


class TestListLLMSkillsTool(BaseTest):
    def _tool(self):
        return ListLLMSkillsTool(team=self.team, user=self.user)

    def test_returns_empty_message_when_no_skills(self):
        result, artifact = _run(self._tool())
        assert artifact is None
        assert "No skills found" in result

    def test_lists_existing_skills(self):
        LLMSkill.objects.create(
            team=self.team,
            name="investigate-metric",
            description="Find why a metric changed.",
            body="# Step 1...",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="audit-flags",
            description="Audit stale flags.",
            body="# Step 1...",
            version=1,
            is_latest=True,
            created_by=self.user,
        )

        result, _ = _run(self._tool())
        assert "investigate-metric" in result
        assert "audit-flags" in result
        assert "Found 2 skill" in result

    def test_search_filters_by_name(self):
        LLMSkill.objects.create(
            team=self.team,
            name="investigate-metric",
            description="A",
            body="x",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="audit-flags",
            description="B",
            body="x",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        result, _ = _run(self._tool(), search="audit")
        assert "audit-flags" in result
        assert "investigate-metric" not in result

    def test_only_returns_latest_versions(self):
        LLMSkill.objects.create(
            team=self.team,
            name="my-skill",
            description="d",
            body="v1 body",
            version=1,
            is_latest=False,
            created_by=self.user,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="my-skill",
            description="d",
            body="v2 body",
            version=2,
            is_latest=True,
            created_by=self.user,
        )

        result, _ = _run(self._tool())
        assert "v2" in result
        assert "Found 1 skill" in result


class TestGetLLMSkillTool(BaseTest):
    def _tool(self):
        return GetLLMSkillTool(team=self.team, user=self.user)

    def test_returns_not_found(self):
        result, _ = _run(self._tool(), name="missing")
        assert "not found" in result

    def test_returns_skill_body_and_metadata(self):
        skill = LLMSkill.objects.create(
            team=self.team,
            name="my-skill",
            description="A description.",
            body="# Heading\nDo this.",
            license="Apache-2.0",
            allowed_tools=["Bash"],
            version=3,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkillFile.objects.create(skill=skill, path="setup.sh", content="echo hi")

        result, _ = _run(self._tool(), name="my-skill")
        assert "my-skill" in result
        assert "v3" in result
        assert "A description." in result
        assert "Heading" in result
        assert "Apache-2.0" in result
        assert "Bash" in result
        assert "setup.sh" in result


class TestGetLLMSkillFileTool(BaseTest):
    def _tool(self):
        return GetLLMSkillFileTool(team=self.team, user=self.user)

    def test_returns_file_content(self):
        skill = LLMSkill.objects.create(
            team=self.team,
            name="s",
            description="d",
            body="b",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkillFile.objects.create(skill=skill, path="docs/notes.md", content="hello world")

        result, _ = _run(self._tool(), name="s", path="docs/notes.md")
        assert "hello world" in result

    def test_rejects_path_traversal(self):
        result, _ = _run(self._tool(), name="s", path="../etc/passwd")
        assert "Invalid file path" in result

    def test_file_not_found(self):
        LLMSkill.objects.create(
            team=self.team,
            name="s",
            description="d",
            body="b",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        result, _ = _run(self._tool(), name="s", path="missing.md")
        assert "not found" in result


class TestCreateLLMSkillTool(BaseTest):
    def _tool(self):
        return CreateLLMSkillTool(team=self.team, user=self.user)

    def test_creates_skill_at_v1(self):
        result, _ = _run(
            self._tool(),
            name="my-new-skill",
            description="Investigate metric drops.",
            body="# Steps\n1. ...",
        )
        assert "Created skill 'my-new-skill'" in result
        assert "v1" in result

        skill = LLMSkill.objects.get(team=self.team, name="my-new-skill")
        assert skill.version == 1
        assert skill.is_latest
        assert skill.body == "# Steps\n1. ..."
        assert skill.created_by == self.user

    @parameterized.expand(INVALID_SKILL_NAMES)
    def test_rejects_invalid_name(self, _case, invalid_name):
        # Validation must match the REST serializer so a name created via Max isn't later
        # rejected by other clients (and vice versa). See _validate_skill_name in manage_skills.py.
        result, _ = _run(
            self._tool(),
            name=invalid_name,
            description="d",
            body="b",
        )
        assert not LLMSkill.objects.filter(team=self.team, name=invalid_name).exists()
        # All the error messages share these phrases — the reserved-name and too-long branches
        # use slightly different wording but always include one of the two below.
        assert "reserved" in result or "lowercase letters" in result or "64 characters" in result

    def test_rejects_oversized_file(self):
        from products.llm_analytics.backend.api.skill_services import MAX_SKILL_FILE_BYTES
        from products.llm_analytics.backend.tools.manage_skills import CreateSkillFileInput

        oversized = "x" * (MAX_SKILL_FILE_BYTES + 1)
        result, _ = _run(
            self._tool(),
            name="too-big",
            description="d",
            body="# x",
            files=[CreateSkillFileInput(path="huge.txt", content=oversized)],
        )
        assert "size limit" in result
        assert not LLMSkill.objects.filter(team=self.team, name="too-big").exists()

    def test_rejects_duplicate_name(self):
        LLMSkill.objects.create(
            team=self.team,
            name="dup",
            description="d",
            body="b",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        result, _ = _run(
            self._tool(),
            name="dup",
            description="d2",
            body="b2",
        )
        assert "already exists" in result

    def test_creates_skill_with_files(self):
        from products.llm_analytics.backend.tools.manage_skills import CreateSkillFileInput

        result, _ = _run(
            self._tool(),
            name="with-files",
            description="d",
            body="# x",
            files=[CreateSkillFileInput(path="a.txt", content="aaa")],
        )
        assert "with-files" in result
        skill = LLMSkill.objects.get(team=self.team, name="with-files")
        files = list(skill.files.all())
        assert len(files) == 1
        assert files[0].path == "a.txt"
        assert files[0].content == "aaa"


class TestUpdateLLMSkillTool(BaseTest):
    def _tool(self):
        return UpdateLLMSkillTool(team=self.team, user=self.user)

    def _seed(self, body="# v1 body"):
        return LLMSkill.objects.create(
            team=self.team,
            name="iter-skill",
            description="d",
            body=body,
            version=1,
            is_latest=True,
            created_by=self.user,
        )

    def test_publishes_new_version_with_full_body(self):
        self._seed()
        result, _ = _run(
            self._tool(),
            name="iter-skill",
            base_version=1,
            body="# v2 body",
        )
        assert "Published v2" in result
        latest = LLMSkill.objects.get(team=self.team, name="iter-skill", is_latest=True)
        assert latest.version == 2
        assert latest.body == "# v2 body"

    def test_publishes_with_edits(self):
        self._seed(body="alpha\nbeta\ngamma")
        from products.llm_analytics.backend.tools.manage_skills import SkillBodyEditInput

        result, _ = _run(
            self._tool(),
            name="iter-skill",
            base_version=1,
            edits=[SkillBodyEditInput(old="beta", new="BETA")],
        )
        assert "Published v2" in result
        latest = LLMSkill.objects.get(team=self.team, name="iter-skill", is_latest=True)
        assert latest.body == "alpha\nBETA\ngamma"

    def test_rejects_body_and_edits_together(self):
        self._seed()
        from products.llm_analytics.backend.tools.manage_skills import SkillBodyEditInput

        result, _ = _run(
            self._tool(),
            name="iter-skill",
            base_version=1,
            body="x",
            edits=[SkillBodyEditInput(old="a", new="b")],
        )
        assert "either `body` or `edits`" in result

    def test_returns_conflict_when_base_version_mismatched(self):
        skill = self._seed()
        skill.is_latest = False
        skill.save()
        LLMSkill.objects.create(
            team=self.team,
            name="iter-skill",
            description="d",
            body="# v2",
            version=2,
            is_latest=True,
            created_by=self.user,
        )

        result, _ = _run(
            self._tool(),
            name="iter-skill",
            base_version=1,
            body="# stale",
        )
        assert "changed since you opened it" in result
        assert "Current version is 2" in result

    def test_not_found(self):
        result, _ = _run(self._tool(), name="nope", base_version=1, body="x")
        assert "not found" in result

    def test_rejects_oversized_body(self):
        from products.llm_analytics.backend.api.skill_services import MAX_SKILL_BODY_BYTES

        self._seed()
        oversized = "x" * (MAX_SKILL_BODY_BYTES + 1)
        result, _ = _run(
            self._tool(),
            name="iter-skill",
            base_version=1,
            body=oversized,
        )
        assert "size limit" in result
        # Nothing should have been published.
        latest = LLMSkill.objects.get(team=self.team, name="iter-skill", is_latest=True)
        assert latest.version == 1


class TestArchiveLLMSkillTool(BaseTest):
    def _tool(self):
        return ArchiveLLMSkillTool(team=self.team, user=self.user)

    def test_archives_skill(self):
        LLMSkill.objects.create(
            team=self.team,
            name="to-archive",
            description="d",
            body="b",
            version=1,
            is_latest=True,
            created_by=self.user,
        )

        result, _ = _run(self._tool(), name="to-archive")
        assert "Archived skill 'to-archive'" in result

        skill = LLMSkill.objects.get(team=self.team, name="to-archive", version=1)
        assert skill.deleted is True
        assert skill.is_latest is False

    def test_not_found(self):
        result, _ = _run(self._tool(), name="nope")
        assert "not found" in result


class TestDuplicateLLMSkillTool(BaseTest):
    def _tool(self):
        return DuplicateLLMSkillTool(team=self.team, user=self.user)

    def test_duplicates_skill(self):
        source = LLMSkill.objects.create(
            team=self.team,
            name="source",
            description="A description.",
            body="# Source body",
            license="MIT",
            allowed_tools=["Bash"],
            version=4,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkillFile.objects.create(skill=source, path="a.txt", content="abc")

        result, _ = _run(self._tool(), source_name="source", new_name="copy")
        assert "Duplicated 'source' to 'copy'" in result
        new_skill = LLMSkill.objects.get(team=self.team, name="copy")
        assert new_skill.version == 1
        assert new_skill.body == "# Source body"
        assert new_skill.license == "MIT"
        assert list(new_skill.files.values_list("path", flat=True)) == ["a.txt"]

    @parameterized.expand(INVALID_SKILL_NAMES)
    def test_rejects_invalid_new_name(self, _case, invalid_name):
        result, _ = _run(self._tool(), source_name="src", new_name=invalid_name)
        assert not LLMSkill.objects.filter(team=self.team, name=invalid_name).exists()
        assert "reserved" in result or "lowercase letters" in result or "64 characters" in result

    def test_conflict_when_destination_exists(self):
        LLMSkill.objects.create(
            team=self.team,
            name="src",
            description="d",
            body="b",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        LLMSkill.objects.create(
            team=self.team,
            name="dest",
            description="d",
            body="b",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        result, _ = _run(self._tool(), source_name="src", new_name="dest")
        assert "already exists" in result
