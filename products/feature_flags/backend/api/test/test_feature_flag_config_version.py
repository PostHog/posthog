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
            (f"{mode}_{index}_{shape}", enforced_rules, version, data)
            for mode, enforced_rules in [
                ("log_only", set()),
                ("partial", {"cross_field.variant_rollout_sum_not_100"}),
                ("full", {"*"}),
            ]
            for index, version in enumerate([2, 3, "1", True, None])
            for shape, data in [
                ("omitted", {}),
                ("empty", {"filters": {}}),
                ("supplied", {"filters": {"groups": "invalid"}}),
            ]
        ]
    )
    def test_stored_config_rejected_before_v1_validation(
        self, _name: str, enforced_rules: set[str], version: Any, data: dict
    ) -> None:
        flag = FeatureFlag(filters={"version": version, "groups": "invalid"})
        with override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES=enforced_rules):
            serializer = FeatureFlagSerializer(flag, data=data, partial=True)
            assert not serializer.is_valid()
        assert serializer.errors["filters"][0].code == "unsupported_config_version"

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

    def test_incoming_version_error_precedes_stored_format_error(self) -> None:
        serializer = FeatureFlagSerializer(
            FeatureFlag(filters={"version": 2}), data={"filters": {"version": 1}}, partial=True
        )
        assert not serializer.is_valid()
        assert serializer.errors["filters"][0].code == "reserved_config_version"


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"cross_field.variant_rollout_sum_not_100"})
class TestFeatureFlagConfigVersionWrites(APIBaseTest):
    @parameterized.expand([("patch", {}), ("patch", {"filters": {}}), ("put", {"filters": {"groups": []}})])
    def test_unsupported_stored_config_is_not_rewritten(self, method: str, data: dict) -> None:
        filters = {"version": 2, "return_type": "boolean", "default_value": False, "rules": []}
        flag = FeatureFlag.objects.create(team=self.team, key="stored-config", filters=filters, version=7)
        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"key": flag.key, "name": "Changed", **data},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unsupported_config_version"
        assert response.json()["attr"] == "filters"
        flag.refresh_from_db()
        assert flag.filters == filters
        assert flag.version == 7
        assert flag.name != "Changed"

    @parameterized.expand(
        [
            (f"{method}_{shape}_{explicit}", method, data, explicit)
            for method in ["patch", "put"]
            for shape, data in [
                ("omitted", {}),
                ("empty", {"filters": {}}),
                ("merge", {"filters": {"payloads": {"true": '"enabled"'}}}),
                ("clear", {"filters": {"groups": []}}),
            ]
            for explicit in [False, True]
        ]
    )
    def test_stored_v1_write_semantics(self, _name: str, method: str, data: dict, explicit: bool) -> None:
        filters = {
            "groups": [{"properties": [], "rollout_percentage": 40, "aggregation_group_type_index": None}],
            **({"version": 1} if explicit else {}),
        }
        flag = FeatureFlag.objects.create(team=self.team, key="v1-config", filters=filters, version=7)
        response = getattr(self.client, method)(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"key": flag.key, "name": "Changed", **data},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.version == 8
        assert flag.name == "Changed"
        assert flag.filters["groups"] == data.get("filters", {}).get("groups", filters["groups"])
        assert flag.filters.get("version") == (1 if explicit else None)
        if "payloads" in data.get("filters", {}):
            assert flag.filters["payloads"] == data["filters"]["payloads"]

    def test_put_without_key_is_rejected(self) -> None:
        """PUT reaches the serializer with partial=False, so a missing required field fails."""
        flag = FeatureFlag.objects.create(
            team=self.team, key="v1-config", filters={"groups": []}, version=7, name="Original"
        )
        response = self.client.put(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"name": "Changed"}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "key"
        flag.refresh_from_db()
        assert flag.name == "Original"
        assert flag.version == 7

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
