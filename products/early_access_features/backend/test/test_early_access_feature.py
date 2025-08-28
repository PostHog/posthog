import json

from posthog.test.base import APIBaseTest, BaseTest, QueryMatchingTest, snapshot_postgres_queries
from unittest.mock import ANY, patch

from django.core.cache import cache
from django.test.client import Client

from rest_framework import status

from posthog.models import FeatureFlag, Person
from posthog.models.team.team_caching import set_team_in_cache

from products.early_access_features.backend.models import EarlyAccessFeature


class TestEarlyAccessFeature(APIBaseTest):
    maxDiff = None

    def test_can_create_early_access_feature(self):
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
        assert response_data["feature_flag"]["filters"].get("super_groups", None)
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert response_data["feature_flag"]["filters"]["groups"][0]["rollout_percentage"] == 0
        assert isinstance(response_data["created_at"], str)

    def test_promote_to_beta(self):
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

        feature_id = response_data["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_feature/{feature_id}",
            data={
                "stage": EarlyAccessFeature.Stage.BETA,
            },
            format="json",
        )
        response_data = response.json()

        assert response.status_code == status.HTTP_200_OK, response_data
        assert response_data["stage"] == EarlyAccessFeature.Stage.BETA
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

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
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

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
        assert not response_data["feature_flag"]["filters"].get("super_groups", None)

    def test_update_doesnt_remove_super_condition(self):
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
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

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
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1

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
                    }
                ],
                "payloads": {"true": '"Hick bondoogling? ????"'},
                "super_groups": [
                    {
                        "properties": [
                            {
                                "key": "$feature_enrollment/hick-bondoogling",
                                "operator": "exact",
                                "type": "person",
                                "value": ["true"],
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ],
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
        assert len(response_data["feature_flag"]["filters"]["super_groups"]) == 1
        assert len(response_data["feature_flag"]["filters"]["groups"]) == 1
        assert response_data["feature_flag"]["filters"]["groups"][0]["rollout_percentage"] == 0
        assert isinstance(response_data["created_at"], str)

    def test_deleting_early_access_feature_removes_super_condition_from_flag(self):
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
                    }
                ],
                "super_groups": None,
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
                    "stage": "beta",
                },
            ],
        }

    @patch("posthog.api.feature_flag.report_user_action")
    def test_creation_context_is_set_to_early_access_features(self, mock_capture):
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
        mock_capture.assert_called_once_with(
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
        assert (
            "Special Folder/Early Access" in fs_entry.path
        ), f"Expected 'Special Folder/Early Access' in {fs_entry.path}"


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
            HTTP_ORIGIN=origin,
            REMOTE_ADDR=ip,
        )

    @snapshot_postgres_queries
    def test_early_access_features(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            rollout_percentage=0,
            created_by=self.user,
        )
        feature_flag2 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket2",
            rollout_percentage=10,
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
                        "flagKey": "sprocket",
                    }
                ],
            )

    @snapshot_postgres_queries
    def test_early_access_features_with_pre_env_cached_team(self):
        Person.objects.create(
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
            rollout_percentage=0,
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
                        "flagKey": "sprocket",
                    }
                ],
            )

    @snapshot_postgres_queries
    def test_early_access_features_with_cached_team(self):
        Person.objects.create(
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
            rollout_percentage=0,
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
                        "flagKey": "sprocket",
                    }
                ],
            )

    def test_early_access_features_beta_only(self):
        Person.objects.create(
            team=self.team,
            distinct_ids=["example_id"],
            properties={"email": "example@posthog.com"},
        )

        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket",
            rollout_percentage=0,
            created_by=self.user,
        )
        feature_flag2 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket2",
            rollout_percentage=10,
            created_by=self.user,
        )
        feature_flag3 = FeatureFlag.objects.create(
            team=self.team,
            name=f"Feature Flag for Feature Sprocket",
            key="sprocket3",
            rollout_percentage=10,
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
                "Project API key invalid. You can find your project API key in PostHog project settings.",
            )

    def test_early_access_features_errors_out_on_no_token(self):
        self.client.logout()

        with self.assertNumQueries(0):
            response = self.client.get(f"/api/early_access_features/")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json()["detail"],
                "API key not provided. You can find your project API key in PostHog project settings.",
            )
