from posthog.test.base import APIBaseTest, BaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team, User

from ...api.skill_services import (
    LLMSkillNotFoundError,
    create_skill_file,
    get_latest_skills_queryset,
    get_skill_by_name_from_db,
    publish_skill_version,
    set_skill_visibility,
)
from ...models.skills import LLMSkill


def _create_skill(
    team: Team,
    *,
    name: str = "my-skill",
    is_global: bool = False,
    version: int = 1,
    is_latest: bool = True,
    body: str = "# body",
    created_by: User | None = None,
) -> LLMSkill:
    return LLMSkill.objects.create(
        team=team,
        name=name,
        description="d",
        body=body,
        version=version,
        is_latest=is_latest,
        is_global=is_global,
        created_by=created_by,
    )


class TestLLMSkillVisibilityService(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.other_org = Organization.objects.create(name="Consumer Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Consumer Team")

    def test_set_skill_visibility_flags_every_version_and_toggles_back(self) -> None:
        _create_skill(self.team, name="foo", version=1, is_latest=False)
        _create_skill(self.team, name="foo", version=2, is_latest=True)

        set_skill_visibility(self.team, "foo", is_global=True)
        assert set(LLMSkill.objects.filter(team=self.team, name="foo").values_list("is_global", flat=True)) == {True}

        set_skill_visibility(self.team, "foo", is_global=False)
        assert set(LLMSkill.objects.filter(team=self.team, name="foo").values_list("is_global", flat=True)) == {False}

    def test_set_skill_visibility_missing_skill_raises(self) -> None:
        with self.assertRaises(LLMSkillNotFoundError):
            set_skill_visibility(self.team, "nope", is_global=True)

    def test_global_skill_reaches_other_team_only_when_globals_included(self) -> None:
        _create_skill(self.team, name="shared", is_global=True)

        # Team-scoped by default: another team can't see it.
        assert get_latest_skills_queryset(self.other_team).filter(name="shared").count() == 0
        assert get_skill_by_name_from_db(self.other_team, "shared") is None

        # Included once globals are requested.
        assert get_latest_skills_queryset(self.other_team, include_global=True).filter(name="shared").count() == 1
        resolved = get_skill_by_name_from_db(self.other_team, "shared", include_global=True)
        assert resolved is not None
        assert resolved.is_global is True

    def test_local_skill_shadows_same_named_global(self) -> None:
        _create_skill(self.team, name="dup", is_global=True)
        own = _create_skill(self.other_team, name="dup")

        latest = get_latest_skills_queryset(self.other_team, include_global=True).filter(name="dup")
        assert latest.count() == 1
        assert latest.first().pk == own.pk

        resolved = get_skill_by_name_from_db(self.other_team, "dup", include_global=True)
        assert resolved is not None
        assert resolved.pk == own.pk

    def test_owning_team_is_not_shadowed_from_its_own_global(self) -> None:
        skill = _create_skill(self.team, name="mine", is_global=True)
        latest = get_latest_skills_queryset(self.team, include_global=True).filter(name="mine")
        assert latest.count() == 1
        assert latest.first().pk == skill.pk

    def test_publish_carries_global_visibility_forward(self) -> None:
        _create_skill(self.team, name="foo", is_global=True, created_by=self.user)
        published = publish_skill_version(self.team, user=self.user, skill_name="foo", body="# v2", base_version=1)
        assert published.version == 2
        assert published.is_global is True

    def test_file_edit_carries_global_visibility_forward(self) -> None:
        _create_skill(self.team, name="foo", is_global=True, created_by=self.user)
        updated = create_skill_file(self.team, user=self.user, skill_name="foo", path="scripts/x.py", content="y")
        assert updated.version == 2
        assert updated.is_global is True


class TestLLMSkillGlobalVisibilityAPI(APIBaseTest):
    def _url(self, path: str = "") -> str:
        return f"/api/environments/{self.team.id}/llm_skills/{path}"

    def _make_staff(self) -> None:
        self.user.is_staff = True
        self.user.save()

    def _consumer_team(self) -> tuple[Team, User]:
        org = Organization.objects.create(name="Consumer Org")
        team = Team.objects.create(organization=org, name="Consumer Team")
        user = User.objects.create_and_join(org, "consumer@example.com", None, "Consumer")
        return team, user

    def test_staff_can_toggle_global_visibility(self) -> None:
        self._make_staff()
        _create_skill(self.team, name="foo", created_by=self.user)

        made_global = self.client.post(self._url("name/foo/visibility/"), {"is_global": True}, format="json")
        assert made_global.status_code == status.HTTP_200_OK
        assert made_global.json()["is_global"] is True
        assert LLMSkill.objects.get(team=self.team, name="foo").is_global is True

        made_private = self.client.post(self._url("name/foo/visibility/"), {"is_global": False}, format="json")
        assert made_private.status_code == status.HTTP_200_OK
        assert made_private.json()["is_global"] is False
        assert LLMSkill.objects.get(team=self.team, name="foo").is_global is False

    def test_non_staff_cannot_make_skill_global(self) -> None:
        assert self.user.is_staff is False
        _create_skill(self.team, name="foo", created_by=self.user)

        response = self.client.post(self._url("name/foo/visibility/"), {"is_global": True}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert LLMSkill.objects.get(team=self.team, name="foo").is_global is False

    def test_visibility_on_missing_skill_returns_404(self) -> None:
        self._make_staff()
        response = self.client.post(self._url("name/ghost/visibility/"), {"is_global": True}, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_other_team_sees_and_reads_a_global_skill(self) -> None:
        _create_skill(self.team, name="shared", is_global=True, created_by=self.user)
        other_team, other_user = self._consumer_team()
        self.client.force_login(other_user)

        listed = self.client.get(f"/api/environments/{other_team.id}/llm_skills/")
        assert listed.status_code == status.HTTP_200_OK
        assert "shared" in [s["name"] for s in listed.json()["results"]]

        fetched = self.client.get(f"/api/environments/{other_team.id}/llm_skills/name/shared/")
        assert fetched.status_code == status.HTTP_200_OK
        assert fetched.json()["is_global"] is True

    def test_non_owner_cannot_archive_a_global_skill(self) -> None:
        _create_skill(self.team, name="shared", is_global=True, created_by=self.user)
        other_team, other_user = self._consumer_team()
        self.client.force_login(other_user)

        response = self.client.post(f"/api/environments/{other_team.id}/llm_skills/name/shared/archive/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert LLMSkill.objects.get(team=self.team, name="shared").deleted is False

    @parameterized.expand(
        [
            ("publish", "patch", "", {"body": "# hijacked", "base_version": 1}),
            ("create_file", "post", "/files", {"path": "scripts/x.sh", "content": "hijacked"}),
        ]
    )
    def test_non_owner_cannot_write_to_a_global_skill(
        self, _name: str, method: str, suffix: str, payload: dict
    ) -> None:
        # Reads include globals, but writes must stay owner-scoped — a consumer resolving a global
        # from another team and then editing/publishing it must 404, never mutate the owner's row.
        # Archive is covered above; this locks the remaining write verbs against the same regression.
        _create_skill(self.team, name="shared", is_global=True, created_by=self.user, body="# original")
        other_team, other_user = self._consumer_team()
        self.client.force_login(other_user)

        url = f"/api/environments/{other_team.id}/llm_skills/name/shared{suffix}"
        response = getattr(self.client, method)(url, payload, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        owner_skill = LLMSkill.objects.get(team=self.team, name="shared", is_latest=True)
        assert owner_skill.version == 1
        assert owner_skill.body == "# original"

    @parameterized.expand([("detail", "name/shared/"), ("list", "")])
    def test_foreign_team_does_not_see_global_skill_author(self, _name: str, path: str) -> None:
        # created_by is the publishing PostHog staff member (name + email); it must not leak to
        # consuming customers who see the global skill in their own project.
        _create_skill(self.team, name="shared", is_global=True, created_by=self.user)
        other_team, other_user = self._consumer_team()
        self.client.force_login(other_user)

        response = self.client.get(f"/api/environments/{other_team.id}/llm_skills/{path}")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        skill = next(s for s in body["results"] if s["name"] == "shared") if path == "" else body
        assert skill["created_by"] is None

    def test_foreign_team_does_not_see_global_skill_version_authors(self) -> None:
        _create_skill(self.team, name="shared", is_global=True, created_by=self.user)
        other_team, other_user = self._consumer_team()
        self.client.force_login(other_user)

        response = self.client.get(f"/api/environments/{other_team.id}/llm_skills/resolve/name/shared")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["skill"]["created_by"] is None
        assert all(version["created_by"] is None for version in body["versions"])

    def test_owning_team_still_sees_global_skill_author(self) -> None:
        _create_skill(self.team, name="shared", is_global=True, created_by=self.user)

        response = self.client.get(self._url("name/shared/"))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["created_by"]["id"] == self.user.id
