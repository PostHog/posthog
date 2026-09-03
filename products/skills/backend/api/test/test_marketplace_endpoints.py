import io
import json
import base64
import zipfile
from datetime import timedelta
from typing import Any

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import HttpResponse
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from rest_framework import serializers, status

from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey, User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from products.access_control.backend.models.access_control import AccessControl

from ...api.skill_serializers import validate_skill_file_path
from ...api.skill_services import archive_skill, set_skill_owners
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

    def test_export_honors_a_zip_accept_header(self):
        self._create_skill()

        response = self.client.get(self._url("make-fractals"), HTTP_ACCEPT="application/zip")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response["Content-Type"] == "application/zip"
        assert zipfile.is_zipfile(io.BytesIO(response.content))

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


SANDBOX_FLAG = "posthog.permissions.posthoganalytics.feature_enabled"


class TestSkillBundle(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_user = User.objects.create_and_join(self.organization, "other@posthog.com", None)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/llm_skills/bundle"

    def _create_skill(self, name: str, *, created_by: User | None = None, **overrides: Any) -> LLMSkill:
        fields = {
            "team": self.team,
            "name": name,
            "description": f"{name} description.",
            "body": f"# {name}\n",
            "version": 1,
            "is_latest": True,
            "created_by": created_by or self.user,
            **overrides,
        }
        return LLMSkill.objects.create(**fields)

    def _fetch(
        self,
        *,
        flag: bool | None = True,
        authorization: str | None = None,
        content: str | None = None,
        limit: int | str | None = None,
        accept: str | None = None,
    ) -> HttpResponse:
        query: dict[str, str] = {}
        if content:
            query["content"] = content
        if limit is not None:
            query["limit"] = str(limit)
        headers = {name: value for name, value in {"Authorization": authorization, "Accept": accept}.items() if value}
        with patch(SANDBOX_FLAG, return_value=flag):
            return self.client.get(self._url(), query, headers=headers)

    @staticmethod
    def _skill_dirs(response: HttpResponse) -> set[str]:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            return {name.split("/", 1)[0] for name in archive.namelist()}

    def test_flag_off_is_404(self):
        self._create_skill("mine")
        assert self._fetch(flag=False).status_code == status.HTTP_404_NOT_FOUND

    def test_flag_service_unavailable_is_503_not_404(self):
        self._create_skill("mine")
        assert self._fetch(flag=None).status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_personal_api_key_with_read_scope_gets_the_bundle(self):
        self._create_skill("mine")
        self.client.logout()
        _mint_pak(self.user, scopes=["llm_skill:read"])

        response = self._fetch(authorization=f"Bearer {_PAK_TOKEN}")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert self._skill_dirs(response) == {"mine"}

    def test_bundle_contains_only_skills_the_user_created_or_owns(self):
        self._create_skill("mine")
        LLMSkillFile.objects.create(skill=self._create_skill("with-file"), path="scripts/run.py", content="print(1)\n")
        self._create_skill("owned", created_by=self.other_user)
        set_skill_owners(self.team, "owned", [self.user])
        self._create_skill("someone-elses", created_by=self.other_user)
        self._create_skill("signals-scout-x", category="scout")
        self._create_skill("archived", deleted=True)
        self._create_skill("old-version", is_latest=False)
        # The latest row carries the last editor; the creator of version 1 still gets the skill.
        self._create_skill("edited-by-other", is_latest=False)
        self._create_skill("edited-by-other", version=2, created_by=self.other_user)
        self._create_skill("created-by-other-edited-by-me", created_by=self.other_user, is_latest=False)
        self._create_skill("created-by-other-edited-by-me", version=2)

        response = self._fetch(content="full")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response["Content-Type"] == "application/zip"
        assert response["X-Skills-Included"] == "4"
        assert response["X-Skills-Dropped"] == "0"
        assert response["X-Skills-Skipped"] == "0"
        assert self._skill_dirs(response) == {"mine", "with-file", "owned", "edited-by-other"}
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert "with-file/scripts/run.py" in archive.namelist()
            assert "with-file/agents/openai.yaml" in archive.namelist()
            assert "name: mine" in archive.read("mine/SKILL.md").decode()

    @parameterized.expand(["stub", "full"])
    def test_over_cap_keeps_newest_and_drops_the_rest(self, content: str):
        base = timezone.now()
        for index, name in enumerate(["oldest", "middle", "newest"]):
            skill = self._create_skill(name)
            LLMSkill.objects.filter(pk=skill.pk).update(updated_at=base + timedelta(minutes=index))

        response = self._fetch(content=content, limit=2)

        assert response.status_code == status.HTTP_200_OK
        assert self._skill_dirs(response) == {"newest", "middle"}
        assert response["X-Skills-Dropped"] == "1"

    def test_byte_cap_stops_at_the_first_skill_that_does_not_fit(self):
        base = timezone.now()
        for index, (name, body) in enumerate([("older-small", "x"), ("huge", "x" * 10_000), ("newest-small", "x")]):
            skill = self._create_skill(name, body=body)
            LLMSkill.objects.filter(pk=skill.pk).update(updated_at=base + timedelta(minutes=index))

        with patch.object(adapters, "MAX_BUNDLE_BYTES", 5_000):
            response = self._fetch(content="full")

        assert self._skill_dirs(response) == {"newest-small"}
        assert response["X-Skills-Dropped"] == "2"

    @parameterized.expand(["stub", "full"])
    def test_spec_invalid_skill_is_skipped_not_fatal(self, content: str):
        self._create_skill("fine")
        self._create_skill("too-long", description="x" * 1025)

        response = self._fetch(content=content)

        assert response.status_code == status.HTTP_200_OK
        assert self._skill_dirs(response) == {"fine"}
        assert response["X-Skills-Skipped"] == "1"
        assert response["X-Skills-Dropped"] == "0"

    @parameterized.expand(
        [
            ("traversal", ["../escape.md"]),
            ("not_canonical", ["refs\\guide.md"]),
            ("case_collision", ["Refs/guide.md", "refs/Guide.md"]),
            ("sidecar_case_variant", ["Agents/OpenAI.yaml"]),
            ("file_where_a_directory_is_needed", ["assets", "assets/logo.png"]),
            ("file_where_the_sidecar_directory_is_needed", ["agents"]),
        ]
    )
    def test_skill_with_an_unsafe_legacy_path_is_skipped(self, _label: str, paths: list[str]):
        self._create_skill("fine")
        unsafe = self._create_skill("unsafe")
        # Bypasses the serializer validation so the rows look like ones that predate it.
        for path in paths:
            LLMSkillFile.objects.create(skill=unsafe, path=path, content="x")
        self._create_skill("Bad/Name")

        response = self._fetch(content="full")

        assert response.status_code == status.HTTP_200_OK
        assert self._skill_dirs(response) == {"fine"}
        assert response["X-Skills-Skipped"] == "2"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert not any(".." in name or name.startswith("/") for name in archive.namelist())

    @parameterized.expand(
        [
            ("stub", "safe\n"),
            ("stub", "bad--name"),
            ("full", "safe\n"),
            ("full", "bad--name"),
        ]
    )
    def test_skill_with_a_malformed_legacy_name_is_skipped(self, content: str, name: str):
        self._create_skill("fine")
        # Bypasses the serializer validation so the row looks like one that predates it.
        self._create_skill(name)

        response = self._fetch(content=content)

        assert response.status_code == status.HTTP_200_OK
        assert self._skill_dirs(response) == {"fine"}
        assert response["X-Skills-Skipped"] == "1"

    def test_zip_accept_header_gets_the_zip_and_errors_stay_json(self):
        self._create_skill("mine")

        response = self._fetch(accept="application/zip")
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response["Content-Type"] == "application/zip"
        assert self._skill_dirs(response) == {"mine"}

        not_enabled = self._fetch(flag=False, accept="application/zip")
        assert not_enabled.status_code == status.HTTP_404_NOT_FOUND
        assert not_enabled["Content-Type"] == "application/json"
        assert json.loads(not_enabled.content)["detail"] == "Not found."

    def test_skipped_skills_page_at_a_fixed_size_not_the_limit(self):
        def queries_with_skipped_rows(count: int) -> int:
            while LLMSkill.objects.filter(team=self.team, name__startswith="too-long-").count() < count:
                index = LLMSkill.objects.filter(team=self.team, name__startswith="too-long-").count()
                self._create_skill(f"too-long-{index}", description="x" * 1025)
            with CaptureQueriesContext(connection) as context:
                response = self._fetch(limit=1)
            assert response.status_code == status.HTTP_200_OK
            assert response["X-Skills-Skipped"] == str(count)
            return len(context.captured_queries)

        self._create_skill("fine")
        # The first request of a test warms per-process caches; compare only warm requests.
        self._fetch(limit=1)

        # Skipped rows do not count toward the limit, so a limit-sized page would add a query per row.
        # Compare past the log-sample size too: the header must report the true skip count, not the
        # bounded sample the walk retains.
        assert queries_with_skipped_rows(1) == queries_with_skipped_rows(adapters._SKIPPED_LOG_SAMPLE_SIZE + 5)

    def test_skill_archived_while_the_bundle_is_built_is_left_out_not_fatal(self):
        self._create_skill("stays")
        vanishing = self._create_skill("vanishing")
        real_batches = adapters._candidate_batches

        def archive_after_reading(rows: Any) -> Any:
            for row in real_batches(rows):
                if row["name"] == "vanishing":
                    LLMSkill.objects.filter(pk=vanishing.pk).update(deleted=True)
                yield row

        with patch.object(adapters, "_candidate_batches", side_effect=archive_after_reading):
            response = self._fetch(content="full")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert self._skill_dirs(response) == {"stays"}
        assert response["X-Skills-Dropped"] == "0"

    def test_a_bundled_sidecar_file_overrides_the_generated_one(self):
        skill = self._create_skill("mine")
        LLMSkillFile.objects.create(skill=skill, path="agents/openai.yaml", content="interface: custom\n")

        response = self._fetch(content="full")

        assert self._skill_dirs(response) == {"mine"}
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.read("mine/agents/openai.yaml").decode() == "interface: custom\n"

    def test_an_invalid_skill_ahead_of_the_byte_cap_is_skipped_not_capping(self):
        base = timezone.now()
        for index, (name, body, description) in enumerate(
            [("older-valid", "x", "fine"), ("newest-invalid-and-huge", "x" * 10_000, "d" * 1025)]
        ):
            skill = self._create_skill(name, body=body, description=description)
            LLMSkill.objects.filter(pk=skill.pk).update(updated_at=base + timedelta(minutes=index))

        with patch.object(adapters, "MAX_BUNDLE_BYTES", 5_000):
            response = self._fetch(content="full")

        assert self._skill_dirs(response) == {"older-valid"}
        assert response["X-Skills-Skipped"] == "1"
        assert response["X-Skills-Dropped"] == "0"

    def test_skill_the_user_is_blocked_from_reading_is_left_out(self):
        cache.clear()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "member@posthog.com", None)
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="member"
        )
        # Resource default "none": the member reaches a skill only through an explicit object grant.
        AccessControl.objects.create(team=self.team, resource="llm_skill", resource_id=None, access_level="none")
        allowed = self._create_skill("allowed")
        self._create_skill("blocked")
        set_skill_owners(self.team, "allowed", [member])
        set_skill_owners(self.team, "blocked", [member])
        AccessControl.objects.create(
            team=self.team,
            resource="llm_skill",
            resource_id=str(allowed.id),
            access_level="viewer",
            organization_member=OrganizationMembership.objects.get(user=member, organization=self.organization),
        )
        self.client.force_login(member)

        response = self._fetch()

        assert response.status_code == status.HTTP_200_OK, response.content
        assert self._skill_dirs(response) == {"allowed"}

    def test_default_bundle_is_stubs_that_point_at_the_mcp(self):
        skill = self._create_skill("mine", description="Forecast quota usage.", body="# The real instructions\n")
        LLMSkillFile.objects.create(skill=skill, path="scripts/run.py", content="print(1)\n")
        self._create_skill("Bad/Name")

        response = self._fetch()

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response["X-Skills-Included"] == "1"
        assert response["X-Skills-Skipped"] == "1"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.namelist() == ["mine/SKILL.md"]
            stub = archive.read("mine/SKILL.md").decode()
        assert "name: mine" in stub
        assert "description: Forecast quota usage." in stub
        assert "source: posthog-skills-store" in stub
        assert 'call skill-get {"skill_name": "mine"}' in stub
        assert "body_next_offset" in stub
        assert '"version": <version>' in stub
        assert "The real instructions" not in stub

    @parameterized.expand(
        [
            ("unknown_content", {"content": "partial"}),
            ("limit_over_ceiling", {"limit": 101}),
            ("limit_zero", {"limit": 0}),
        ]
    )
    def test_bad_query_params_are_400(self, _label: str, query: dict[str, Any]):
        self._create_skill("mine")

        assert self._fetch(**query).status_code == status.HTTP_400_BAD_REQUEST

    def test_no_skills_is_an_empty_zip(self):
        response = self._fetch()

        assert response.status_code == status.HTTP_200_OK
        assert response["X-Skills-Included"] == "0"
        assert self._skill_dirs(response) == set()

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.skills.backend.api.skills.SkillBundleBurstThrottle.rate", new="1/minute")
    def test_oauth_and_session_callers_are_throttled(self, *_args):
        # The general Burst/Sustained throttles only count personal-API-key traffic, so an OAuth
        # (or session) caller would otherwise hit this expensive zip endpoint unthrottled. The
        # patched rate trips the second call; the test client uses session auth, the same
        # "authenticated, no personal API key" class the sandbox's OAuth token falls into.
        self._create_skill("mine")

        first = self._fetch()
        assert first.status_code == status.HTTP_200_OK, first.content

        second = self._fetch()
        assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS

        # The bucket is per user, so one caller's burst does not 429 the rest of the project.
        self.client.force_login(self.other_user)
        assert self._fetch().status_code == status.HTTP_200_OK


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
        # Make access grant-based: the resource default is "none", so a member only gets in with an
        # explicit grant — restricting the default is how skill access is actually gated.
        AccessControl.objects.create(team=self.team, resource="llm_skill", resource_id=None, access_level="none")
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
            resource="llm_skill",
            resource_id=None,
            access_level="viewer",
            organization_member=self._membership(),
        )
        assert self._clone_status() == status.HTTP_200_OK
