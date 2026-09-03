from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.models import Tag

from products.feature_flags.backend.api.feature_flag import TAG_REQUIREMENT_EXEMPT_CREATION_CONTEXTS
from products.feature_flags.backend.facade.api import update_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.team_feature_flag_policy_config import TeamFeatureFlagPolicyConfig


class TestFeatureFlagRequireTags(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/feature_flags/"

    def _require_tags(self, required: bool) -> None:
        TeamFeatureFlagPolicyConfig.objects.update_or_create(team=self.team, defaults={"require_tags": required})
        self.team.refresh_from_db()

    def _tag_flag(self, flag: FeatureFlag, name: str) -> None:
        tag, _ = Tag.objects.get_or_create(name=name, team_id=self.team.id)
        flag.tagged_items.create(tag_id=tag.id)

    def test_create_without_tags_is_allowed_when_not_required(self) -> None:
        self._require_tags(False)

        response = self.client.post(self.url, {"key": "untagged-flag"}, format="json")

        assert response.status_code == status.HTTP_201_CREATED

    def test_create_without_tags_is_rejected_when_required(self) -> None:
        self._require_tags(True)

        response = self.client.post(self.url, {"key": "untagged-flag"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Add at least one tag" in response.json()["detail"]
        assert not FeatureFlag.objects.filter(key="untagged-flag", team=self.team).exists()

    def test_create_with_empty_tag_list_is_rejected_when_required(self) -> None:
        self._require_tags(True)

        response = self.client.post(self.url, {"key": "untagged-flag", "tags": []}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_with_tags_is_allowed_when_required(self) -> None:
        self._require_tags(True)

        response = self.client.post(self.url, {"key": "tagged-flag", "tags": ["billing"]}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        flag = FeatureFlag.objects.get(key="tagged-flag", team=self.team)
        assert list(flag.tagged_items.values_list("tag__name", flat=True)) == ["billing"]

    @parameterized.expand(sorted(TAG_REQUIREMENT_EXEMPT_CREATION_CONTEXTS))
    def test_flags_created_for_another_object_stay_exempt(self, creation_context: str) -> None:
        self._require_tags(True)

        response = self.client.post(
            self.url,
            {"key": f"{creation_context}-flag", "creation_context": creation_context},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED

    def test_update_cannot_remove_the_last_tag_when_required(self) -> None:
        flag = FeatureFlag.objects.create(key="tagged-flag", team=self.team, created_by=self.user)
        self._tag_flag(flag, "billing")
        self._require_tags(True)

        response = self.client.patch(f"{self.url}{flag.id}/", {"tags": []}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Keep at least one tag" in response.json()["detail"]
        assert flag.tagged_items.count() == 1

    def test_update_can_swap_tags_when_required(self) -> None:
        flag = FeatureFlag.objects.create(key="tagged-flag", team=self.team, created_by=self.user)
        self._tag_flag(flag, "billing")
        self._require_tags(True)

        response = self.client.patch(f"{self.url}{flag.id}/", {"tags": ["growth"]}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert list(flag.tagged_items.values_list("tag__name", flat=True)) == ["growth"]

    def test_update_of_a_flag_that_predates_the_setting_is_allowed(self) -> None:
        flag = FeatureFlag.objects.create(key="legacy-flag", team=self.team, created_by=self.user)
        self._require_tags(True)

        response = self.client.patch(f"{self.url}{flag.id}/", {"name": "Renamed"}, format="json")

        assert response.status_code == status.HTTP_200_OK

    def test_update_driven_by_a_post_request_is_not_read_as_a_create(self) -> None:
        # Experiments, early access features, and product tours write a flag as a side effect of
        # their own POST, so the flag serializer sees a POST it must still treat as an update.
        flag = FeatureFlag.objects.create(key="experiment-flag", team=self.team, created_by=self.user)
        self._require_tags(True)
        request = APIRequestFactory().post("/")
        request.user = self.user

        updated = update_flag(flag, {"active": False}, team=self.team, user=self.user, request=request)

        assert updated.active is False

    def test_create_with_a_blank_tag_is_rejected_when_required(self) -> None:
        self._require_tags(True)

        response = self.client.post(self.url, {"key": "blank-tag-flag", "tags": ["   "]}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand([("set", []), ("set", ["   "]), ("remove", ["billing"])])
    def test_bulk_update_cannot_strip_the_last_tag_when_required(self, tag_action: str, tags: list[str]) -> None:
        flag = FeatureFlag.objects.create(key="tagged-flag", team=self.team, created_by=self.user)
        self._tag_flag(flag, "billing")
        self._require_tags(True)

        response = self.client.post(
            f"{self.url}bulk_update_tags/",
            {"ids": [flag.id], "action": tag_action, "tags": tags},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert flag.tagged_items.count() == 1

    def test_bulk_update_can_still_swap_tags_when_required(self) -> None:
        flag = FeatureFlag.objects.create(key="tagged-flag", team=self.team, created_by=self.user)
        self._tag_flag(flag, "billing")
        self._require_tags(True)

        response = self.client.post(
            f"{self.url}bulk_update_tags/",
            {"ids": [flag.id], "action": "set", "tags": ["growth"]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert list(flag.tagged_items.values_list("tag__name", flat=True)) == ["growth"]
