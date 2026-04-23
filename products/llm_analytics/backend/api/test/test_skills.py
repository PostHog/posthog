from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from ...models.skills import LLMSkill, LLMSkillFile
from ..skills import LLMSkillViewSet


@patch("products.llm_analytics.backend.api.skills.posthoganalytics.feature_enabled", return_value=True)
class TestLLMSkillAPI(APIBaseTest):
    def _url(self, path: str = "") -> str:
        return f"/api/environments/{self.team.id}/llm_skills/{path}"

    def create_skill(
        self,
        *,
        name: str = "my-skill",
        description: str = "A test skill",
        body: str = "# Test\nDo the thing.",
        version: int = 1,
        is_latest: bool = True,
        deleted: bool = False,
        license: str = "",
        compatibility: str = "",
        allowed_tools: list | None = None,
        metadata: dict | None = None,
    ) -> LLMSkill:
        return LLMSkill.objects.create(
            team=self.team,
            name=name,
            description=description,
            body=body,
            version=version,
            is_latest=is_latest,
            deleted=deleted,
            license=license,
            compatibility=compatibility,
            allowed_tools=allowed_tools or [],
            metadata=metadata or {},
            created_by=self.user,
        )

    # --- Create ---

    def test_create_skill_succeeds(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "my-skill",
                "description": "Extract PDF text and tables.",
                "body": "# PDF Processing\n\nUse pdfplumber.",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "my-skill"
        assert data["description"] == "Extract PDF text and tables."
        assert data["body"] == "# PDF Processing\n\nUse pdfplumber."
        assert data["version"] == 1
        assert data["is_latest"] is True
        assert data["latest_version"] == 1
        assert data["version_count"] == 1

    def test_create_skill_with_all_fields(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "full-skill",
                "description": "Full featured skill.",
                "body": "# Full\nEverything.",
                "license": "Apache-2.0",
                "compatibility": "Requires Python 3.12+",
                "allowed_tools": ["Bash", "Read"],
                "metadata": {"author": "test-org", "version": "1.0"},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["license"] == "Apache-2.0"
        assert data["compatibility"] == "Requires Python 3.12+"
        assert data["allowed_tools"] == ["Bash", "Read"]
        assert data["metadata"] == {"author": "test-org", "version": "1.0"}

    def test_create_skill_with_duplicate_name_fails(self, mock_feature_enabled):
        self.create_skill(name="existing-skill")

        response = self.client.post(
            self._url(),
            data={
                "name": "existing-skill",
                "description": "Duplicate.",
                "body": "# Dup",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "name"
        assert "already exists" in response.json()["detail"]

    @parameterized.expand(
        [
            ("uppercase", "Invalid_Name"),
            ("leading_hyphen", "-my-skill"),
            ("trailing_hyphen", "my-skill-"),
            ("consecutive_hyphens", "my--skill"),
            ("reserved_new", "new"),
        ]
    )
    def test_create_skill_validates_name_format(self, mock_feature_enabled, _label, skill_name):
        response = self.client.post(
            self._url(),
            data={
                "name": skill_name,
                "description": "Bad name.",
                "body": "# Bad",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_skill_requires_description(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "no-desc",
                "body": "# No desc",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_skill_with_files(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "skill-with-files",
                "description": "Has bundled files from the start.",
                "body": "# Files",
                "files": [
                    {"path": "scripts/run.sh", "content": "#!/bin/bash\necho hi", "content_type": "text/x-shellscript"},
                    {"path": "references/guide.md", "content": "# Guide"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["version"] == 1
        file_manifest = data.get("files", [])
        paths = sorted(f["path"] for f in file_manifest)
        assert paths == ["references/guide.md", "scripts/run.sh"]

        # The bundled file body is fetchable via the file endpoint.
        file_response = self.client.get(f"{self._url()}name/skill-with-files/files/scripts/run.sh")
        assert file_response.status_code == status.HTTP_200_OK
        assert file_response.json()["content"] == "#!/bin/bash\necho hi"
        assert file_response.json()["content_type"] == "text/x-shellscript"

    def test_create_skill_with_oversized_file_fails(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "big-file-skill",
                "description": "Has a huge file.",
                "body": "# Body",
                "files": [
                    {"path": "big.txt", "content": "x" * 1_100_000},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_skill_with_too_many_files_fails(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "many-files-skill",
                "description": "Has too many files.",
                "body": "# Body",
                "files": [{"path": f"file-{i}.txt", "content": "content"} for i in range(51)],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_skill_with_duplicate_file_paths_fails(self, mock_feature_enabled):
        response = self.client.post(
            self._url(),
            data={
                "name": "dup-files-skill",
                "description": "Has duplicate file paths.",
                "body": "# Body",
                "files": [
                    {"path": "scripts/run.sh", "content": "echo a"},
                    {"path": "scripts/run.sh", "content": "echo b"},
                ],
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- List ---

    def test_list_skills_returns_name_and_description_without_body(self, mock_feature_enabled):
        self.create_skill(name="skill-a", description="Does A things.")
        self.create_skill(name="skill-b", description="Does B things.")

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["count"] == 2
        results = data["results"]
        assert len(results) == 2
        assert all("description" in r for r in results)
        assert all("body" not in r for r in results)

    def test_list_skills_search_by_name(self, mock_feature_enabled):
        self.create_skill(name="pdf-processing", description="Handles PDFs.")
        self.create_skill(name="code-review", description="Reviews code.")

        response = self.client.get(self._url() + "?search=pdf")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["name"] == "pdf-processing"

    def test_list_skills_search_by_description(self, mock_feature_enabled):
        self.create_skill(name="skill-one", description="Handles PDF documents.")
        self.create_skill(name="skill-two", description="Reviews Python code.")

        response = self.client.get(self._url() + "?search=python")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 1
        assert response.json()["results"][0]["name"] == "skill-two"

    # --- Get by name ---

    def test_get_skill_by_name(self, mock_feature_enabled):
        self.create_skill(name="fetch-me", description="Fetchable.", body="# Fetch me body")

        response = self.client.get(self._url("name/fetch-me"))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "fetch-me"
        assert data["description"] == "Fetchable."
        assert data["body"] == "# Fetch me body"
        assert "files" in data

    def test_get_skill_by_name_returns_file_manifest(self, mock_feature_enabled):
        skill = self.create_skill(name="with-files")
        LLMSkillFile.objects.create(skill=skill, path="scripts/setup.sh", content="#!/bin/bash\necho hi")
        LLMSkillFile.objects.create(skill=skill, path="references/guide.md", content="# Guide")

        response = self.client.get(self._url("name/with-files"))

        assert response.status_code == status.HTTP_200_OK
        files = response.json()["files"]
        assert len(files) == 2
        paths = {f["path"] for f in files}
        assert "scripts/setup.sh" in paths
        assert "references/guide.md" in paths

    def test_get_skill_not_found(self, mock_feature_enabled):
        response = self.client.get(self._url("name/nonexistent"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- Publish new version ---

    def test_publish_new_version(self, mock_feature_enabled):
        self.create_skill(name="evolving-skill", body="# V1")

        response = self.client.patch(
            self._url("name/evolving-skill"),
            data={"body": "# V2 - improved", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == 2
        assert data["body"] == "# V2 - improved"
        assert data["is_latest"] is True

    def test_publish_carries_forward_unchanged_fields(self, mock_feature_enabled):
        self.create_skill(
            name="carry-forward",
            description="Original desc.",
            body="# V1",
            license="MIT",
            compatibility="Python 3.12+",
        )

        response = self.client.patch(
            self._url("name/carry-forward"),
            data={"body": "# V2", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["description"] == "Original desc."
        assert data["license"] == "MIT"
        assert data["compatibility"] == "Python 3.12+"

    def test_publish_can_update_description(self, mock_feature_enabled):
        self.create_skill(name="update-desc", description="Old desc.", body="# Body")

        response = self.client.patch(
            self._url("name/update-desc"),
            data={"description": "New desc.", "body": "# Body v2", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["description"] == "New desc."

    def test_publish_with_version_conflict_fails(self, mock_feature_enabled):
        self.create_skill(name="conflict-skill", body="# V1")
        self.client.patch(
            self._url("name/conflict-skill"),
            data={"body": "# V2", "base_version": 1},
            format="json",
        )

        response = self.client.patch(
            self._url("name/conflict-skill"),
            data={"body": "# V2-conflict", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_publish_copies_files_forward(self, mock_feature_enabled):
        skill = self.create_skill(name="files-carry", body="# V1")
        LLMSkillFile.objects.create(skill=skill, path="scripts/run.sh", content="#!/bin/bash")

        response = self.client.patch(
            self._url("name/files-carry"),
            data={"body": "# V2", "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        new_skill = LLMSkill.objects.get(name="files-carry", version=2, deleted=False)
        assert LLMSkillFile.objects.filter(skill=new_skill).count() == 1
        assert LLMSkillFile.objects.get(skill=new_skill).path == "scripts/run.sh"

    # --- Publish with edits (find/replace) ---

    def test_publish_with_edits_applies_single_replacement(self, mock_feature_enabled):
        self.create_skill(name="edit-me", body="# Title\n\nHello world.\n")

        response = self.client.patch(
            self._url("name/edit-me"),
            data={
                "edits": [{"old": "Hello world.", "new": "Hello there."}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == 2
        assert data["body"] == "# Title\n\nHello there.\n"

    def test_publish_with_edits_applies_sequential_replacements(self, mock_feature_enabled):
        self.create_skill(name="seq-edits", body="alpha\nbeta\ngamma\n")

        response = self.client.patch(
            self._url("name/seq-edits"),
            data={
                "edits": [
                    {"old": "alpha", "new": "ALPHA"},
                    {"old": "beta", "new": "BETA"},
                ],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["body"] == "ALPHA\nBETA\ngamma\n"

    @parameterized.expand(
        [
            ("zero_matches", "some content\n", [{"old": "missing", "new": "x"}], None),
            ("multi_matches", "pick pick pick\n", [{"old": "pick", "new": "chose"}], "3 times"),
        ]
    )
    def test_publish_with_edits_apply_errors(self, mock_feature_enabled, label, initial_body, edits, detail_fragment):
        skill_name = f"edit-apply-err-{label.replace('_', '-')}"
        self.create_skill(name=skill_name, body=initial_body)

        response = self.client.patch(
            self._url(f"name/{skill_name}"),
            data={"edits": edits, "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body_resp = response.json()
        assert body_resp["edit_index"] == 0
        if detail_fragment is not None:
            assert detail_fragment in body_resp["detail"]

    @parameterized.expand(
        [
            (
                "body_and_edits_conflict",
                {
                    "body": "new content\n",
                    "edits": [{"old": "content", "new": "other"}],
                    "base_version": 1,
                },
            ),
            ("empty_edits_list", {"edits": [], "base_version": 1}),
        ]
    )
    def test_publish_rejects_invalid_edit_requests(self, mock_feature_enabled, label, payload):
        skill_name = f"invalid-{label.replace('_', '-')}"
        self.create_skill(name=skill_name, body="content\n")

        response = self.client.patch(
            self._url(f"name/{skill_name}"),
            data=payload,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_publish_with_edits_exceeding_body_size_limit_fails(self, mock_feature_enabled):
        # Seed a body just under the 1 MB limit, then edit to push the result over.
        seeded_body = "x" * (1_000_000 - len("MARKER")) + "MARKER"
        self.create_skill(name="size-edit", body=seeded_body)

        response = self.client.patch(
            self._url("name/size-edit"),
            data={
                "edits": [{"old": "MARKER", "new": "MARKER" + "y" * 100}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body_resp = response.json()
        assert body_resp["edit_index"] == 0
        assert "size limit" in body_resp["detail"]

    def test_publish_with_edits_carries_files_forward(self, mock_feature_enabled):
        skill = self.create_skill(name="edits-files", body="original\n")
        LLMSkillFile.objects.create(skill=skill, path="references/a.md", content="A")

        response = self.client.patch(
            self._url("name/edits-files"),
            data={
                "edits": [{"old": "original", "new": "edited"}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        new_skill = LLMSkill.objects.get(name="edits-files", version=2, deleted=False)
        assert new_skill.body == "edited\n"
        assert LLMSkillFile.objects.filter(skill=new_skill, path="references/a.md").exists()

    # --- Publish with file_edits (per-file find/replace) ---

    def test_publish_with_file_edits_patches_single_file(self, mock_feature_enabled):
        skill = self.create_skill(name="file-patch", body="# Body\n")
        LLMSkillFile.objects.create(skill=skill, path="references/ranking.md", content="rank high\n")
        LLMSkillFile.objects.create(skill=skill, path="references/other.md", content="untouched\n")

        response = self.client.patch(
            self._url("name/file-patch"),
            data={
                "file_edits": [
                    {
                        "path": "references/ranking.md",
                        "edits": [{"old": "rank high", "new": "rank higher"}],
                    }
                ],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        new_skill = LLMSkill.objects.get(name="file-patch", version=2, deleted=False)
        ranking = LLMSkillFile.objects.get(skill=new_skill, path="references/ranking.md")
        other = LLMSkillFile.objects.get(skill=new_skill, path="references/other.md")
        assert ranking.content == "rank higher\n"
        assert other.content == "untouched\n"

    def test_publish_with_file_edits_patches_multiple_files(self, mock_feature_enabled):
        skill = self.create_skill(name="multi-patch", body="# Body\n")
        LLMSkillFile.objects.create(skill=skill, path="references/a.md", content="alpha\n")
        LLMSkillFile.objects.create(skill=skill, path="references/b.md", content="beta\n")

        response = self.client.patch(
            self._url("name/multi-patch"),
            data={
                "file_edits": [
                    {"path": "references/a.md", "edits": [{"old": "alpha", "new": "ALPHA"}]},
                    {"path": "references/b.md", "edits": [{"old": "beta", "new": "BETA"}]},
                ],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        new_skill = LLMSkill.objects.get(name="multi-patch", version=2, deleted=False)
        assert LLMSkillFile.objects.get(skill=new_skill, path="references/a.md").content == "ALPHA\n"
        assert LLMSkillFile.objects.get(skill=new_skill, path="references/b.md").content == "BETA\n"

    @parameterized.expand(
        [
            (
                "unknown_path",
                "references/exists.md",
                "hello\n",
                [{"path": "references/missing.md", "edits": [{"old": "x", "new": "y"}]}],
                "references/missing.md",
                None,
                None,
            ),
            (
                "zero_matches",
                "references/a.md",
                "hello\n",
                [{"path": "references/a.md", "edits": [{"old": "missing", "new": "x"}]}],
                "references/a.md",
                None,
                0,
            ),
            (
                "multi_matches",
                "references/a.md",
                "pick pick\n",
                [{"path": "references/a.md", "edits": [{"old": "pick", "new": "chose"}]}],
                "references/a.md",
                "2 times",
                0,
            ),
        ]
    )
    def test_publish_with_file_edits_apply_errors(
        self,
        mock_feature_enabled,
        label,
        seed_path,
        seed_content,
        file_edits,
        expected_file_path,
        detail_fragment,
        expected_edit_index,
    ):
        skill_name = f"file-edit-apply-err-{label.replace('_', '-')}"
        skill = self.create_skill(name=skill_name, body="# Body\n")
        LLMSkillFile.objects.create(skill=skill, path=seed_path, content=seed_content)

        response = self.client.patch(
            self._url(f"name/{skill_name}"),
            data={"file_edits": file_edits, "base_version": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        body_resp = response.json()
        assert body_resp["file_path"] == expected_file_path
        if expected_edit_index is None:
            assert "edit_index" not in body_resp
        else:
            assert body_resp["edit_index"] == expected_edit_index
        if detail_fragment is not None:
            assert detail_fragment in body_resp["detail"]

    @parameterized.expand(
        [
            (
                "files_and_file_edits_conflict",
                {
                    "files": [{"path": "references/a.md", "content": "new"}],
                    "file_edits": [{"path": "references/a.md", "edits": [{"old": "hello", "new": "bye"}]}],
                    "base_version": 1,
                },
            ),
            (
                "duplicate_file_edit_paths",
                {
                    "file_edits": [
                        {"path": "references/a.md", "edits": [{"old": "a", "new": "A"}]},
                        {"path": "references/a.md", "edits": [{"old": "b", "new": "B"}]},
                    ],
                    "base_version": 1,
                },
            ),
            ("empty_file_edits_list", {"file_edits": [], "base_version": 1}),
            (
                "traversal_path",
                {
                    "file_edits": [
                        {"path": "../escape.md", "edits": [{"old": "a", "new": "b"}]},
                    ],
                    "base_version": 1,
                },
            ),
            (
                "absolute_path",
                {
                    "file_edits": [
                        {"path": "/absolute/path.md", "edits": [{"old": "a", "new": "b"}]},
                    ],
                    "base_version": 1,
                },
            ),
        ]
    )
    def test_publish_rejects_invalid_file_edit_requests(self, mock_feature_enabled, label, payload):
        skill_name = f"invalid-file-edit-{label.replace('_', '-')}"
        skill = self.create_skill(name=skill_name, body="# Body\n")
        LLMSkillFile.objects.create(skill=skill, path="references/a.md", content="hello\n")

        response = self.client.patch(
            self._url(f"name/{skill_name}"),
            data=payload,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_publish_combines_body_edits_and_file_edits(self, mock_feature_enabled):
        skill = self.create_skill(name="body-and-file", body="# Title\noriginal\n")
        LLMSkillFile.objects.create(skill=skill, path="references/a.md", content="old\n")

        response = self.client.patch(
            self._url("name/body-and-file"),
            data={
                "edits": [{"old": "original", "new": "updated"}],
                "file_edits": [{"path": "references/a.md", "edits": [{"old": "old", "new": "new"}]}],
                "base_version": 1,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        new_skill = LLMSkill.objects.get(name="body-and-file", version=2, deleted=False)
        assert new_skill.body == "# Title\nupdated\n"
        assert LLMSkillFile.objects.get(skill=new_skill, path="references/a.md").content == "new\n"

    # --- Archive ---

    def test_archive_skill(self, mock_feature_enabled):
        self.create_skill(name="to-archive")

        response = self.client.post(self._url("name/to-archive/archive"))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not LLMSkill.objects.filter(name="to-archive", deleted=False).exists()

    # --- Duplicate ---

    def test_duplicate_skill(self, mock_feature_enabled):
        skill = self.create_skill(name="original", description="Original skill.", body="# Original")
        LLMSkillFile.objects.create(skill=skill, path="scripts/run.sh", content="#!/bin/bash")

        response = self.client.post(
            self._url("name/original/duplicate"),
            data={"new_name": "the-copy"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == "the-copy"
        assert data["description"] == "Original skill."
        assert data["version"] == 1

        copy_skill = LLMSkill.objects.get(name="the-copy", deleted=False)
        assert LLMSkillFile.objects.filter(skill=copy_skill).count() == 1

    def test_duplicate_to_existing_name_fails(self, mock_feature_enabled):
        self.create_skill(name="source")
        self.create_skill(name="taken")

        response = self.client.post(
            self._url("name/source/duplicate"),
            data={"new_name": "taken"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # --- Get file ---

    def test_get_file_by_path(self, mock_feature_enabled):
        skill = self.create_skill(name="file-skill")
        LLMSkillFile.objects.create(
            skill=skill,
            path="scripts/setup.sh",
            content="#!/bin/bash\necho hello",
            content_type="text/x-shellscript",
        )

        response = self.client.get(self._url("name/file-skill/files/scripts/setup.sh"))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["path"] == "scripts/setup.sh"
        assert data["content"] == "#!/bin/bash\necho hello"
        assert data["content_type"] == "text/x-shellscript"

    def test_get_nonexistent_file_returns_404(self, mock_feature_enabled):
        self.create_skill(name="no-files")

        response = self.client.get(self._url("name/no-files/files/missing.txt"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    # --- File CRUD (create / delete / rename) ---

    def test_create_file_adds_file_and_bumps_version(self, mock_feature_enabled):
        self.create_skill(name="crud-create", body="# V1")

        response = self.client.post(
            self._url("name/crud-create/files"),
            data={"path": "scripts/setup.sh", "content": "#!/bin/bash\necho hi"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["version"] == 2
        assert {(f["path"], f["content_type"]) for f in data["files"]} == {("scripts/setup.sh", "text/plain")}
        stored = LLMSkillFile.objects.get(skill__name="crud-create", skill__is_latest=True, path="scripts/setup.sh")
        assert stored.content == "#!/bin/bash\necho hi"

    def test_create_file_carries_existing_files_forward(self, mock_feature_enabled):
        skill = self.create_skill(name="crud-carry")
        LLMSkillFile.objects.create(skill=skill, path="references/a.md", content="A")

        response = self.client.post(
            self._url("name/crud-carry/files"),
            data={"path": "references/b.md", "content": "B"},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        paths = {f["path"] for f in response.json()["files"]}
        assert paths == {"references/a.md", "references/b.md"}

    def test_create_file_fails_when_path_exists(self, mock_feature_enabled):
        skill = self.create_skill(name="crud-dup")
        LLMSkillFile.objects.create(skill=skill, path="dup.md", content="existing")

        response = self.client.post(
            self._url("name/crud-dup/files"),
            data={"path": "dup.md", "content": "new"},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in response.json()["detail"]

    def test_create_file_rejects_path_traversal(self, mock_feature_enabled):
        self.create_skill(name="crud-traversal")

        response = self.client.post(
            self._url("name/crud-traversal/files"),
            data={"path": "../etc/passwd", "content": "no"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_file_enforces_max_file_count(self, mock_feature_enabled):
        from ..skill_services import MAX_SKILL_FILE_COUNT

        skill = self.create_skill(name="crud-max")
        LLMSkillFile.objects.bulk_create(
            [LLMSkillFile(skill=skill, path=f"f{i}.md", content="x") for i in range(MAX_SKILL_FILE_COUNT)]
        )

        response = self.client.post(
            self._url("name/crud-max/files"),
            data={"path": "overflow.md", "content": "x"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert str(MAX_SKILL_FILE_COUNT) in response.json()["detail"]

    def test_create_file_on_unknown_skill_returns_404(self, mock_feature_enabled):
        response = self.client.post(
            self._url("name/missing/files"),
            data={"path": "a.md", "content": "A"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_file_removes_file_and_bumps_version(self, mock_feature_enabled):
        skill = self.create_skill(name="crud-delete")
        LLMSkillFile.objects.create(skill=skill, path="keep.md", content="K")
        LLMSkillFile.objects.create(skill=skill, path="remove.md", content="R")

        response = self.client.delete(self._url("name/crud-delete/files/remove.md"))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == 2
        paths = {f["path"] for f in data["files"]}
        assert paths == {"keep.md"}

    def test_delete_file_returns_404_when_path_missing(self, mock_feature_enabled):
        self.create_skill(name="crud-delete-missing")

        response = self.client.delete(self._url("name/crud-delete-missing/files/nope.md"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_file_rejects_path_traversal(self, mock_feature_enabled):
        self.create_skill(name="crud-delete-traversal")

        response = self.client.delete(self._url("name/crud-delete-traversal/files/..%2Fetc%2Fpasswd"))

        # %2F decodes to '/' so the path *does* reach delete_file; the in-view ".." segment
        # check is what produces the 400. 404 is also tolerated in case routing/middleware
        # rejects it earlier for some setups.
        assert response.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND}

    def test_delete_file_requires_write_scope(self, mock_feature_enabled):
        # delete_file is registered via @get_file.mapping.delete, which would otherwise
        # inherit get_file's llm_skill:read scope. Verify DELETE requires llm_skill:write.
        request = APIRequestFactory().delete("/api/environments/1/llm_skills/name/x/files/a.md")
        view = LLMSkillViewSet()
        view.action = "delete_file"
        assert view.dangerously_get_required_scopes(request, view) == ["llm_skill:write"]

        view.action = "get_file"
        assert view.dangerously_get_required_scopes(request, view) == ["llm_skill:write"]

    def test_get_file_uses_read_scope(self, mock_feature_enabled):
        request = APIRequestFactory().get("/api/environments/1/llm_skills/name/x/files/a.md")
        view = LLMSkillViewSet()
        view.action = "get_file"
        # GET on get_file should fall through to the action's own required_scopes=['llm_skill:read']
        # (dangerously_get_required_scopes returns None so the action decorator's scope wins).
        assert view.dangerously_get_required_scopes(request, view) is None

    def test_rename_file_moves_file_and_bumps_version(self, mock_feature_enabled):
        skill = self.create_skill(name="crud-rename")
        LLMSkillFile.objects.create(skill=skill, path="old/name.md", content="X", content_type="text/markdown")

        response = self.client.post(
            self._url("name/crud-rename/files-rename"),
            data={"old_path": "old/name.md", "new_path": "new/name.md"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["version"] == 2
        paths = {f["path"]: f["content_type"] for f in data["files"]}
        assert paths == {"new/name.md": "text/markdown"}
        new_file = LLMSkillFile.objects.get(skill__name="crud-rename", skill__is_latest=True)
        assert new_file.path == "new/name.md"
        assert new_file.content == "X"
        assert new_file.content_type == "text/markdown"

    def test_rename_file_returns_404_when_old_path_missing(self, mock_feature_enabled):
        self.create_skill(name="crud-rename-missing")

        response = self.client.post(
            self._url("name/crud-rename-missing/files-rename"),
            data={"old_path": "missing.md", "new_path": "new.md"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_rename_file_returns_409_when_new_path_exists(self, mock_feature_enabled):
        skill = self.create_skill(name="crud-rename-conflict")
        LLMSkillFile.objects.create(skill=skill, path="a.md", content="A")
        LLMSkillFile.objects.create(skill=skill, path="b.md", content="B")

        response = self.client.post(
            self._url("name/crud-rename-conflict/files-rename"),
            data={"old_path": "a.md", "new_path": "b.md"},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_rename_file_rejects_same_path(self, mock_feature_enabled):
        skill = self.create_skill(name="crud-rename-noop")
        LLMSkillFile.objects.create(skill=skill, path="a.md", content="A")

        response = self.client.post(
            self._url("name/crud-rename-noop/files-rename"),
            data={"old_path": "a.md", "new_path": "a.md"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            ("create",),
            ("delete",),
            ("rename",),
        ]
    )
    def test_file_write_respects_base_version(self, mock_feature_enabled, endpoint):
        skill_name = f"crud-{endpoint}-bv"
        skill = self.create_skill(name=skill_name, body="# V1")
        LLMSkillFile.objects.create(skill=skill, path="target.md", content="T")

        if endpoint == "create":
            response = self.client.post(
                self._url(f"name/{skill_name}/files"),
                data={"path": "new.md", "content": "N", "base_version": 99},
                format="json",
            )
        elif endpoint == "delete":
            response = self.client.delete(self._url(f"name/{skill_name}/files/target.md") + "?base_version=99")
        else:
            response = self.client.post(
                self._url(f"name/{skill_name}/files-rename"),
                data={"old_path": "target.md", "new_path": "renamed.md", "base_version": 99},
                format="json",
            )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["current_version"] == 1
        assert LLMSkillFile.objects.filter(skill__name=skill_name, path="target.md").exists()

    def test_file_crud_sequence_is_chainable_with_base_version(self, mock_feature_enabled):
        """Agents should be able to chain create/rename/delete via base_version."""
        self.create_skill(name="crud-chain", body="# V1")

        # v1 -> v2: create a.md with base_version 1
        r1 = self.client.post(
            self._url("name/crud-chain/files"),
            data={"path": "a.md", "content": "A", "base_version": 1},
            format="json",
        )
        assert r1.status_code == status.HTTP_201_CREATED
        assert r1.json()["version"] == 2

        # v2 -> v3: rename with base_version 2
        r2 = self.client.post(
            self._url("name/crud-chain/files-rename"),
            data={"old_path": "a.md", "new_path": "b.md", "base_version": 2},
            format="json",
        )
        assert r2.status_code == status.HTTP_200_OK
        assert r2.json()["version"] == 3

        # v3 -> v4: delete with base_version 3
        r3 = self.client.delete(self._url("name/crud-chain/files/b.md") + "?base_version=3")
        assert r3.status_code == status.HTTP_200_OK
        assert r3.json()["version"] == 4
        assert LLMSkillFile.objects.filter(skill__name="crud-chain", skill__is_latest=True).count() == 0

    # --- Resolve ---

    def test_resolve_returns_skill_with_version_history(self, mock_feature_enabled):
        self.create_skill(name="versioned", body="# V1", version=1, is_latest=False)
        self.create_skill(name="versioned", body="# V2", version=2, is_latest=True)

        response = self.client.get(self._url("resolve/name/versioned"))

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["skill"]["name"] == "versioned"
        assert len(data["versions"]) == 2
        assert data["versions"][0]["version"] == 2
        assert data["versions"][1]["version"] == 1

    # --- Feature flag ---

    def test_returns_403_when_feature_flag_disabled(self, mock_feature_enabled):
        mock_feature_enabled.return_value = False

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_403_FORBIDDEN
