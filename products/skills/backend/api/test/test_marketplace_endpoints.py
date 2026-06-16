import io
import json
import base64
import zipfile
from datetime import timedelta

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from rest_framework import serializers, status

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from ...api.skill_serializers import validate_skill_file_path
from ...api.skill_services import archive_skill
from ...marketplace.adapters import build_team_marketplace_tree
from ...marketplace.packaging import SkillExport, build_skill_zip
from ...models.skills import LLMSkill, LLMSkillFile

# Real PSAK tokens are alphanumeric after the phs_ prefix (no underscores/hyphens).
_PSAK_TOKEN = "phs_marketplacetoken123"


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
        LLMSkillFile.objects.create(
            skill=skill, path="scripts/run.py", content="print(1)\n", content_type="text/x-python"
        )
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

    def test_export_then_reimport_round_trip(self, _mock_flag):
        skill = LLMSkill.objects.create(
            team=self.team,
            name="round-trip",
            description="Round trip me.",
            body="# round-trip\n\nbody here.\n",
            version=1,
            is_latest=True,
            allowed_tools=["Bash", "Write"],
            created_by=self.user,
        )
        LLMSkillFile.objects.create(
            skill=skill, path="scripts/x.py", content="print(1)\n", content_type="text/x-python"
        )

        export = self.client.get(self._url("round-trip"))
        assert export.status_code == status.HTTP_200_OK
        zip_bytes = export.content

        # Free the name so the re-import recreates it cleanly.
        archive_skill(self.team, "round-trip")

        upload = SimpleUploadedFile("round-trip.zip", zip_bytes, content_type="application/zip")
        imported = self.client.post(
            f"/api/environments/{self.team.id}/llm_skills/import", {"file": upload}, format="multipart"
        )
        assert imported.status_code == status.HTTP_201_CREATED, imported.content
        data = imported.json()
        assert data["name"] == "round-trip"
        assert data["description"] == "Round trip me."
        assert data["body"] == "# round-trip\n\nbody here.\n"
        assert data["allowed_tools"] == ["Bash", "Write"]
        assert any(f["path"] == "scripts/x.py" for f in data["files"])

    def test_import_missing_file_is_400(self, _mock_flag):
        response = self.client.post(f"/api/environments/{self.team.id}/llm_skills/import", {}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_import_duplicate_name_is_400(self, _mock_flag):
        LLMSkill.objects.create(
            team=self.team, name="dupe", description="d", body="b", version=1, is_latest=True, created_by=self.user
        )
        export = SkillExport(name="dupe", description="A dupe.", body="# dupe\n", version=1)
        upload = SimpleUploadedFile("dupe.zip", build_skill_zip(export), content_type="application/zip")
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_skills/import", {"file": upload}, format="multipart"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_export_rejects_spec_invalid_description(self, _mock_flag):
        # Stored limit is 4096 but the spec caps description at 1024 — export must refuse rather
        # than emit a spec-invalid SKILL.md.
        LLMSkill.objects.create(
            team=self.team,
            name="too-long",
            description="x" * 1025,
            body="# too-long\n",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        response = self.client.get(self._url("too-long"))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["problems"]


class TestSkillMarketplaceGit(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Git clients carry no session — clear the base-class force_login so the only
        # credential is the Basic header (or none), matching how `git clone` authenticates.
        self.client.logout()
        # The synthesized repo is cached on team_id + content version; clear so cross-test
        # state (LocMemCache isn't rolled back with the DB) can't leak between cases.
        cache.clear()

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
        # No PSAK → 401 with a Basic challenge (git can't complete a Bearer/OAuth flow, so the
        # view pins WWW-Authenticate to Basic via the global 401 handler).
        response = self.client.get(self._info_refs_url(), {"service": "git-upload-pack"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.get("WWW-Authenticate", "").startswith("Basic")

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
        _mint_psak(self.team, scopes=["dashboard:read"])  # unrelated scope, lacks llm_skill access
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
            # A valid pkt-line "done" command (0009 = length 9, payload "done\n") after a flush-pkt.
            data=b"00000009done\n",
            content_type="application/x-git-upload-pack-request",
            # git sends this Accept; the passthrough renderer must satisfy content negotiation (no 406).
            HTTP_ACCEPT="application/x-git-upload-pack-result",
            HTTP_AUTHORIZATION=_basic_header(_PSAK_TOKEN),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/x-git-upload-pack-result"
        assert len(response.content) > 0


class TestSkillFilePathValidation:
    @pytest.mark.parametrize(
        "bad_path",
        ["", "scripts/", "a//b.md", "..", "../x.md", "/abs.md", "SKILL.md", "skill.md", "a\x00b.md"],
    )
    def test_rejects_unsafe_paths(self, bad_path):
        with pytest.raises(serializers.ValidationError):
            validate_skill_file_path(bad_path)

    @pytest.mark.parametrize("good_path", ["scripts/run.py", "references/guide.md", "a/b/c.md", "scripts/skill.md"])
    def test_accepts_safe_paths(self, good_path):
        assert validate_skill_file_path(good_path) == good_path


class TestMarketplaceResilience(APIBaseTest):
    def test_skill_with_uncloneable_paths_is_skipped_not_fatal(self):
        # A skill with two files colliding only by case would synthesize a tree that aborts
        # `git clone` on a case-insensitive filesystem — it must be skipped, not break the whole
        # team's marketplace.
        good = LLMSkill.objects.create(
            team=self.team, name="good", description="d", body="b", version=1, is_latest=True, created_by=self.user
        )
        LLMSkillFile.objects.create(skill=good, path="scripts/run.py", content="x", content_type="text/x-python")
        bad = LLMSkill.objects.create(
            team=self.team, name="bad", description="d", body="b", version=1, is_latest=True, created_by=self.user
        )
        LLMSkillFile.objects.create(skill=bad, path="a.md", content="x", content_type="text/markdown")
        LLMSkillFile.objects.create(skill=bad, path="A.md", content="y", content_type="text/markdown")

        tree = build_team_marketplace_tree(self.team)
        assert "plugins/posthog-skills/skills/good/SKILL.md" in tree
        assert "plugins/posthog-skills/skills/bad/SKILL.md" not in tree


class TestMarketplaceVersion(APIBaseTest):
    def _plugin_version_epoch(self) -> int:
        tree = build_team_marketplace_tree(self.team)
        version = json.loads(tree[".claude-plugin/marketplace.json"])["plugins"][0]["version"]
        return int(version.rsplit(".", 1)[1])

    def test_archiving_newest_skill_does_not_regress_version(self):
        now = timezone.now().replace(microsecond=0)
        older = LLMSkill.objects.create(
            team=self.team,
            name="skill-old",
            description="old",
            body="x",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        newest = LLMSkill.objects.create(
            team=self.team,
            name="skill-new",
            description="new",
            body="x",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        # Make the to-be-archived skill clearly the most-recently-updated.
        LLMSkill.objects.filter(pk=older.pk).update(updated_at=now - timedelta(hours=2))
        LLMSkill.objects.filter(pk=newest.pk).update(updated_at=now)

        before = self._plugin_version_epoch()
        archive_skill(self.team, "skill-new")
        after = self._plugin_version_epoch()

        # Without the archive bumping updated_at, the version would drop back to the older
        # skill's timestamp; with the fix it advances (archive is itself a change).
        assert after >= before
