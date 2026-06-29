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

from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey, User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from ee.models.rbac.access_control import AccessControl

from ...api.skill_serializers import validate_skill_file_path
from ...api.skill_services import archive_skill
from ...marketplace import adapters
from ...marketplace.adapters import build_team_marketplace_tree
from ...marketplace.credentials import issue_marketplace_credential
from ...marketplace.packaging import SkillExport, build_skill_zip
from ...models.skills import LLMSkill, LLMSkillFile

_PAK_TOKEN = "phx_marketplacetoken123"


def _basic_header(token: str) -> str:
    raw = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"Basic {raw}"


def _mint_pak(
    user: User, *, scopes: list[str], scoped_teams: list[int] | None = None, token: str = _PAK_TOKEN
) -> PersonalAPIKey:
    return PersonalAPIKey.objects.create(
        user=user,
        label="marketplace-test",
        secure_value=hash_key_value(token),
        mask_value="phx...key",
        scopes=scopes,
        scoped_teams=scoped_teams,
    )


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

    def test_export_returns_spec_zip(self):
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

    def test_export_missing_skill_404(self):
        assert self.client.get(self._url("nope")).status_code == status.HTTP_404_NOT_FOUND

    def test_export_then_reimport_round_trip(self):
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

    def test_import_missing_file_is_400(self):
        response = self.client.post(f"/api/environments/{self.team.id}/llm_skills/import", {}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_import_duplicate_name_is_400(self):
        LLMSkill.objects.create(
            team=self.team, name="dupe", description="d", body="b", version=1, is_latest=True, created_by=self.user
        )
        export = SkillExport(name="dupe", description="A dupe.", body="# dupe\n", version=1)
        upload = SimpleUploadedFile("dupe.zip", build_skill_zip(export), content_type="application/zip")
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_skills/import", {"file": upload}, format="multipart"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_export_rejects_spec_invalid_description(self):
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
        # No credential → 401 with a Basic challenge (git can't complete a Bearer/OAuth flow, so the
        # view pins WWW-Authenticate to Basic via the global 401 handler).
        response = self.client.get(self._info_refs_url(), {"service": "git-upload-pack"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.get("WWW-Authenticate", "").startswith("Basic")

    def test_info_refs_with_pak_advertises_refs(self):
        self._create_skill()
        _mint_pak(self.user, scopes=["llm_skill:read"], scoped_teams=[self.team.id])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/x-git-upload-pack-advertisement"
        assert b"# service=git-upload-pack" in response.content
        assert b"refs/heads/main" in response.content

    def test_info_refs_rejects_unknown_service(self):
        _mint_pak(self.user, scopes=["llm_skill:read"], scoped_teams=[self.team.id])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-receive-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_pak_without_scope_is_denied(self):
        _mint_pak(self.user, scopes=["dashboard:read"], scoped_teams=[self.team.id])  # lacks llm_skill access
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_pak_scoped_to_other_team_is_denied(self):
        # A key scoped to a different team can't clone this team's marketplace (team scoping).
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        _mint_pak(self.user, scopes=["llm_skill:read"], scoped_teams=[other_team.id])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_non_member_credential_is_denied(self):
        # The point of using a user-tied Personal API Key: when the owner is not (or no longer) a
        # member of the team, their credential stops working — no manual revocation needed.
        outsider = User.objects.create_user("outsider@example.com", "pw", first_name="Out")
        _mint_pak(outsider, scopes=["llm_skill:read"], scoped_teams=[self.team.id])
        response = self.client.get(
            self._info_refs_url(),
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
        )
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_upload_pack_with_pak_returns_packfile_result(self):
        self._create_skill()
        _mint_pak(self.user, scopes=["llm_skill:read"], scoped_teams=[self.team.id])
        response = self.client.post(
            self._upload_pack_url(),
            # A valid pkt-line "done" command (0009 = length 9, payload "done\n") after a flush-pkt.
            data=b"00000009done\n",
            content_type="application/x-git-upload-pack-request",
            # git sends this Accept; the passthrough renderer must satisfy content negotiation (no 406).
            HTTP_ACCEPT="application/x-git-upload-pack-result",
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
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

    def test_backslashes_are_normalized_to_slashes(self):
        # Stored as forward-slash so it nests as a real file in the git tree (and so the two
        # spellings can't dodge dedup), not a flat entry literally named "references\\guide.md".
        assert validate_skill_file_path("references\\guide.md") == "references/guide.md"


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
        assert "plugins/posthog-skill-store/skills/good/SKILL.md" in tree
        assert "plugins/posthog-skill-store/skills/bad/SKILL.md" not in tree


class TestMarketplaceVersion(APIBaseTest):
    def _plugin_version_epoch(self) -> int:
        tree = build_team_marketplace_tree(self.team)
        version = json.loads(tree[".claude-plugin/marketplace.json"])["plugins"][0]["version"]
        return int(version.rsplit(".", 1)[1])

    def test_plugin_version_query_is_cached_across_requests(self):
        # The Max(updated_at) query should run once per window, not on every synthesis — a clone is
        # two requests (info/refs + upload-pack) plus repeated auto-update polls.
        LLMSkill.objects.create(
            team=self.team, name="s", description="d", body="x", version=1, is_latest=True, created_by=self.user
        )
        cache.clear()
        with patch.object(adapters, "_team_plugin_version", wraps=adapters._team_plugin_version) as spy:
            adapters.synthesize_team_marketplace_repo(self.team)
            adapters.synthesize_team_marketplace_repo(self.team)
        assert spy.call_count == 1

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


class TestMarketplaceInstallCommand(APIBaseTest):
    def _url(self) -> str:
        return f"/api/environments/{self.team.id}/llm_skills/marketplace/install-command"

    def _label(self) -> str:
        return f"Skill store · team {self.team.id}"

    def _credential(self) -> PersonalAPIKey | None:
        return PersonalAPIKey.objects.filter(user=self.user, label=self._label()).first()

    def test_get_reports_absent_when_no_credential(self):
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "absent"
        assert body["connected"] is False
        assert body["token"] is None
        assert body["command"] is None
        assert body["plugin_name"] == "posthog-skill-store"
        assert "YOUR_PHX_TOKEN" in body["command_template"]
        assert self._credential() is None

    def test_get_does_not_mint(self):
        self.client.get(self._url())
        assert PersonalAPIKey.objects.filter(user=self.user).count() == 0

    def test_post_mints_read_only_team_scoped_credential(self):
        response = self.client.post(self._url())
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "created"
        assert body["connected"] is True
        assert body["token"].startswith("phx_")
        assert body["token"] in body["command"]
        assert "x-access-token:" in body["command"]
        assert f"/api/projects/{self.team.id}/llm_skills/marketplace.git" in body["command"]
        # Claude Code command is two lines: marketplace add, then plugin install.
        assert "/plugin marketplace add" in body["command"]
        assert f"/plugin install posthog-skill-store@{body['marketplace_name']}" in body["command"]

        # Codex command carries the same token and the two-step add/install sequence.
        assert body["token"] in body["codex_command"]
        assert "codex plugin marketplace add" in body["codex_command"]
        assert f"codex plugin add posthog-skill-store@{body['marketplace_name']}" in body["codex_command"]

        key = self._credential()
        assert key is not None
        assert key.scopes == ["llm_skill:read"]
        assert key.scoped_teams == [self.team.id]  # locked to this team
        assert key.label == self._label()
        assert PersonalAPIKey.objects.filter(user=self.user).count() == 1

    def test_post_again_without_rotate_reuses_and_returns_no_token(self):
        self.client.post(self._url())
        original = self._credential()
        assert original is not None

        response = self.client.post(self._url())
        body = response.json()
        assert body["status"] == "exists"
        assert body["token"] is None
        assert body["command"] is None
        assert body["mask_value"] == original.mask_value

        # No new key, and the stored secret is untouched — existing setups keep working.
        assert PersonalAPIKey.objects.filter(user=self.user).count() == 1
        original.refresh_from_db()
        reloaded = self._credential()
        assert reloaded is not None
        assert reloaded.secure_value == original.secure_value

    def test_post_with_rotate_rolls_same_key_and_issues_fresh_token(self):
        self.client.post(self._url())
        original = self._credential()
        assert original is not None
        old_secure = original.secure_value

        response = self.client.post(self._url(), {"rotate": True}, format="json")
        body = response.json()
        assert body["status"] == "rotated"
        assert body["token"].startswith("phx_")

        # Same record (no sprawl), new secret, rotation timestamp set, and crucially the returned
        # token matches the stored hash (the rotate is atomic — no lost update).
        assert PersonalAPIKey.objects.filter(user=self.user).count() == 1
        rolled = self._credential()
        assert rolled is not None
        assert rolled.id == original.id
        assert rolled.secure_value != old_secure
        assert rolled.last_rolled_at is not None
        assert hash_key_value(body["token"]) == rolled.secure_value

    def test_reuse_re_narrows_a_drifted_key_without_minting_a_token(self):
        # A same-label key that somehow carries broader scopes must be pulled back to read-only,
        # single-team before it's handed back — the UI/endpoint describe it as exactly that.
        issue_marketplace_credential(self.team, self.user, rotate=False)
        drifted = self._credential()
        assert drifted is not None
        other_team = Team.objects.create(organization=self.organization, name="other")
        drifted.scopes = ["llm_skill:read", "llm_skill:write"]
        drifted.scoped_teams = [self.team.id, other_team.id]
        drifted.scoped_organizations = [str(self.organization.id)]
        drifted.save()

        result = issue_marketplace_credential(self.team, self.user, rotate=False)

        assert result.status == "exists"
        assert result.token is None  # narrowing needs no new token
        result.key.refresh_from_db()
        assert result.key.scopes == ["llm_skill:read"]
        assert result.key.scoped_teams == [self.team.id]
        assert result.key.scoped_organizations == []

    def test_rotate_re_narrows_scopes_alongside_the_fresh_token(self):
        issue_marketplace_credential(self.team, self.user, rotate=False)
        drifted = self._credential()
        assert drifted is not None
        drifted.scopes = ["llm_skill:read", "llm_skill:write"]
        drifted.save(update_fields=["scopes"])

        result = issue_marketplace_credential(self.team, self.user, rotate=True)

        assert result.status == "rotated"
        assert result.token is not None
        result.key.refresh_from_db()
        # A freshly minted token must never inherit the broader scopes.
        assert result.key.scopes == ["llm_skill:read"]
        assert result.key.scoped_teams == [self.team.id]

    def test_one_user_connecting_does_not_roll_another_users_credential(self):
        # Per-user keying: a teammate connecting must not touch mine.
        mine = issue_marketplace_credential(self.team, self.user, rotate=False)
        my_secure = mine.key.secure_value

        teammate = User.objects.create_and_join(self.organization, "teammate@posthog.com", "pw")
        theirs = issue_marketplace_credential(self.team, teammate, rotate=False)

        assert theirs.status == "created"
        assert theirs.key.id != mine.key.id
        assert PersonalAPIKey.objects.filter(user=self.user).count() == 1
        assert PersonalAPIKey.objects.filter(user=teammate).count() == 1
        mine.key.refresh_from_db()
        assert mine.key.secure_value == my_secure  # untouched


class TestImportAndCreateValidation(APIBaseTest):
    def _import_url(self) -> str:
        return f"/api/environments/{self.team.id}/llm_skills/import"

    def test_import_rejects_oversized_body(self):
        # A spec-valid zip (short description) must still be rejected when its SKILL.md body exceeds
        # the same byte cap the create/edit paths enforce — the import path used to skip that check.
        export = SkillExport(name="big-skill", description="Big skill.", body="x" * 1_000_001, version=1)
        upload = SimpleUploadedFile("big.zip", build_skill_zip(export), content_type="application/zip")
        response = self.client.post(self._import_url(), {"file": upload}, format="multipart")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "body" in str(response.json()).lower()

    def test_create_rejects_whitespace_allowed_tool(self):
        # A tool name with a space would fracture the spec's space-delimited allowed-tools string.
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_skills/",
            {"name": "ws-tool-skill", "description": "d", "body": "b", "allowed_tools": ["Bash Write"]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_oversize_skills_skipped_from_marketplace_tree(self):
        LLMSkill.objects.create(
            team=self.team, name="aaa", description="d", body="x" * 100, version=1, is_latest=True, created_by=self.user
        )
        LLMSkill.objects.create(
            team=self.team, name="zzz", description="d", body="y" * 100, version=1, is_latest=True, created_by=self.user
        )
        with patch.object(adapters, "_MAX_MARKETPLACE_TREE_BYTES", 150):
            tree = build_team_marketplace_tree(self.team)
        # First skill fits the (patched) ceiling; the second crosses it and is skipped rather than OOM.
        assert "plugins/posthog-skill-store/skills/aaa/SKILL.md" in tree
        assert "plugins/posthog-skill-store/skills/zzz/SKILL.md" not in tree


class TestSkillMarketplaceRBAC(APIBaseTest):
    """The marketplace read must be gated by the same llm_skill RBAC as the JSON skill APIs — a
    project member who loses skill access can no longer clone, even with a previously minted key."""

    def setUp(self):
        super().setUp()
        self.client.logout()  # git carries no session; auth is the Basic-bridged PAK only
        cache.clear()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        # Skills inherit their access-control resource from llm_analytics (RESOURCE_INHERITANCE_MAP).
        # Make access grant-based: the resource default is "none", so a member only gets in with an
        # explicit grant — restricting the default is how skill access is actually gated.
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="none")
        LLMSkill.objects.create(
            team=self.team,
            name="make-fractals",
            description="d",
            body="# x\n",
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        self.member = User.objects.create_and_join(self.organization, "rbac-member@posthog.com", "pw")
        _mint_pak(self.member, scopes=["llm_skill:read"], scoped_teams=[self.team.id])

    def _membership(self) -> OrganizationMembership:
        return OrganizationMembership.objects.get(user=self.member, organization=self.organization)

    def _clone_status(self) -> int:
        return self.client.get(
            f"/api/projects/{self.team.id}/llm_skills/marketplace.git/info/refs",
            {"service": "git-upload-pack"},
            HTTP_AUTHORIZATION=_basic_header(_PAK_TOKEN),
        ).status_code

    def test_member_without_skill_access_is_denied(self):
        # Valid key, current project member — but no llm_skill grant → the clone is denied. This is
        # the gap the JSON skill APIs close via AccessControlPermission, now closed here too.
        assert self._clone_status() in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_member_with_skill_access_can_clone(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=self._membership(),
        )
        assert self._clone_status() == status.HTTP_200_OK
