import base64
import io
import zipfile

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from ...models.skills import LLMSkill, LLMSkillFile

_PSAK_TOKEN = "phs_marketplace_token"


def _basic_header(token: str) -> str:
    raw = base64.b64encode(f"marketplace:{token}".encode()).decode()
    return f"Basic {raw}"


def _mint_psak(team: Team, *, scopes: list[str], token: str = _PSAK_TOKEN) -> ProjectSecretAPIKey:
    return ProjectSecretAPIKey.objects.create(
        team=team,
        label="marketplace",
        secure_value=hash_key_value(token),
        mask_value="phs...key",
        scopes=scopes,
    )


@patch("products.skills.backend.api.skills.posthoganalytics.feature_enabled", return_value=True)
class TestSkillZipExport(APIBaseTest):
    def _url(self, name: str) -> str:
        return f"/api/environments/{self.team.id}/llm_skills/name/{name}/export"

    def _create_skill(self) -> LLMSkill:
        skill = LLMSkill.objects.create(
            team=self.team,
            name="make-fractals",
            description="Render fractals.",
            body="# make-fractals\n\nDo the thing.",
            version=2,
            is_latest=True,
            allowed_tools=["Bash", "Write"],
            created_by=self.user,
        )
        LLMSkillFile.objects.create(skill=skill, path="scripts/run.py", content="print(1)\n", content_type="text/x-python")
        return skill

    def test_export_returns_spec_zip(self, _mock_flag):
        self._create_skill()
        response = self.client.get(self._url("make-fractals"))

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/zip"
        assert "make-fractals.zip" in response["Content-Disposition"]

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            skill_md = archive.read("make-fractals/SKILL.md").decode()
        assert "make-fractals/SKILL.md" in names
        assert "make-fractals/scripts/run.py" in names
        assert "allowed-tools: Bash Write" in skill_md

    def test_export_missing_skill_404(self, _mock_flag):
        assert self.client.get(self._url("nope")).status_code == status.HTTP_404_NOT_FOUND


class TestSkillMarketplaceGit(APIBaseTest):
    def _info_refs_url(self) -> str:
        return f"/api/projects/{self.team.id}/llm_skills/marketplace.git/info/refs"

    def _upload_pack_url(self) -> str:
        return f"/api/projects/{self.team.id}/llm_skills/marketplace.git/git-upload-pack"

    def _create_skill(self) -> LLMSkill:
        return LLMSkill.objects.create(
            team=self.team,
            name="make-fractals",
            description="Render fractals.",
            body="# make-fractals\n",
            version=1,
            is_latest=True,
            created_by=self.user,
        )

    def test_info_refs_requires_credentials(self):
        response = self.client.get(self._info_refs_url(), {"service": "git-upload-pack"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Basic" in response.get("WWW-Authenticate", "")

    def test_info_refs_with_psak_advertises_refs(self):
        self._create_skill()
        _mint_psak(self.team, scopes=["llm_skill:read"])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PSAK_TOKEN),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/x-git-upload-pack-advertisement"
        assert b"# service=git-upload-pack" in response.content
        assert b"refs/heads/main" in response.content

    def test_info_refs_rejects_unknown_service(self):
        _mint_psak(self.team, scopes=["llm_skill:read"])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-receive-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PSAK_TOKEN),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_psak_without_scope_is_denied(self):
        _mint_psak(self.team, scopes=["llm_skill:write"])  # write only, read required
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PSAK_TOKEN),
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_psak_from_other_team_is_denied(self):
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        OrganizationMembership.objects.create(organization=other_org, user=self.user)
        _mint_psak(other_team, scopes=["llm_skill:read"])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PSAK_TOKEN),
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_upload_pack_with_psak_returns_packfile_result(self):
        self._create_skill()
        _mint_psak(self.team, scopes=["llm_skill:read"])
        response = self.client.post(
            self._upload_pack_url(),
            data=b"0000000ddone\n",
            content_type="application/x-git-upload-pack-request",
            HTTP_AUTHORIZATION=_basic_header(_PSAK_TOKEN),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/x-git-upload-pack-result"
        assert len(response.content) > 0
