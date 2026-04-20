from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from ...models.skills import LLMSkill, LLMSkillFile


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
