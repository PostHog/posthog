from typing import Any

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.models import FeatureFlag


class TestFeatureFlagConfigVersionValidation(SimpleTestCase):
    @parameterized.expand(
        [
            (f"{mode}_{index}", enforced_rules, version)
            for mode, enforced_rules in [
                ("log_only", set()),
                ("partial", {"cross_field.variant_rollout_sum_not_100"}),
                ("full", {"*"}),
            ]
            for index, version in enumerate([1, 2, "1", True, None, 3])
        ]
    )
    def test_config_version_is_reserved(self, _name: str, enforced_rules: set[str], version: Any) -> None:
        with override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES=enforced_rules):
            serializer = FeatureFlagSerializer(data={"filters": {"version": version}}, partial=True)
            assert not serializer.is_valid()
        assert serializer.errors["filters"][0].code == "reserved_config_version"


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"cross_field.variant_rollout_sum_not_100"})
class TestFeatureFlagConfigVersionWrites(APIBaseTest):
    @parameterized.expand([("create",), ("update",)])
    def test_config_version_cannot_reach_storage(self, operation: str) -> None:
        filters = {"groups": [{"properties": [], "rollout_percentage": 40}]}
        url = f"/api/projects/{self.team.id}/feature_flags/"
        if operation == "update":
            flag = FeatureFlag.objects.create(team=self.team, key="reserved-version", filters=filters)
            response = self.client.patch(f"{url}{flag.id}/", {"filters": {"version": "1"}}, format="json")
        else:
            response = self.client.post(
                url, {"key": "reserved-version", "filters": {**filters, "version": "1"}}, format="json"
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "reserved_config_version"
        assert response.json()["attr"] == "filters"
        if operation == "update":
            flag.refresh_from_db()
            assert flag.filters == filters
        else:
            assert not FeatureFlag.objects.filter(team=self.team, key="reserved-version").exists()
