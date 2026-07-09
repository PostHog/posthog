import json

import unittest
from posthog.test.base import APIBaseTest, BaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest.mock import ANY, MagicMock, patch

from django.core.cache import cache
from django.test.client import Client

from parameterized import parameterized
from rest_framework import status

from posthog.api.test.test_personal_api_keys import PersonalAPIKeysBaseTest
from posthog.models.team.team_caching import set_team_in_cache
from posthog.models.user import User
from posthog.test.persons import create_person

from products.early_access_features.backend.models import EarlyAccessFeature
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.models.rbac.access_control import AccessControl


class TestEarlyAccessFeatureSiteAppTemplate(unittest.TestCase):
    def test_site_app_template_escapes_user_controlled_fields(self):
        import re

        from posthog.cdp.templates._siteapps.template_early_access_features import template

        code = template.code

        assert "escapeHTML" in code, "escapeHTML function must be defined in the template"

        for field in ["item.name", "item.description"]:
            raw_pattern = re.compile(r"\$\{" + re.escape(field) + r"\}")
            escaped_pattern = re.compile(r"\$\{escapeHTML\(" + re.escape(field) + r"\)\}")

            raw_count = len(raw_pattern.findall(code))
            escaped_count = len(escaped_pattern.findall(code))

            assert raw_count == 0, f"Found {raw_count} unescaped interpolation(s) of {field}"
            assert escaped_count > 0, f"No escaped interpolation of {field} found"

    def test_site_app_template_uses_safe_url_for_documentation_url_href(self):
        """safeUrl validates the protocol (http/https only) and encodes the URL,
        unlike raw encodeURI which would allow javascript: URLs through."""
        import re

        from posthog.cdp.templates._siteapps.template_early_access_features import template

        code = template.code

        raw_pattern = re.compile(r"\$\{item\.documentationUrl\}")
        safe_url_pattern = re.compile(r"\$\{safeUrl\(item\.documentationUrl\)\}")

        assert "safeUrl" in code, "safeUrl function must be defined in the template"
        assert len(raw_pattern.findall(code)) == 0, "Found unescaped interpolation of item.documentationUrl"
        assert len(safe_url_pattern.findall(code)) > 0, "item.documentationUrl must be wrapped in safeUrl"


class TestEarlyAccessFeature(APIBaseTest):
    maxDiff = None

    def test_can_create_early_access_feature_in_concept_stage(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert EarlyAccessFeature.objects.filter(id=response_data["id"]).exists()
        assert FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).exists()
        assert response_data["name"] == "Hick bondoogling"
        assert response_data["description"] == 'Boondoogle your hicks with one click. Just click "bazinga"!'
        assert response_data["stage"] == "concept"
        assert response_data["feature_flag"]["key"] == "hick-bondoogling"
        assert response_data["feature_flag"]["active"]
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert not response_data["feature_flag"]["filters"].get("feature_enrollment", None)
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert response_data["feature_flag"]["filters"]["groups"][0]["rollout_percentage"] == 0
        assert isinstance(response_data["created_at"], str)

    def test_can_create_early_access_feature_in_alpha_stage(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "alpha",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["stage"] == "alpha"
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

    @parameterized.expand(
        [
            (EarlyAccessFeature.Stage.ALPHA,),
            (EarlyAccessFeature.Stage.BETA,),
            (EarlyAccessFeature.Stage.GENERAL_AVAILABILITY,),
        ]
    )
    def test_promote_concept_to_active_stage_adds_feature_enrollment(self, target_stage):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert not response_data["feature_flag"]["filters"].get("feature_enrollment", None)

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "stage": target_stage,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == target_stage
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

    @parameterized.expand(
        [
            (
                "with_rollout_to_all",
                True,
                False,
                [{"properties": [], "rollout_percentage": 100, "aggregation_group_type_index": None}],
            ),
            ("without_rollout_to_all", False, True, None),
        ]
    )
    def test_promote_to_ga_rollout_to_all(self, _name, rollout_to_all, expect_enrollment, expected_groups):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={"name": "Hick bondoogling", "description": "Test feature", "stage": "beta"},
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

        feature_id = response_data["id"]

        patch_data: dict = {"stage": EarlyAccessFeature.Stage.GENERAL_AVAILABILITY}
        if rollout_to_all:
            patch_data["rollout_to_all"] = True

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data=patch_data,
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.GENERAL_AVAILABILITY
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        if expect_enrollment:
            assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True
        else:
            assert not response_data["feature_flag"]["filters"].get("feature_enrollment")
            assert response_data["feature_flag"]["filters"]["groups"] == expected_groups

    def test_demote_alpha_to_concept_removes_feature_enrollment(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "alpha",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "stage": EarlyAccessFeature.Stage.CONCEPT,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.CONCEPT
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert not response_data["feature_flag"]["filters"].get("feature_enrollment", None)

    def test_archive(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "stage": EarlyAccessFeature.Stage.ARCHIVED,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.ARCHIVED
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert not response_data["feature_flag"]["filters"].get("feature_enrollment", None)

    def test_update_doesnt_remove_feature_enrollment(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "description": "Something else!",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.BETA
        assert response_data["description"] == "Something else!"
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True

    def test_we_dont_delete_existing_flag_information_when_creating_early_access_feature(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ],
                "payloads": {"true": '"Hick bondoogling? ????"'},
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert EarlyAccessFeature.objects.filter(id=response_data["id"]).exists()
        assert FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).exists()

        flag.refresh_from_db()
        self.assertEqual(
            flag.filters,
            {
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                        "aggregation_group_type_index": None,
                    }
                ],
                "payloads": {"true": '"Hick bondoogling? ????"'},
                "aggregation_group_type_index": None,
                "feature_enrollment": True,
            },
        )

    def test_cant_create_early_access_feature_with_duplicate_key(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "There is already a feature flag with this key.",
        )

    def test_can_create_new_early_access_feature_with_soft_deleted_flag(self):
        FeatureFlag.objects.create(
            team=self.team,
            filters={"groups": [{"properties": [], "rollout_percentage": None}]},
            key="hick-bondoogling",
            created_by=self.user,
            deleted=True,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert EarlyAccessFeature.objects.filter(id=response_data["id"]).exists()
        assert FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).exists()
        assert response_data["name"] == "Hick bondoogling"
        assert response_data["description"] == 'Boondoogle your hicks with one click. Just click "bazinga"!'
        assert response_data["stage"] == "beta"
        assert response_data["feature_flag"]["key"] == "hick-bondoogling"
        assert response_data["feature_flag"]["active"]
        assert "super_groups" not in response_data["feature_flag"]["filters"]
        assert response_data["feature_flag"]["filters"]["feature_enrollment"] is True
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert response_data["feature_flag"]["filters"]["groups"][0]["rollout_percentage"] == 0
        assert isinstance(response_data["created_at"], str)

    def test_deleting_early_access_feature_removes_feature_enrollment_from_flag(self):
        existing_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ]
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": existing_flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        response = self.client.delete(
            f"/api/projects/{self.team.id}/early_access_feature/{response_data['id']}/",
            format="json",
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        flag = FeatureFlag.objects.filter(key=response_data["feature_flag"]["key"]).all()[0]

        self.assertEqual(
            flag.filters,
            {
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                        "aggregation_group_type_index": None,
                    }
                ],
                "aggregation_group_type_index": None,
                "feature_enrollment": None,
            },
        )

    def test_cant_soft_delete_flag_with_early_access_feature(self):
        existing_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [
                    {
                        "properties": [{"key": "xyz", "value": "ok", "type": "person"}],
                        "rollout_percentage": None,
                    }
                ]
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": existing_flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{existing_flag.id}/",
            data={
                "deleted": True,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        assert (
            response_data["detail"]
            == "Cannot delete a feature flag that is in use with early access features. Please delete the early access feature before deleting the flag."
        )

    def test_cant_create_early_access_feature_with_group_flag(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "aggregation_group_type_index": 1,
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "Group-based feature flags are not supported for Early Access Features.",
        )

    def test_cant_create_early_access_feature_with_multivariate_flag(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "first-variant",
                            "name": "First Variant",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "second-variant",
                            "name": "Second Variant",
                            "rollout_percentage": 25,
                        },
                        {
                            "key": "third-variant",
                            "name": "Third Variant",
                            "rollout_percentage": 25,
                        },
                    ]
                },
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "Multivariate feature flags are not supported for Early Access Features.",
        )

    def test_cant_create_early_access_feature_with_flag_with_existing_early_access_feature(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [], "rollout_percentage": None}],
            },
            key="hick-bondoogling",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )

        # Request for new feature with same flag id should fail
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Another feature",
                "description": 'Boondoogle your hicks AGAIN with one click. Just click "bazinga"!',
                "stage": "beta",
                "feature_flag_id": flag.id,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response_data

        self.assertEqual(
            response_data["detail"],
            "Linked feature flag hick-bondoogling already has a feature attached to it.",
        )

    def test_can_edit_feature(self):
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Click counter",
            description="A revolution in usability research: now you can count clicks!",
            stage="beta",
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            data={
                "name": "Mouse-up counter",
                "description": "Oops, we made a mistake, it actually only counts mouse-up events.",
            },
            format="json",
        )
        response_data = response.json()

        feature.refresh_from_db()
        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["name"] == "Mouse-up counter"
        assert response_data["description"] == "Oops, we made a mistake, it actually only counts mouse-up events."
        assert response_data["stage"] == "beta"
        assert feature.name == "Mouse-up counter"

    def test_can_list_features(self):
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Click counter",
            description="A revolution in usability research: now you can count clicks!",
            stage="beta",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/")
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data == {
            "count": 1,
            "next": None,
            "previous": None,
            "results": [
                {
                    "created_at": ANY,
                    "description": "A revolution in usability research: now you can count clicks!",
                    "documentation_url": "",
                    "feature_flag": None,
                    "id": ANY,
                    "name": "Click counter",
                    "payload": {},
                    "stage": "beta",
                    "user_access_level": "editor",
                },
            ],
        }

    def test_can_create_early_access_feature_with_payload(self):
        payload = {"key": "value", "nested": {"inner": "data", "number": 42}}
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Feature with payload",
                "description": "A feature with a custom payload",
                "stage": "beta",
                "payload": payload,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["payload"] == payload
        feature = EarlyAccessFeature.objects.get(id=response_data["id"])
        assert feature.payload == payload

    def test_can_create_early_access_feature_without_payload_defaults_to_empty_dict(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Feature without payload",
                "description": "A feature without a payload",
                "stage": "beta",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert response_data["payload"] == {}

        feature = EarlyAccessFeature.objects.get(id=response_data["id"])
        assert feature.payload == {}

    def test_can_update_payload(self):
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Feature",
            description="A feature",
            stage="beta",
            payload={"old": "data"},
        )

        new_payload = {"new": "payload", "updated": True, "count": 123}
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            data={"payload": new_payload},
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["payload"] == new_payload
        feature.refresh_from_db()
        assert feature.payload == new_payload

    def test_can_update_payload_to_empty_dict(self):
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Feature",
            description="A feature",
            stage="beta",
            payload={"existing": "data"},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            data={"payload": {}},
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["payload"] == {}
        feature.refresh_from_db()
        assert feature.payload == {}

    def test_payload_in_list_response(self):
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Feature with payload",
            description="A feature",
            stage="beta",
            payload={"custom": "data", "number": 42},
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Feature without payload",
            description="Another feature",
            stage="beta",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/")
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["count"] == 2
        payloads = [result["payload"] for result in response_data["results"]]
        assert {"custom": "data", "number": 42} in payloads
        assert {} in payloads

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_creation_context_is_set_to_early_access_features(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
            },
            format="json",
        )
        response_data = response.json()
        ff_instance = FeatureFlag.objects.get(id=response_data["feature_flag"]["id"])
        mock_report_user_action.assert_called_once_with(
            ANY,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": ff_instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
                "creation_context": "early_access_features",
            },
            team=ANY,
            request=ANY,
        )

    @patch("posthog.tasks.early_access_feature.send_events_for_early_access_feature_stage_change.delay")
    def test_send_events_for_early_access_feature_stage_change_fires_on_stage_change(self, mock_celery_task):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "CeleryTestFeature",
                "description": "Test firing celery task",
                "stage": EarlyAccessFeature.Stage.CONCEPT,
            },
            format="json",
        )
        feature_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={"stage": EarlyAccessFeature.Stage.BETA},
            format="json",
        )

        mock_celery_task.assert_called_once_with(
            str(feature_id),
            "concept",
            "beta",
        )

    def test_create_early_access_feature_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={
                "name": "Hick bondoogling",
                "description": 'Boondoogle your hicks with one click. Just click "bazinga"!',
                "stage": "concept",
                "_create_in_folder": "Special Folder/Early Access",
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_201_CREATED, response_data
        feature_id = response_data["id"]
        assert EarlyAccessFeature.objects.filter(id=feature_id).exists()
        assert FeatureFlag.objects.filter(id=response_data["feature_flag"]["id"]).exists()

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(
            team=self.team,
            ref=str(feature_id),
            type="early_access_feature",
        ).first()

        assert fs_entry is not None, "FileSystem entry not found for the newly created Early Access Feature."
        assert "Special Folder/Early Access" in fs_entry.path, (
            f"Expected 'Special Folder/Early Access' in {fs_entry.path}"
        )


class TestPreviewList(BaseTest, QueryMatchingTest):
    def setUp(self):
        cache.clear()
        super().setUp()
        # it is really important to know that /decide is CSRF exempt. Enforce checking in the client
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)

    def _get_features(
        self,
        token=None,
        origin="http://127.0.0.1:8000",
        ip="127.0.0.1",
    ):
        return self.client.get(
            f"/api/early_access_features/",
            data={"token": token or self.team.api_token},
            headers={"origin": origin},
            REMOTE_ADDR=ip,
        )

    @snapshot_postgres_queries
    def test_early_access_features(self):
        create_person(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            created_by=self.user,
        )
        feature_flag2 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket2",
            created_by=self.user,
        )
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="beta",
            feature_flag=feature_flag,
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="alpha",
            feature_flag=feature_flag2,
        )

        self.client.logout()

        with self.assertNumQueries(2):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

            self.assertListEqual(
                response.json()["earlyAccessFeatures"],
                [
                    {
                        "id": str(feature.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "beta",
                        "documentationUrl": "",
                        "payload": {},
                        "flagKey": "sprocket",
                    }
                ],
            )

    @snapshot_postgres_queries
    def test_early_access_features_with_pre_env_cached_team(self):
        create_person(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        # This is precisely what the `set_team_in_cache()` would have set on Dec 9, 2024
        cache.set(
            f"team_token:{self.team.api_token}",
            json.dumps(
                {
                    # Important: this serialization doesn't have `project_id`! It wasn't always part of CachingTeamSerializer
                    "id": self.team.id,
                    "uuid": str(self.team.uuid),
                    "name": self.team.name,
                    "api_token": self.team.api_token,
                }
            ),
        )
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            created_by=self.user,
        )
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="beta",
            feature_flag=feature_flag,
        )

        self.client.logout()

        with self.assertNumQueries(1):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

            self.assertListEqual(
                response.json()["earlyAccessFeatures"],
                [
                    {
                        "id": str(feature.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "beta",
                        "documentationUrl": "",
                        "payload": {},
                        "flagKey": "sprocket",
                    }
                ],
            )

    @snapshot_postgres_queries
    def test_early_access_features_with_cached_team(self):
        create_person(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        # Slightly dirty to use the actual implementation of `set_team_in_cache()` here, but this tests how things are
        set_team_in_cache(self.team.api_token)
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            created_by=self.user,
        )
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="beta",
            feature_flag=feature_flag,
        )

        self.client.logout()

        with self.assertNumQueries(1):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

            self.assertListEqual(
                response.json()["earlyAccessFeatures"],
                [
                    {
                        "id": str(feature.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "beta",
                        "documentationUrl": "",
                        "payload": {},
                        "flagKey": "sprocket",
                    }
                ],
            )

    def test_early_access_features_beta_only(self):
        create_person(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            created_by=self.user,
        )
        feature_flag2 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket2",
            created_by=self.user,
        )
        feature_flag3 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket3",
            created_by=self.user,
        )
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="beta",
            feature_flag=feature_flag,
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="alpha",
            feature_flag=feature_flag2,
        )
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="draft",
            feature_flag=feature_flag3,
        )

        self.client.logout()

        with self.assertNumQueries(2):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

            self.assertListEqual(
                response.json()["earlyAccessFeatures"],
                [
                    {
                        "id": str(feature.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "beta",
                        "documentationUrl": "",
                        "payload": {},
                        "flagKey": "sprocket",
                    }
                ],
            )

    def test_early_access_features_errors_out_on_random_token(self):
        self.client.logout()

        with self.assertNumQueries(1):
            response = self._get_features(token="random_token")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["detail"],
                "Project token invalid. You can find your project token in PostHog project settings.",
            )

    def test_early_access_features_errors_out_on_no_token(self):
        self.client.logout()

        with self.assertNumQueries(0):
            response = self.client.get(f"/api/early_access_features/")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["detail"],
                "Project token not provided. You can find your project token in PostHog project settings.",
            )

    def test_early_access_features_preserves_documentation_url(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="Feature Flag for Docs Test",
            key="docs-test",
            created_by=self.user,
        )
        documentation_url = "https://docs.example.com/features/sprocket?version=2&lang=en#getting-started"
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="Docs Feature",
            description="Feature with docs link.",
            stage="beta",
            feature_flag=feature_flag,
            documentation_url=documentation_url,
        )

        self.client.logout()

        response = self._get_features()
        self.assertEqual(response.status_code, 200)
        feature_data = response.json()["earlyAccessFeatures"][0]
        self.assertEqual(
            feature_data["documentationUrl"],
            documentation_url,
        )

    @snapshot_postgres_queries
    def test_early_access_features_includes_payload_in_preview(self):
        create_person(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            created_by=self.user,
        )
        payload = {"customKey": "customValue", "nested": {"data": 123}}
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            name="Sprocket",
            description="A fancy new sprocket.",
            stage="beta",
            feature_flag=feature_flag,
            payload=payload,
        )

        self.client.logout()

        with self.assertNumQueries(2):
            response = self._get_features()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get("access-control-allow-origin"), "http://127.0.0.1:8000")

            self.assertListEqual(
                response.json()["earlyAccessFeatures"],
                [
                    {
                        "id": str(feature.id),
                        "name": "Sprocket",
                        "description": "A fancy new sprocket.",
                        "stage": "beta",
                        "documentationUrl": "",
                        "payload": payload,
                        "flagKey": "sprocket",
                    }
                ],
            )


class TestEarlyAccessFeatureScopeWarning(PersonalAPIKeysBaseTest, APIBaseTest):
    CREATE_PAYLOAD = {
        "name": "Scope warning feature",
        "description": "x",
        "stage": "concept",
    }

    def setUp(self):
        super().setUp()
        self.key.scopes = ["early_access_feature:write"]
        self.key.save()
        self.auth_headers = {"authorization": f"Bearer {self.value}"}

    def _warning_events(self, mock_logger):
        return [
            call
            for call in mock_logger.warning.call_args_list
            if call.args and call.args[0] == "feature_flag_write_via_other_scope"
        ]

    def _create_feature(self, **extra):
        return self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={**self.CREATE_PAYLOAD, **extra},
            format="json",
            headers=self.auth_headers,
        )

    def test_create_with_early_access_feature_write_only_logs_warning(self):
        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self._create_feature()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        events = self._warning_events(mock_logger)
        assert len(events) == 1
        extra = events[0].kwargs
        assert extra["action"] == "early_access_feature.create"
        assert extra["team_id"] == self.team.id
        assert extra["scopes"] == ["early_access_feature:write"]
        assert extra["auth_kind"] == "personal_api_key"
        assert extra["auth_id"] == self.key.id

    def test_create_with_feature_flag_write_does_not_log(self):
        self.key.scopes = ["early_access_feature:write", "feature_flag:write"]
        self.key.save()
        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self._create_feature()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert self._warning_events(mock_logger) == []

    def test_create_with_wildcard_scope_does_not_log(self):
        self.key.scopes = ["*"]
        self.key.save()
        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self._create_feature()
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert self._warning_events(mock_logger) == []

    def test_update_with_stage_change_logs_warning(self):
        self.key.scopes = ["*"]
        self.key.save()
        feature_id = self._create_feature().json()["id"]
        self.key.scopes = ["early_access_feature:write"]
        self.key.save()

        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/early_access_feature/{feature_id}/",
                data={"stage": "beta"},
                format="json",
                headers=self.auth_headers,
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        events = self._warning_events(mock_logger)
        assert len(events) == 1
        assert events[0].kwargs["action"] == "early_access_feature.stage_change"

    def test_update_without_stage_change_does_not_log(self):
        self.key.scopes = ["*"]
        self.key.save()
        feature_id = self._create_feature().json()["id"]
        self.key.scopes = ["early_access_feature:write"]
        self.key.save()

        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/early_access_feature/{feature_id}/",
                data={"description": "updated"},
                format="json",
                headers=self.auth_headers,
            )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._warning_events(mock_logger) == []

    def test_destroy_logs_warning(self):
        self.key.scopes = ["*"]
        self.key.save()
        feature_id = self._create_feature().json()["id"]
        self.key.scopes = ["early_access_feature:write"]
        self.key.save()

        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self.client.delete(
                f"/api/projects/{self.team.id}/early_access_feature/{feature_id}/",
                headers=self.auth_headers,
            )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        events = self._warning_events(mock_logger)
        assert len(events) == 1
        assert events[0].kwargs["action"] == "early_access_feature.destroy"

    def test_session_auth_does_not_log(self):
        self.client.force_login(self.user)
        with patch("products.feature_flags.backend.api.feature_flag.scope_audit_logger") as mock_logger:
            response = self.client.post(
                f"/api/projects/{self.team.id}/early_access_feature/",
                data=self.CREATE_PAYLOAD,
                format="json",
            )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert self._warning_events(mock_logger) == []


class TestEarlyAccessFeatureScopeEnforcement(PersonalAPIKeysBaseTest, APIBaseTest):
    # Enforcement (raise 403) is gated behind a rollout flag; force it on for this class.
    CREATE_PAYLOAD = {
        "name": "Scope enforcement feature",
        "description": "x",
        "stage": "concept",
    }

    def setUp(self):
        super().setUp()
        self.key.scopes = ["early_access_feature:write"]
        self.key.save()
        self.auth_headers = {"authorization": f"Bearer {self.value}"}
        enforce_patcher = patch(
            "products.feature_flags.backend.api.feature_flag._is_enforce_feature_flag_write_scope_enabled",
            return_value=True,
        )
        enforce_patcher.start()
        self.addCleanup(enforce_patcher.stop)

    def _create_feature(self, **extra):
        return self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data={**self.CREATE_PAYLOAD, **extra},
            format="json",
            headers=self.auth_headers,
        )

    def _create_feature_as_admin(self):
        self.key.scopes = ["*"]
        self.key.save()
        feature_id = self._create_feature().json()["id"]
        self.key.scopes = ["early_access_feature:write"]
        self.key.save()
        return feature_id

    @parameterized.expand(
        [
            ("eaf_write_only", ["early_access_feature:write"], status.HTTP_403_FORBIDDEN),
            ("with_feature_flag_write", ["early_access_feature:write", "feature_flag:write"], status.HTTP_201_CREATED),
            ("wildcard", ["*"], status.HTTP_201_CREATED),
        ]
    )
    def test_create_scope_matrix(self, _name, scopes, expected_status):
        self.key.scopes = scopes
        self.key.save()
        response = self._create_feature()
        assert response.status_code == expected_status, response.json()
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert "feature_flag:write" in response.json()["detail"]

    def test_update_stage_change_is_denied(self):
        feature_id = self._create_feature_as_admin()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}/",
            data={"stage": "beta"},
            format="json",
            headers=self.auth_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_update_without_stage_change_is_allowed(self):
        feature_id = self._create_feature_as_admin()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}/",
            data={"description": "updated"},
            format="json",
            headers=self.auth_headers,
        )
        assert response.status_code == status.HTTP_200_OK, response.json()

    def test_create_linking_existing_flag_without_mutation_is_allowed(self):
        # Linking an existing flag at a non-active stage writes no flag row, so it is not gated.
        flag = FeatureFlag.objects.create(team=self.team, key="eaf-link-only", created_by=self.user)
        response = self._create_feature(feature_flag_id=flag.id, stage="concept")
        assert response.status_code == status.HTTP_201_CREATED, response.json()

    def test_destroy_is_denied(self):
        feature_id = self._create_feature_as_admin()
        response = self.client.delete(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}/",
            headers=self.auth_headers,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_session_auth_is_allowed(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            data=self.CREATE_PAYLOAD,
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()


class TestEarlyAccessFeatureResourceAccessControl(APIBaseTest):
    """Resource- and object-level access control for early access features."""

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        self.member = User.objects.create_and_join(self.organization, "eaf-member@posthog.com", "password")
        self.client.force_login(self.member)

    def _set_resource_level(self, access_level: str) -> None:
        AccessControl.objects.create(resource="early_access_feature", team=self.team, access_level=access_level)

    def _create_feature(self) -> EarlyAccessFeature:
        return EarlyAccessFeature.objects.create(team=self.team, name="Example feature", stage="concept")

    def _create_feature_with_flag(self) -> EarlyAccessFeature:
        # Flag created by the admin so the member is not the flag creator (creators get manager).
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="eaf-linked-flag",
            name="EAF linked flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 0}]},
        )
        return EarlyAccessFeature.objects.create(
            team=self.team, name="Linked feature", stage="concept", feature_flag=flag
        )

    def _restrict_feature_flag_access(self, access_level: str) -> None:
        AccessControl.objects.create(resource="feature_flag", team=self.team, access_level=access_level)

    @parameterized.expand([("none", status.HTTP_403_FORBIDDEN), ("viewer", status.HTTP_200_OK)])
    def test_list_access_by_resource_level(self, access_level: str, expected_status: int) -> None:
        self._set_resource_level(access_level)
        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/")
        self.assertEqual(response.status_code, expected_status)

    @parameterized.expand([("viewer", status.HTTP_403_FORBIDDEN), ("editor", status.HTTP_201_CREATED)])
    def test_create_access_by_resource_level(self, access_level: str, expected_status: int) -> None:
        self._set_resource_level(access_level)
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            {"name": f"Feature {access_level}", "stage": "concept"},
            format="json",
        )
        self.assertEqual(response.status_code, expected_status, response.json())

    @parameterized.expand([("viewer", status.HTTP_403_FORBIDDEN), ("editor", status.HTTP_200_OK)])
    def test_update_access_by_resource_level(self, access_level: str, expected_status: int) -> None:
        feature = self._create_feature()
        self._set_resource_level(access_level)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, expected_status, response.json())

    @parameterized.expand([("viewer", status.HTTP_403_FORBIDDEN), ("editor", status.HTTP_204_NO_CONTENT)])
    def test_delete_access_by_resource_level(self, access_level: str, expected_status: int) -> None:
        feature = self._create_feature()
        self._set_resource_level(access_level)
        response = self.client.delete(f"/api/projects/{self.team.id}/early_access_feature/{feature.id}")
        self.assertEqual(response.status_code, expected_status)

    def test_user_access_level_reflects_resource_level(self) -> None:
        feature = self._create_feature()
        self._set_resource_level("viewer")
        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/{feature.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # No creator concept on this model, so the effective level is the resource-level floor.
        self.assertEqual(response.json()["user_access_level"], "viewer")

    def test_user_access_level_reflects_object_level(self) -> None:
        # An object-level grant for one feature should win over the lower resource-level floor.
        feature = self._create_feature()
        self._set_resource_level("viewer")
        AccessControl.objects.create(
            resource="early_access_feature",
            resource_id=str(feature.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="editor",
        )
        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/{feature.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["user_access_level"], "editor")

    def test_access_controls_endpoint_route_exists(self) -> None:
        feature = self._create_feature()
        # Grant the member viewer so the read still exercises the access_control:read gate as a non-admin.
        self._set_resource_level("viewer")
        response = self.client.get(f"/api/projects/{self.team.id}/early_access_feature/{feature.id}/access_controls")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_manager_member_cannot_modify_object_access_controls(self) -> None:
        # Editor resource access passes write checks but does not grant manager on the object.
        feature = self._create_feature()
        self._set_resource_level("editor")
        response = self.client.put(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}/access_controls",
            {"access_level": "viewer"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_manager_can_modify_object_access_controls(self) -> None:
        # A member with manager access to the object can change its access controls.
        feature = self._create_feature()
        AccessControl.objects.create(
            resource="early_access_feature",
            resource_id=str(feature.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            team=self.team,
            access_level="manager",
        )
        response = self.client.put(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}/access_controls",
            {"access_level": "viewer"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

    def test_eaf_editor_without_feature_flag_access_cannot_create_flag(self) -> None:
        # early_access_feature editor must not bypass feature_flag access control when creating a flag.
        self._set_resource_level("editor")
        self._restrict_feature_flag_access("viewer")
        response = self.client.post(
            f"/api/projects/{self.team.id}/early_access_feature/",
            {"name": "Bypass attempt", "stage": "concept"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())

    def test_eaf_editor_without_feature_flag_access_cannot_activate_stage(self) -> None:
        # Promoting to an active stage mutates the linked flag, so it requires feature_flag editor.
        feature = self._create_feature_with_flag()
        self._set_resource_level("editor")
        self._restrict_feature_flag_access("viewer")
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            {"stage": "beta"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())

    def test_eaf_editor_without_feature_flag_access_cannot_delete_with_linked_flag(self) -> None:
        # Deleting clears the linked flag's enrollment, so it requires feature_flag editor.
        feature = self._create_feature_with_flag()
        self._set_resource_level("editor")
        self._restrict_feature_flag_access("viewer")
        response = self.client.delete(f"/api/projects/{self.team.id}/early_access_feature/{feature.id}")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_eaf_editor_with_feature_flag_access_can_activate_stage(self) -> None:
        # With the default feature_flag editor access, the linked-flag write is allowed.
        feature = self._create_feature_with_flag()
        self._set_resource_level("editor")
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature.id}",
            {"stage": "beta"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())


class TestComingSoonWaitlistSurvey(APIBaseTest):
    def _concept_feature(self, name: str = "Sloppy joes") -> EarlyAccessFeature:
        flag = FeatureFlag.objects.create(team=self.team, key=name.lower().replace(" ", "-"), created_by=self.user)
        return EarlyAccessFeature.objects.create(
            team=self.team,
            name=name,
            stage=EarlyAccessFeature.Stage.CONCEPT,
            feature_flag=flag,
        )

    def test_ensure_creates_api_survey_linked_to_flag_and_sets_payload(self):
        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature()
        survey = ensure_waitlist_survey_for_feature(feature)

        assert survey is not None
        assert survey.type == Survey.SurveyType.API
        assert survey.linked_flag_id == feature.feature_flag_id
        assert survey.questions and survey.questions[0]["type"] == "open"
        question_id = survey.questions[0]["id"]

        feature.refresh_from_db()
        assert feature.payload["survey_id"] == str(survey.id)
        assert feature.payload["survey_question_id"] == question_id

    def test_ensure_is_idempotent(self):
        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature()
        first = ensure_waitlist_survey_for_feature(feature)
        feature.refresh_from_db()
        second = ensure_waitlist_survey_for_feature(feature)

        assert second is None  # already has survey_id, nothing to do
        assert Survey.objects.filter(team=self.team, linked_flag=feature.feature_flag).count() == 1
        assert first is not None

    def test_ensure_skips_non_concept_features(self):
        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature(name="Beta thing")
        feature.stage = EarlyAccessFeature.Stage.BETA
        feature.save()

        assert ensure_waitlist_survey_for_feature(feature) is None
        assert Survey.objects.filter(team=self.team).count() == 0

    def test_ensure_appends_flag_key_when_waitlist_name_is_taken(self):
        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        from products.surveys.backend.models import Survey

        Survey.objects.create(
            team=self.team, name="Sloppy joes waitlist", type=Survey.SurveyType.POPOVER, created_by=self.user
        )
        feature = self._concept_feature(name="Sloppy joes")

        survey = ensure_waitlist_survey_for_feature(feature)

        assert survey is not None
        assert survey.name == "Sloppy joes waitlist (sloppy-joes)"
        assert survey.linked_flag_id == feature.feature_flag_id

    def test_ensure_adopts_survey_created_by_concurrent_task(self):
        # Covers only the adopt-on-IntegrityError control flow: `transaction` is mocked (a
        # TestCase already wraps the whole test in one transaction, so real savepoint and
        # advisory-lock semantics can't be exercised here) and the IntegrityError is raised
        # by the mock, not by a real constraint violation.
        from django.db import IntegrityError

        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature(name="Racy")
        real_create = Survey.objects.create

        def concurrent_create(**kwargs):
            # Simulate another worker winning the race: its survey exists by the time our
            # insert fails on the (team, name) unique constraint.
            real_create(**kwargs)
            raise IntegrityError("duplicate key value violates unique constraint")

        with (
            patch("posthog.tasks.early_access_feature.transaction"),
            patch.object(Survey.objects, "create", side_effect=concurrent_create),
        ):
            survey = ensure_waitlist_survey_for_feature(feature)

        assert survey is not None
        assert Survey.objects.filter(team=self.team, linked_flag=feature.feature_flag).count() == 1
        feature.refresh_from_db()
        assert feature.payload["survey_id"] == str(survey.id)

    def test_ensure_recheck_under_lock_adopts_survey_committed_after_first_check(self):
        # The divergent-name race: the initial linked-survey check misses, another task's
        # survey for the same flag commits before the advisory lock is taken, and without
        # the re-check under the lock this task would create a second survey under the
        # "(flag-key)" suffixed name. Simulate the stale first read and assert the re-check
        # adopts the committed survey instead of creating a duplicate.
        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature(name="Racy")
        existing = Survey.objects.create(
            team=self.team,
            name="Racy waitlist",
            type=Survey.SurveyType.API,
            linked_flag=feature.feature_flag,
            questions=[{"type": "open", "question": "q"}],
            created_by=self.user,
        )

        real_filter = Survey.objects.filter
        first_check = {"done": False}

        def stale_first_read(*args, **kwargs):
            if not first_check["done"]:
                first_check["done"] = True
                return Survey.objects.none()
            return real_filter(*args, **kwargs)

        with patch.object(Survey.objects, "filter", side_effect=stale_first_read):
            survey = ensure_waitlist_survey_for_feature(feature)

        assert survey is not None
        assert survey.id == existing.id
        assert Survey.objects.filter(team=self.team, linked_flag=feature.feature_flag).count() == 1
        feature.refresh_from_db()
        assert feature.payload["survey_id"] == str(existing.id)

    @patch("posthog.tasks.early_access_feature.create_waitlist_survey_for_concept_feature.delay")
    def test_post_save_enqueues_task_for_concept_feature(self, mock_delay):
        with self.captureOnCommitCallbacks(execute=True):
            feature = self._concept_feature(name="Signal me")

        mock_delay.assert_called_once_with(str(feature.id))

    @parameterized.expand(
        [
            ("beta_stage", EarlyAccessFeature.Stage.BETA, {}),
            ("already_has_survey", EarlyAccessFeature.Stage.CONCEPT, {"survey_id": "some-survey-id"}),
        ]
    )
    @patch("posthog.tasks.early_access_feature.create_waitlist_survey_for_concept_feature.delay")
    def test_post_save_does_not_enqueue_task(self, _name, stage, payload, mock_delay):
        flag = FeatureFlag.objects.create(team=self.team, key=f"no-enqueue-{_name}", created_by=self.user)
        with self.captureOnCommitCallbacks(execute=True):
            EarlyAccessFeature.objects.create(
                team=self.team, name=f"No enqueue {_name}", stage=stage, feature_flag=flag, payload=payload
            )

        mock_delay.assert_not_called()

    @patch("posthog.tasks.early_access_feature.coming_soon_waitlist_surveys_enabled", return_value=False)
    def test_task_does_nothing_when_flag_disabled(self, _mock_enabled):
        from posthog.tasks.early_access_feature import create_waitlist_survey_for_concept_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature(name="Gated off")
        create_waitlist_survey_for_concept_feature(str(feature.id))

        feature.refresh_from_db()
        assert not (feature.payload or {}).get("survey_id")
        assert Survey.objects.filter(team=self.team).count() == 0

    @patch("posthog.tasks.early_access_feature.coming_soon_waitlist_surveys_enabled", return_value=True)
    def test_task_creates_survey_when_flag_enabled(self, _mock_enabled):
        from posthog.tasks.early_access_feature import create_waitlist_survey_for_concept_feature

        from products.surveys.backend.models import Survey

        feature = self._concept_feature(name="Gated on")
        create_waitlist_survey_for_concept_feature(str(feature.id))

        feature.refresh_from_db()
        assert feature.payload.get("survey_id")
        assert Survey.objects.filter(team=self.team, linked_flag=feature.feature_flag).count() == 1

    @patch("posthog.tasks.early_access_feature.capture_event")
    @patch("posthog.hogql.query.execute_hogql_query")
    def test_migrate_command_skips_already_responded_emails(self, mock_query, mock_capture):
        from django.core.management import call_command

        from posthog.tasks.early_access_feature import ensure_waitlist_survey_for_feature

        feature = self._concept_feature(name="Migrate me")
        survey = ensure_waitlist_survey_for_feature(feature)
        assert survey is not None

        mock_query.side_effect = [
            # Legacy registrations: one new sign-up, one who already responded (case differs).
            MagicMock(results=[("new@example.com", "did-new"), ("Already@Example.com", "did-already")]),
            # Emails that already responded to the survey (lowercased by the query).
            MagicMock(results=[("already@example.com",)]),
        ]

        call_command("migrate_enrollments_to_waitlist_surveys", team_id=self.team.id, really_run=True)

        assert mock_capture.call_count == 1
        assert mock_capture.call_args.kwargs["distinct_id"] == "did-new"
        assert mock_capture.call_args.kwargs["properties"]["$survey_response"] == "new@example.com"
        assert mock_capture.call_args.kwargs["properties"]["$survey_id"] == str(survey.id)
