from datetime import timedelta
from typing import Any, cast

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    flush_persons_and_events,
    snapshot_postgres_queries,
    snapshot_postgres_queries_context,
)
from unittest.mock import ANY, patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models import User
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import sort_cohorts_topologically
from products.dashboards.backend.api.dashboard import Dashboard
from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.api.organization_feature_flag import (
    EXISTING_TARGET_SCHEDULE_DEPENDENCY_WARNING,
    OrganizationFeatureFlagView,
)
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange
from products.surveys.backend.models import Survey


def _flag_dependency_property(dependency_flag: FeatureFlag, as_int: bool = False) -> dict[str, Any]:
    return {
        "key": dependency_flag.id if as_int else str(dependency_flag.id),
        "type": "flag",
        "value": "true",
        "operator": "flag_evaluates_to",
    }


def _add_release_condition_payload(properties: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "operation": "add_release_condition",
        "value": {
            "groups": [{"rollout_percentage": 100, "properties": properties}],
            "payloads": {},
            "multivariate": None,
        },
    }


class TestOrganizationFeatureFlagGet(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)
        self.team_3 = Team.objects.create(organization=self.organization)

        # Set deterministic API tokens to ensure stable query snapshots
        self.team_1.api_token = "phc_test_token_1"
        self.team_1.save()
        self.team_2.api_token = "phc_test_token_2"
        self.team_2.save()
        self.team_3.api_token = "phc_test_token_3"
        self.team_3.save()

        self.feature_flag_key = "key-1"

        self.feature_flag_1 = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key=self.feature_flag_key
        )
        self.feature_flag_2 = FeatureFlag.objects.create(
            team=self.team_2, created_by=self.user, key=self.feature_flag_key
        )
        self.feature_flag_deleted = FeatureFlag.objects.create(
            team=self.team_3, created_by=self.user, key=self.feature_flag_key, deleted=True
        )

        super().setUp()

    @snapshot_postgres_queries
    def test_get_feature_flag_success(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        expected_data = [
            {
                "flag_id": flag.id,
                "team_id": flag.team.id,
                "created_by": ANY,
                "filters": flag.get_filters(),
                "created_at": flag.created_at.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                "active": flag.active,
                "evaluations_7d": 0,
            }
            for flag in [self.feature_flag_1, self.feature_flag_2]
        ]
        self.assertCountEqual(response.json(), expected_data)

    def test_get_feature_flag_not_found(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/nonexistent-flag"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

    def test_get_feature_flag_unauthorized(self):
        self.client.logout()

        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_feature_flag_redacts_encrypted_payloads(self):
        FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="encrypted-key",
            has_encrypted_payloads=True,
            filters={"groups": [], "payloads": {"true": "ciphertext-blob"}},
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/encrypted-key"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()[0]["filters"]["payloads"]["true"], REDACTED_PAYLOAD_VALUE)

    def test_get_feature_flag_filters_inaccessible_teams(self):
        """Test that flags from teams the user cannot access are not returned."""
        from posthog.constants import AvailableFeature

        # Enable access control for the organization
        self.organization.available_product_features = [
            {
                "name": AvailableFeature.ACCESS_CONTROL,
                "key": AvailableFeature.ACCESS_CONTROL,
            }
        ]
        self.organization.save()

        # Import AccessControl for setting up private team
        from ee.models.rbac.access_control import AccessControl

        # Make team_2 private by setting default access to "none"
        AccessControl.objects.create(
            team=self.team_2,
            resource="project",
            resource_id=str(self.team_2.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only return flag from team_1, not team_2 (which is now private)
        response_data = response.json()
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["team_id"], self.team_1.id)

    def test_get_feature_flag_filters_flag_denied_by_object_level_access_control(self):
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        from ee.models.rbac.access_control import AccessControl

        # Create a second user and log in as them (not the flag creator) so that
        # the "creator is always visible" exception does not apply.
        other_user = self._create_user("other@posthog.com")
        self.client.force_login(other_user)

        # Deny the non-creator user access to feature_flag_2 at the object level.
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=str(self.feature_flag_2.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/{self.feature_flag_key}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_data = response.json()
        # Only team_1's flag should be returned; team_2's flag is denied.
        self.assertEqual(len(response_data), 1)
        self.assertEqual(response_data[0]["team_id"], self.team_1.id)


class TestOrganizationFeatureFlagKeys(APIBaseTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        # Shared key exists in both projects; each project also has a unique key.
        FeatureFlag.objects.create(team=self.team_1, created_by=self.user, key="shared")
        FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key="shared")
        FeatureFlag.objects.create(team=self.team_1, created_by=self.user, key="only-in-1")
        FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key="only-in-2")
        FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key="deleted", deleted=True)

        super().setUp()

    def _keys_url(self, **params: Any) -> str:
        url = f"/api/organizations/{self.organization.id}/feature_flags/keys/"
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}?{query}" if query else url

    def test_keys_returns_union_across_compared_projects(self):
        response = self.client.get(self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(sorted(row["key"] for row in data["results"]), ["only-in-1", "only-in-2", "shared"])

    def test_keys_excludes_deleted_flags(self):
        response = self.client.get(self._keys_url(team_ids=self.team_2.id))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        keys = [row["key"] for row in response.json()["results"]]
        self.assertNotIn("deleted", keys)
        self.assertCountEqual(keys, ["shared", "only-in-2"])

    def test_keys_redacts_encrypted_payloads(self):
        # Session reads must never receive encrypted remote-config ciphertext.
        FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="secret-config",
            has_encrypted_payloads=True,
            filters={"groups": [], "payloads": {"true": "ciphertext-blob"}},
        )

        response = self.client.get(self._keys_url(team_ids=self.team_1.id))

        row = next(r for r in response.json()["results"] if r["key"] == "secret-config")
        self.assertEqual(row["filters"]["payloads"]["true"], REDACTED_PAYLOAD_VALUE)
        self.assertNotIn("ciphertext-blob", str(row["filters"]))

    def test_keys_representative_prefers_earlier_team_in_order(self):
        # team_2 listed first -> the shared row should be represented by team_2's flag.
        response = self.client.get(self._keys_url(team_ids=self.team_2.id) + f"&team_ids={self.team_1.id}")

        shared = next(row for row in response.json()["results"] if row["key"] == "shared")
        self.assertEqual(shared["team_id"], self.team_2.id)

    def test_keys_deduplicates_team_ids_preserving_priority(self):
        # team_1 repeated at the end must not override its first-seen priority over team_2.
        response = self.client.get(
            self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&team_ids={self.team_1.id}"
        )

        shared = next(row for row in response.json()["results"] if row["key"] == "shared")
        self.assertEqual(shared["team_id"], self.team_1.id)

    def test_keys_search_picks_representative_matching_search(self):
        # Same key in both teams, but only the lower-priority team's name matches the search term.
        FeatureFlag.objects.create(team=self.team_1, created_by=self.user, key="billing-flag", name="Alpha")
        FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key="billing-flag", name="SearchTarget")

        response = self.client.get(
            self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&search=SearchTarget"
        )

        rows = response.json()["results"]
        self.assertEqual([row["key"] for row in rows], ["billing-flag"])
        self.assertEqual(rows[0]["team_id"], self.team_2.id)
        self.assertEqual(rows[0]["name"], "SearchTarget")

    def test_keys_search_filters_by_key(self):
        response = self.client.get(self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&search=only")

        keys = [row["key"] for row in response.json()["results"]]
        self.assertCountEqual(keys, ["only-in-1", "only-in-2"])

    def test_keys_paginates_distinct_keys(self):
        first = self.client.get(
            self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&limit=2&offset=0"
        )
        self.assertEqual(first.json()["count"], 3)
        self.assertEqual(len(first.json()["results"]), 2)
        self.assertIsNotNone(first.json()["next"])
        self.assertIsNone(first.json()["previous"])

        second = self.client.get(
            self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&limit=2&offset=2"
        )
        self.assertEqual(len(second.json()["results"]), 1)
        self.assertIsNone(second.json()["next"])
        self.assertIsNotNone(second.json()["previous"])

    def test_keys_pagination_urls_preserve_team_ids_and_search(self):
        # The next/previous links must carry the same team_ids and search, or paging would
        # silently switch to the wrong projects or drop the filter.
        first = self.client.get(
            self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&search=only&limit=1&offset=0"
        )
        next_url = first.json()["next"]
        self.assertIsNotNone(next_url)
        self.assertIn(f"team_ids={self.team_1.id}", next_url)
        self.assertIn(f"team_ids={self.team_2.id}", next_url)
        self.assertIn("search=only", next_url)

        second = self.client.get(
            self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}&search=only&limit=1&offset=1"
        )
        previous_url = second.json()["previous"]
        self.assertIsNotNone(previous_url)
        self.assertIn(f"team_ids={self.team_1.id}", previous_url)
        self.assertIn(f"team_ids={self.team_2.id}", previous_url)
        self.assertIn("search=only", previous_url)

    def test_keys_negative_limit_returns_400(self):
        response = self.client.get(self._keys_url(team_ids=self.team_1.id) + "&limit=-5")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # A negative limit is clamped to 1, not passed to a negative slice (which would 500).
        self.assertLessEqual(len(response.json()["results"]), 1)

    def test_keys_accepts_comma_separated_team_ids(self):
        response = self.client.get(self._keys_url(team_ids=f"{self.team_1.id},{self.team_2.id}"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(sorted(row["key"] for row in response.json()["results"]), ["only-in-1", "only-in-2", "shared"])

    def test_keys_defaults_to_all_accessible_teams_when_unspecified(self):
        response = self.client.get(self._keys_url())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        keys = [row["key"] for row in response.json()["results"]]
        self.assertCountEqual(keys, ["shared", "only-in-1", "only-in-2"])

    def test_keys_ignores_teams_outside_the_organization(self):
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org)
        FeatureFlag.objects.create(team=other_team, created_by=self.user, key="other-org-flag")

        response = self.client.get(self._keys_url(team_ids=other_team.id))

        # The team is not in this org, so it falls back to all accessible teams in the org.
        keys = [row["key"] for row in response.json()["results"]]
        self.assertNotIn("other-org-flag", keys)
        self.assertCountEqual(keys, ["shared", "only-in-1", "only-in-2"])

    def test_keys_unauthorized(self):
        self.client.logout()
        response = self.client.get(self._keys_url(team_ids=self.team_1.id))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_keys_invalid_param_returns_400(self):
        response = self.client.get(self._keys_url(team_ids=self.team_1.id) + "&limit=abc")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_keys_excludes_flags_denied_by_object_level_access_control(self):
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        from ee.models.rbac.access_control import AccessControl

        # Use a second user (not the flag creator) so the creator-always-visible
        # exception in filter_queryset_by_access_level does not apply.
        other_user = self._create_user("other-keys@posthog.com")
        self.client.force_login(other_user)

        # Deny the non-creator user access to the "shared" flag in team_2 at the object level.
        shared_flag_team2 = FeatureFlag.objects.get(team=self.team_2, key="shared")
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=str(shared_flag_team2.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        response = self.client.get(self._keys_url(team_ids=self.team_1.id) + f"&team_ids={self.team_2.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # "shared" key still appears because team_1's copy is accessible; team_2's is excluded.
        rows = response.json()["results"]
        keys = [row["key"] for row in rows]
        self.assertIn("shared", keys)
        shared_row = next(row for row in rows if row["key"] == "shared")
        # Representative must be from team_1, not team_2 (team_2's flag is denied).
        self.assertEqual(shared_row["team_id"], self.team_1.id)


class TestOrganizationFeatureFlagCopy(APIBaseTest, QueryMatchingTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        # Set deterministic API tokens to ensure stable query snapshots
        self.team_1.api_token = "phc_test_copy_token_1"
        self.team_1.save()
        self.team_2.api_token = "phc_test_copy_token_2"
        self.team_2.save()

        self.feature_flag_key = "copied-flag-key"
        self.rollout_percentage_to_copy = 65
        self.feature_flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=self.feature_flag_key,
            filters={"groups": [{"rollout_percentage": self.rollout_percentage_to_copy}]},
        )

        super().setUp()

    def _enable_access_control(self):
        from posthog.constants import AvailableFeature

        self.organization.available_product_features = [
            {
                "name": AvailableFeature.ACCESS_CONTROL,
                "key": AvailableFeature.ACCESS_CONTROL,
            }
        ]
        self.organization.save()

    @snapshot_postgres_queries
    def test_copy_feature_flag_create_new(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertIn("failed", response.json())

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": {
                "groups": [
                    {
                        "rollout_percentage": self.rollout_percentage_to_copy,
                        "aggregation_group_type_index": None,
                    }
                ],
                "aggregation_group_type_index": None,
            },
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "deleted": False,
            "archived": False,
            "created_by": ANY,
            "id": ANY,
            "created_at": ANY,
            "updated_at": ANY,
            "usage_dashboard": ANY,
            "experiment_set": [],
            "experiment_set_metadata": [],
            "surveys": [],
            "features": [],
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "analytics_dashboards": [],
            "has_enriched_analytics": False,
            "tags": [],
            "evaluation_contexts": [],
            "user_access_level": "manager",
            "is_remote_configuration": False,
            "has_encrypted_payloads": False,
            "status": "ACTIVE",
            "version": 1,
            "last_modified_by": ANY,
            "last_called_at": None,
            "evaluation_runtime": "all",
            "bucketing_identifier": "distinct_id",
            "is_used_in_replay_settings": False,
            "team_id": target_project.id,
        }

        flag_response = response.json()["success"][0]

        assert flag_response == expected_flag_response
        assert flag_response["created_by"]["id"] == self.user.id

    def test_copy_feature_flag_with_dependencies_query_count(self):
        dependency_keys = ("flag-c-query-count", "flag-b-query-count", "flag-a-query-count")
        flag_to_copy, _, _ = self._create_dependency_chain(
            "flag-a-query-count", "flag-b-query-count", "flag-c-query-count"
        )

        def dependency_target_flag_lookup(query: str) -> bool:
            return (
                'FROM "posthog_featureflag"' in query
                and '"posthog_featureflag"."key" IN' in query
                and any(dependency_key in query for dependency_key in dependency_keys)
            )

        with snapshot_postgres_queries_context(
            self, custom_query_matcher=dependency_target_flag_lookup
        ) as query_context:
            response = self._post_copy_flag(flag_to_copy, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        self.assertEqual(
            response.json()["success"][0]["copied_dependency_keys"], ["flag-c-query-count", "flag-b-query-count"]
        )
        target_team_refetches = [
            query["sql"]
            for query in query_context.captured_queries
            if 'FROM "posthog_team"' in query["sql"] and f'"posthog_team"."id" IN ({self.team_2.id})' in query["sql"]
        ]
        self.assertEqual(target_team_refetches, [])

    def test_copy_feature_flag_update_existing(self):
        target_project = self.team_2
        rollout_percentage_existing = 99

        existing_flag = FeatureFlag.objects.create(
            team=target_project,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            ensure_experience_continuity=False,
        )

        # The following instances must remain linked to the existing flag after overwriting it
        experiment = Experiment.objects.create(team=self.team_2, created_by=self.user, feature_flag_id=existing_flag.id)
        survey = Survey.objects.create(team=self.team, created_by=self.user, linked_flag=existing_flag)
        feature = EarlyAccessFeature.objects.create(
            team=self.team,
            feature_flag=existing_flag,
        )
        analytics_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )
        existing_flag.analytics_dashboards.set([analytics_dashboard])
        usage_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )
        existing_flag.usage_dashboard = usage_dashboard
        existing_flag.save()

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertIn("failed", response.json())

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": {
                "groups": [
                    {
                        "rollout_percentage": self.rollout_percentage_to_copy,
                        "aggregation_group_type_index": None,
                    }
                ],
                "aggregation_group_type_index": None,
            },
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "deleted": False,
            "archived": False,
            "created_by": ANY,
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "has_enriched_analytics": False,
            "tags": [],
            "evaluation_contexts": [],
            "id": ANY,
            "created_at": ANY,
            "updated_at": ANY,
            "usage_dashboard": ANY,
            "experiment_set": ANY,
            "experiment_set_metadata": ANY,
            "surveys": ANY,
            "features": ANY,
            "analytics_dashboards": ANY,
            "user_access_level": "manager",
            "is_remote_configuration": False,
            "has_encrypted_payloads": False,
            "status": "ACTIVE",
            "version": 2,
            "last_modified_by": ANY,
            "last_called_at": None,
            "evaluation_runtime": "all",
            "bucketing_identifier": "distinct_id",
            "is_used_in_replay_settings": False,
            "team_id": target_project.id,
        }

        flag_response = response.json()["success"][0]

        assert flag_response == expected_flag_response

        # Linked instances must remain linked
        assert flag_response["created_by"]["id"] == self.user.id
        assert experiment.id == flag_response["experiment_set"][0]
        assert str(survey.id) == flag_response["surveys"][0]["id"]
        assert str(feature.id) == flag_response["features"][0]["id"]
        assert analytics_dashboard.id == flag_response["analytics_dashboards"][0]
        assert usage_dashboard.id == flag_response["usage_dashboard"]

    def test_copy_feature_flag_restores_request_method_between_targets(self):
        target_project_with_existing_flag = self.team_2
        target_project_with_new_cohort = Team.objects.create(organization=self.organization)
        source_cohort = Cohort.objects.create(
            team=self.team_1,
            name="request-method-cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "email", "value": "test@example.com", "type": "person", "operator": "exact"},
                    ],
                }
            },
        )
        self.feature_flag_to_copy.filters = {
            "groups": [
                {
                    "rollout_percentage": self.rollout_percentage_to_copy,
                    "properties": [{"key": "id", "type": "cohort", "value": source_cohort.id}],
                }
            ]
        }
        self.feature_flag_to_copy.save()
        FeatureFlag.objects.create(
            team=target_project_with_existing_flag,
            created_by=self.user,
            key=self.feature_flag_key,
            filters={"groups": [{"rollout_percentage": 99}]},
        )

        response = self._post_copy_flag(
            self.feature_flag_to_copy,
            [target_project_with_existing_flag.id, target_project_with_new_cohort.id],
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        self.assertCountEqual(
            [flag["team_id"] for flag in response.json()["success"]],
            [target_project_with_existing_flag.id, target_project_with_new_cohort.id],
        )
        copied_cohort = Cohort.objects.get(team=target_project_with_new_cohort, name=source_cohort.name)
        copied_flag = FeatureFlag.objects.get(team=target_project_with_new_cohort, key=self.feature_flag_key)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"][0]["value"], copied_cohort.id)

    def test_copy_feature_flag_with_old_legacy_flags(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-to-copy-here",
            filters={"groups": [{"properties": [], "rollout_percentage": self.rollout_percentage_to_copy}]},
        )

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 1)
        self.assertEqual(len(response.json()["failed"]), 0)

    def test_copy_feature_flag_update_override_deleted(self):
        target_project = self.team_2
        target_project_2 = Team.objects.create(organization=self.organization)
        # Set deterministic API token for newly created team
        target_project_2.api_token = "phc_test_copy_token_3"
        target_project_2.save()
        rollout_percentage_existing = 99

        existing_deleted_flag = FeatureFlag.objects.create(
            team=target_project,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            ensure_experience_continuity=False,
            deleted=True,
        )
        existing_deleted_flag2 = FeatureFlag.objects.create(
            team=target_project_2,
            created_by=self.user,
            key=self.feature_flag_key,
            name="Existing flag",
            filters={"groups": [{"rollout_percentage": rollout_percentage_existing}]},
            ensure_experience_continuity=False,
            deleted=True,
        )

        # The following instances must be overriden for a soft-deleted flag
        Survey.objects.create(team=self.team, created_by=self.user, linked_flag=existing_deleted_flag)

        analytics_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )
        existing_deleted_flag.analytics_dashboards.set([analytics_dashboard])
        usage_dashboard = Dashboard.objects.create(
            team=self.team,
            created_by=self.user,
        )

        existing_deleted_flag.usage_dashboard = usage_dashboard
        existing_deleted_flag.save()

        # Experiments restrict deleting soft-deleted flags
        Experiment.objects.create(
            team=target_project_2, created_by=self.user, feature_flag_id=existing_deleted_flag2.id
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        data = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [target_project.id, target_project_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertIn("failed", response.json())

        # Check copied flag in the response
        expected_flag_response = {
            "key": self.feature_flag_to_copy.key,
            "name": self.feature_flag_to_copy.name,
            "filters": {
                "groups": [
                    {
                        "rollout_percentage": self.rollout_percentage_to_copy,
                        "aggregation_group_type_index": None,
                    }
                ],
                "aggregation_group_type_index": None,
            },
            "active": self.feature_flag_to_copy.active,
            "ensure_experience_continuity": self.feature_flag_to_copy.ensure_experience_continuity,
            "deleted": False,
            "archived": False,
            "created_by": ANY,
            "rollback_conditions": None,
            "performed_rollback": False,
            "can_edit": True,
            "has_enriched_analytics": False,
            "tags": [],
            "evaluation_contexts": [],
            "id": ANY,
            "created_at": ANY,
            "updated_at": ANY,
            "usage_dashboard": ANY,
            "experiment_set": ANY,
            "experiment_set_metadata": ANY,
            "surveys": ANY,
            "features": ANY,
            "analytics_dashboards": ANY,
            "user_access_level": "manager",
            "is_remote_configuration": False,
            "has_encrypted_payloads": False,
            "status": "ACTIVE",
            "version": 1,
            "last_modified_by": ANY,
            "last_called_at": None,
            "evaluation_runtime": "all",
            "bucketing_identifier": "distinct_id",
            "is_used_in_replay_settings": False,
            "team_id": target_project.id,
        }
        flag_response = response.json()["success"][0]

        assert flag_response == expected_flag_response
        assert flag_response["created_by"]["id"] == self.user.id

        # Linked instances must be overridden for a soft-deleted flag
        self.assertEqual(flag_response["experiment_set"], [])
        self.assertEqual(flag_response["surveys"], [])
        self.assertNotEqual(flag_response["usage_dashboard"], existing_deleted_flag.usage_dashboard.id)
        self.assertEqual(flag_response["analytics_dashboards"], [])

        # target_project_2 should have failed: soft-deleted flag is still referenced
        # by an active experiment (invariant violation), so the defensive guardrail fires.
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertEqual(response.json()["failed"][0]["project_id"], target_project_2.id)
        self.assertIn(
            "Cannot reuse key 'copied-flag-key'",
            response.json()["failed"][0]["error_message"],
        )
        self.assertIn(
            "referenced by active experiment(s)",
            response.json()["failed"][0]["error_message"],
        )

    @parameterized.expand(
        [
            # disable_copied_flag, pre_existing_target, expected_active
            ("disable_true_new", True, False, False),
            ("disable_true_existing", True, True, False),
            ("disable_false_new", False, False, True),
            ("disable_omitted_new", None, False, True),
        ]
    )
    def test_copy_feature_flag_disable_copied_flag(
        self, _name, disable_copied_flag, pre_existing_target, expected_active
    ):
        assert self.feature_flag_to_copy.active is True

        if pre_existing_target:
            FeatureFlag.objects.create(
                team=self.team_2,
                created_by=self.user,
                key=self.feature_flag_to_copy.key,
                active=True,
                filters={"groups": [{"rollout_percentage": 10}]},
            )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data: dict[str, Any] = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.feature_flag_to_copy.team_id,
            "target_project_ids": [self.team_2.id],
        }
        if disable_copied_flag is not None:
            data["disable_copied_flag"] = disable_copied_flag

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 1)
        self.assertEqual(response.json()["success"][0]["active"], expected_active)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_to_copy.key, team=self.team_2)
        self.assertEqual(copied_flag.active, expected_active)

        # Source flag must remain untouched
        self.feature_flag_to_copy.refresh_from_db()
        self.assertTrue(self.feature_flag_to_copy.active)

    def test_copy_feature_flag_missing_fields(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data: dict[str, Any] = {}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        body = response.json()
        self.assertEqual(body["type"], "validation_error")
        self.assertEqual(body["code"], "required")
        self.assertIn("This field is required.", body["detail"])

    def test_copy_feature_flag_nonexistent_key(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": "nonexistent-key",
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.json())

    def test_copy_feature_flag_from_other_org_returns_not_found(self):
        from posthog.models.organization import Organization

        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org)
        FeatureFlag.objects.create(team=other_team, created_by=self.user, key="other-org-flag")

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": "other-org-flag",
            "from_project": other_team.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Feature flag to copy does not exist.")

    def test_copy_feature_flag_to_nonexistent_target(self):
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        nonexistent_project_id = 999
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [nonexistent_project_id],
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 0)
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertEqual(nonexistent_project_id, response.json()["failed"][0]["project_id"])

    def test_copy_feature_flag_unauthorized(self):
        self.client.logout()
        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_copy_feature_flag_to_inaccessible_team_fails(self):
        """Test that copying a flag to a team the user cannot access fails."""
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()

        # Make team_2 private by setting default access to "none"
        AccessControl.objects.create(
            team=self.team_2,
            resource="project",
            resource_id=str(self.team_2.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 0)
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertEqual(response.json()["failed"][0]["project_id"], self.team_2.id)
        self.assertEqual(response.json()["failed"][0]["error_message"], "Project not found.")

    def test_copy_feature_flag_to_target_without_feature_flag_create_access_fails(self):
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()
        copying_user = self._create_user("copy-target-create-denied@posthog.com")
        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="source-parent",
            active=True,
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="copy-needs-target-create-access",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_dependency)]}
                ]
            },
        )
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=None,
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        requirements_response = self._post_dependency_requirements(flag_to_copy)
        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertFalse(requirements["can_copy_dependencies"])
        self.assertIn("permission", requirements["reason"])
        self.assertEqual(requirements["copied_dependency_keys"], [])

        response = self._post_copy_flag(flag_to_copy, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["success"], [])
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertIn("permission", response.json()["failed"][0]["error_message"])
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=source_dependency.key).exists())
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_to_copy.key).exists())

    def test_copy_feature_flag_with_dependencies_succeeds_for_allowed_target_when_another_target_is_denied(self):
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()
        copying_user = self._create_user("copy-mixed-target-create-access@posthog.com")
        allowed_target = Team.objects.create(organization=self.organization)
        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="mixed-target-parent",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="mixed-target-dependent",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_dependency)]}
                ]
            },
        )
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=None,
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        response = self._post_copy_flag(
            flag_to_copy,
            [allowed_target.id, self.team_2.id],
            copy_dependencies=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(len(body["success"]), 1)
        self.assertEqual(body["success"][0]["team_id"], allowed_target.id)
        self.assertEqual(body["success"][0]["copied_dependency_keys"], [source_dependency.key])
        self.assertEqual(len(body["failed"]), 1)
        self.assertEqual(body["failed"][0]["project_id"], self.team_2.id)
        self.assertIn("permission", body["failed"][0]["error_message"])
        self.assertTrue(FeatureFlag.objects.filter(team=allowed_target, key=source_dependency.key).exists())
        self.assertTrue(FeatureFlag.objects.filter(team=allowed_target, key=flag_to_copy.key).exists())
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=source_dependency.key).exists())
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_to_copy.key).exists())

    def test_copy_feature_flag_does_not_update_object_denied_target_flag(self):
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()
        copying_user = self._create_user("copy-target-object-denied@posthog.com")
        source_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="object-denied-target",
            active=True,
            filters={"groups": [{"rollout_percentage": 25}]},
        )
        existing_target_flag = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=source_flag.key,
            active=True,
            filters={"groups": [{"rollout_percentage": 99}]},
        )
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=str(existing_target_flag.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        response = self._post_copy_flag(source_flag)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["success"], [])
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertIn("permission", response.json()["failed"][0]["error_message"])
        existing_target_flag.refresh_from_db()
        self.assertEqual(existing_target_flag.filters["groups"][0]["rollout_percentage"], 99)

    def test_copy_feature_flag_to_target_outside_route_organization_fails(self):
        other_organization = Organization.objects.create(name="Other organization")
        other_team = Team.objects.create(organization=other_organization)
        self.user.join(organization=other_organization)
        self.user.current_organization = self.organization
        self.user.current_team = self.team_1
        self.user.save()
        self.client.force_login(self.user)

        response = self._post_copy_flag(self.feature_flag_to_copy, [other_team.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["success"], [])
        self.assertEqual(
            response.json()["failed"], [{"project_id": other_team.id, "error_message": "Project not found."}]
        )
        self.assertFalse(FeatureFlag.objects.filter(team=other_team, key=self.feature_flag_key).exists())

    def test_copy_feature_flag_cohort_nonexistent_in_destination(self):
        cohorts = {}
        creation_order = []

        def create_cohort(name, children):
            creation_order.append(name)
            properties = [{"key": "$some_prop", "value": "nomatchihope", "type": "person", "operator": "exact"}]
            if children:
                properties = [{"key": "id", "type": "cohort", "value": child.pk} for child in children]

            cohorts[name] = Cohort.objects.create(
                team=self.team,
                name=str(name),
                filters={
                    "properties": {
                        "type": "AND",
                        "values": properties,
                    }
                },
            )

        # link cohorts
        create_cohort(1, None)
        create_cohort(3, None)
        create_cohort(2, [cohorts[1]])
        create_cohort(4, [cohorts[2], cohorts[3]])
        create_cohort(5, [cohorts[4]])
        create_cohort(6, None)
        create_cohort(7, [cohorts[5], cohorts[6]])  # "head" cohort

        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-with-cohort",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": cohorts[7].pk,  # link "head" cohort
                            }
                        ],
                    }
                ]
            },
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # check all cohorts were created in the destination project
        for name in creation_order:
            found_cohort = Cohort.objects.filter(name=str(name), team_id=target_project.id).exists()
            self.assertTrue(found_cohort)

    def test_copy_feature_flag_cohort_nonexistent_in_destination_2(self):
        feature_flag_key = "flag-with-cohort"
        cohorts = {}

        def create_cohort(name):
            cohorts[name] = Cohort.objects.create(
                team=self.team,
                name=name,
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "name", "value": "test", "type": "person", "operator": "exact"},
                        ],
                    }
                },
            )

        create_cohort("a")
        create_cohort("b")
        create_cohort("c")
        create_cohort("d")

        def connect(parent, child):
            cohorts[parent].filters["properties"]["values"][0] = {
                "key": "id",
                "value": cohorts[child].pk,
                "type": "cohort",
            }
            cohorts[parent].save()

        connect("d", "b")
        connect("a", "d")
        connect("c", "a")

        head_cohort = cohorts["c"]
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=feature_flag_key,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": head_cohort.pk,  # link "head" cohort
                            }
                        ],
                    }
                ]
            },
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        target_project = self.team_2

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # check all cohorts were created in the destination project
        for name in cohorts.keys():
            found_cohort = Cohort.objects.filter(name=name, team_id=target_project.id)[0]
            self.assertTrue(found_cohort)

        # destination flag contains the head cohort
        destination_flag = FeatureFlag.objects.get(key=feature_flag_key, team_id=target_project.id)
        destination_flag_head_cohort_id = destination_flag.filters["groups"][0]["properties"][0]["value"]
        destination_head_cohort = Cohort.objects.get(pk=destination_flag_head_cohort_id, team_id=target_project.id)
        self.assertEqual(destination_head_cohort.name, head_cohort.name)
        self.assertNotEqual(destination_head_cohort.id, head_cohort.id)

        # get topological order of the original cohorts
        original_cohorts_cache = {}
        for _, cohort in cohorts.items():
            original_cohorts_cache[cohort.id] = cohort
        original_cohort_ids = set(original_cohorts_cache.keys())
        topologically_sorted_original_cohort_ids = sort_cohorts_topologically(
            original_cohort_ids, original_cohorts_cache
        )

        # drill down the destination cohorts in the reverse topological order
        # the order of names should match the reverse topological order of the original cohort names
        topologically_sorted_original_cohort_ids_reversed = topologically_sorted_original_cohort_ids[::-1]

        def traverse(cohort, index):
            expected_cohort_id = topologically_sorted_original_cohort_ids_reversed[index]
            expected_name = original_cohorts_cache[expected_cohort_id].name
            self.assertEqual(expected_name, cohort.name)

            prop = cohort.filters["properties"]["values"][0]
            if prop["type"] == "cohort":
                next_cohort_id = prop["value"]
                next_cohort = Cohort.objects.get(pk=next_cohort_id, team_id=target_project.id)
                traverse(next_cohort, index + 1)

        traverse(destination_head_cohort, 0)

    def test_copy_feature_flag_destination_cohort_not_overridden(self):
        cohort_name = "cohort-1"
        target_project = self.team_2
        original_cohort = Cohort.objects.create(
            team=self.team,
            name=cohort_name,
            groups=[{"properties": [{"key": "$some_prop", "value": "original_value", "type": "person"}]}],
        )

        destination_cohort_prop_value = "destination_value"
        Cohort.objects.create(
            team=target_project,
            name=cohort_name,
            groups=[{"properties": [{"key": "$some_prop", "value": destination_cohort_prop_value, "type": "person"}]}],
        )

        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-with-cohort",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 20,
                        "properties": [
                            {
                                "key": "id",
                                "type": "cohort",
                                "value": original_cohort.pk,
                            }
                        ],
                    }
                ]
            },
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

        data = {
            "feature_flag_key": flag_to_copy.key,
            "from_project": flag_to_copy.team_id,
            "target_project_ids": [target_project.id],
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        destination_cohort = Cohort.objects.filter(name=cohort_name, team=target_project).first()
        self.assertTrue(destination_cohort is not None)
        # check destination value not overwritten

        if destination_cohort is not None:
            self.assertTrue(destination_cohort.groups[0]["properties"][0]["value"] == destination_cohort_prop_value)

    def _copy_flags_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"

    def _dependency_requirements_url(self) -> str:
        return f"{self._copy_flags_url()}/dependency_requirements"

    def _post_copy_flag(
        self,
        feature_flag: FeatureFlag,
        target_project_ids: list[int] | None = None,
        **overrides: Any,
    ) -> Any:
        data: dict[str, Any] = {
            "feature_flag_key": feature_flag.key,
            "from_project": feature_flag.team_id,
            "target_project_ids": target_project_ids if target_project_ids is not None else [self.team_2.id],
        }
        data.update(overrides)
        return self.client.post(self._copy_flags_url(), data)

    def _post_dependency_requirements(
        self,
        feature_flag: FeatureFlag,
        target_project_ids: list[int] | None = None,
    ) -> Any:
        return self.client.post(
            self._dependency_requirements_url(),
            {
                "feature_flag_key": feature_flag.key,
                "from_project": feature_flag.team_id,
                "target_project_ids": target_project_ids if target_project_ids is not None else [self.team_2.id],
            },
        )

    def _create_dependency_chain(self, *keys: str) -> list[FeatureFlag]:
        next_dependency: FeatureFlag | None = None
        flags_by_key: dict[str, FeatureFlag] = {}

        for key in reversed(keys):
            properties: list[dict[str, Any]] = (
                [self._flag_dependency_property(next_dependency)] if next_dependency else []
            )
            flag = FeatureFlag.objects.create(
                team=self.team_1,
                created_by=self.user,
                key=key,
                active=True,
                filters={"groups": [{"rollout_percentage": 100, "properties": properties}]},
            )
            flags_by_key[key] = flag
            next_dependency = flag

        return [flags_by_key[key] for key in keys]

    def _flag_dependency_property(self, dependency_flag, as_int=False):
        return _flag_dependency_property(dependency_flag, as_int=as_int)

    @parameterized.expand(
        [
            ("copy_flags", "copy_flags"),
            ("dependency_requirements", "dependency_requirements"),
        ]
    )
    def test_copy_feature_flag_source_project_denied_returns_not_found(self, _name, endpoint):
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()
        copying_user = self._create_user("copy-source-project-denied@posthog.com")
        AccessControl.objects.create(
            team=self.team_1,
            resource="project",
            resource_id=str(self.team_1.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        if endpoint == "dependency_requirements":
            response = self._post_dependency_requirements(self.feature_flag_to_copy)
        else:
            response = self._post_copy_flag(self.feature_flag_to_copy)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not exist", response.json()["error"])
        self.assertNotIn(self.feature_flag_key, response.content.decode())
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=self.feature_flag_key).exists())

    @parameterized.expand(
        [
            ("copy_flags", "copy_flags"),
            ("dependency_requirements", "dependency_requirements"),
        ]
    )
    def test_copy_feature_flag_source_object_denied_returns_forbidden(self, _name, endpoint):
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()
        copying_user = self._create_user("copy-source-object-denied@posthog.com")
        AccessControl.objects.create(
            team=self.team_1,
            resource="feature_flag",
            resource_id=str(self.feature_flag_to_copy.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        if endpoint == "dependency_requirements":
            response = self._post_dependency_requirements(self.feature_flag_to_copy)
        else:
            response = self._post_copy_flag(self.feature_flag_to_copy)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("permission", response.json()["error"])
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=self.feature_flag_key).exists())

    @parameterized.expand(
        [
            # name, target_parent_active (None = no same-key flag in target), include_sibling_prop,
            # expected_warning_substring (None = remapped, no warning), expected_active, expected_remaining_types
            ("present_and_active", True, False, None, True, ["flag"]),
            ("missing_with_sibling", None, True, "no flag with that key", False, ["person"]),
            ("missing_only_property", None, False, "no flag with that key", False, []),
            ("disabled_in_target", False, False, "disabled", False, []),
        ]
    )
    def test_copy_feature_flag_remaps_or_drops_dependency(
        self,
        _name,
        target_parent_active,
        include_sibling_prop,
        expected_warning_substring,
        expected_active,
        expected_remaining_types,
    ):
        target_project = self.team_2

        source_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="parent-flag", active=True
        )
        target_parent = None
        if target_parent_active is not None:
            # Same-key parent in the target project, created with a different ID than the source
            target_parent = FeatureFlag.objects.create(
                team=target_project, created_by=self.user, key="parent-flag", active=target_parent_active
            )

        properties = [self._flag_dependency_property(source_parent)]
        if include_sibling_prop:
            properties.append({"key": "$some_prop", "value": "x", "type": "person", "operator": "exact"})

        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": properties}]},
        )

        response = self._post_copy_flag(dependent_flag, [target_project.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["failed"]), 0)
        success = response.json()["success"][0]

        copied_flag = FeatureFlag.objects.get(key="dependent-flag", team_id=target_project.id)
        remaining = copied_flag.filters["groups"][0].get("properties", [])
        self.assertEqual([prop["type"] for prop in remaining], expected_remaining_types)
        self.assertEqual(copied_flag.active, expected_active)

        if expected_warning_substring is None:
            # Dependency remapped to the target project's parent flag; nothing dropped, copy stays active
            assert target_parent is not None
            self.assertNotIn("flag_dependency_warnings", success)
            self.assertEqual(remaining[0]["key"], str(target_parent.id))
        else:
            # Dependency dropped: a warning is surfaced and the copy is forced inactive for review
            self.assertIn("flag_dependency_warnings", success)
            self.assertIn(expected_warning_substring, success["flag_dependency_warnings"][0])

    def test_copy_feature_flag_drops_disabled_source_dependency_even_when_target_same_key_flag_is_active(self):
        source_parent = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="disabled-source-parent",
            active=False,
        )
        target_parent = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=source_parent.key,
            active=True,
        )
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-on-disabled-source",
            active=True,
            filters={
                "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_parent)]}]
            },
        )

        requirements_response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertFalse(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], [])
        self.assertEqual(requirements["reused_dependency_keys"], [])
        self.assertIn("disabled in the source project", requirements["reason"])

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertIn("disabled in the source project", success["flag_dependency_warnings"][0])

        target_parent.refresh_from_db()
        self.assertTrue(target_parent.active)
        copied_flag = FeatureFlag.objects.get(key=dependent_flag.key, team=self.team_2)
        self.assertFalse(copied_flag.active)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"], [])

    def test_copy_feature_flag_drops_unresolved_dependency_when_dependency_map_is_empty(self):
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": "999999999",
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            }
                        ],
                    }
                ]
            },
        )

        response = self._post_copy_flag(dependent_flag, [self.team_2.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertIn("flag_dependency_warnings", success)
        self.assertIn("could not be resolved", success["flag_dependency_warnings"][0])

        copied_flag = FeatureFlag.objects.get(key="dependent-flag", team=self.team_2)
        self.assertFalse(copied_flag.active)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"], [])

    def test_copy_feature_flag_remaps_int_keyed_dependency(self):
        # Dependencies are usually stored as string keys, so the int-key branch of the remap is
        # otherwise untested — assert it remaps and normalizes to the string key shape used downstream.
        target_project = self.team_2
        source_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="parent-flag", active=True
        )
        target_parent = FeatureFlag.objects.create(
            team=target_project, created_by=self.user, key="parent-flag", active=True
        )
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [self._flag_dependency_property(source_parent, as_int=True)],
                    }
                ]
            },
        )

        response = self._post_copy_flag(dependent_flag, [target_project.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["failed"]), 0)
        copied_flag = FeatureFlag.objects.get(key="dependent-flag", team_id=target_project.id)
        remapped_key = copied_flag.filters["groups"][0]["properties"][0]["key"]
        self.assertEqual(remapped_key, str(target_parent.id))
        self.assertTrue(copied_flag.active)

    def test_copy_feature_flag_with_multiple_dependencies_in_one_group(self):
        # A group with two flag dependencies: one present-and-active in the target (remapped), one
        # missing (dropped). Exactly one warning should be surfaced and only the active one kept.
        target_project = self.team_2
        present_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="present-parent", active=True
        )
        target_present_parent = FeatureFlag.objects.create(
            team=target_project, created_by=self.user, key="present-parent", active=True
        )
        missing_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="missing-parent", active=True
        )

        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            self._flag_dependency_property(present_parent),
                            self._flag_dependency_property(missing_parent),
                        ],
                    }
                ]
            },
        )

        response = self._post_copy_flag(dependent_flag, [target_project.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["failed"]), 0)
        success = response.json()["success"][0]

        copied_flag = FeatureFlag.objects.get(key="dependent-flag", team_id=target_project.id)
        remaining = copied_flag.filters["groups"][0]["properties"]
        # Only the present dependency survives, remapped to the target's parent ID
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["key"], str(target_present_parent.id))
        # The dropped dependency yields exactly one warning (the group still has the kept dependency,
        # so no "group now matches everyone" warning is added)
        self.assertEqual(len(success["flag_dependency_warnings"]), 1)
        self.assertIn("missing-parent", success["flag_dependency_warnings"][0])
        # A dependency was dropped, so the copy is forced inactive for review even though the
        # remapped dependency still gates the group.
        self.assertFalse(copied_flag.active)

    def test_copy_feature_flag_remaps_dependency_per_target_without_leak(self):
        # Each target has its own same-key parent under a different ID. The remap runs on a per-target
        # deep copy of the filters, so each copy must point at its own target's parent and stay active.
        target_1 = self.team_2
        target_2 = Team.objects.create(organization=self.organization)
        source_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="parent-flag", active=True
        )
        parent_in_1 = FeatureFlag.objects.create(team=target_1, created_by=self.user, key="parent-flag", active=True)
        parent_in_2 = FeatureFlag.objects.create(team=target_2, created_by=self.user, key="parent-flag", active=True)
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_parent)]}]
            },
        )

        response = self._post_copy_flag(dependent_flag, [target_1.id, target_2.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["failed"]), 0)
        for success in response.json()["success"]:
            self.assertNotIn("flag_dependency_warnings", success)

        copied_1 = FeatureFlag.objects.get(key="dependent-flag", team_id=target_1.id)
        copied_2 = FeatureFlag.objects.get(key="dependent-flag", team_id=target_2.id)
        self.assertEqual(copied_1.filters["groups"][0]["properties"][0]["key"], str(parent_in_1.id))
        self.assertEqual(copied_2.filters["groups"][0]["properties"][0]["key"], str(parent_in_2.id))
        self.assertTrue(copied_1.active)
        self.assertTrue(copied_2.active)

    def test_copy_remote_config_flag_preserves_type(self):
        """Test that copying a remote config flag preserves the is_remote_configuration field."""
        target_project = self.team_2

        remote_config_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="remote-config-flag",
            filters={"groups": [{"rollout_percentage": 100}], "payloads": {"true": '{"key": "value"}'}},
            is_remote_configuration=True,
            has_encrypted_payloads=False,
        )

        response = self._post_copy_flag(remote_config_flag, [target_project.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertEqual(len(response.json()["success"]), 1)

        flag_response = response.json()["success"][0]
        self.assertEqual(flag_response["is_remote_configuration"], True)
        self.assertEqual(flag_response["has_encrypted_payloads"], False)
        self.assertEqual(flag_response["key"], remote_config_flag.key)

        # Verify the flag in the database
        copied_flag = FeatureFlag.objects.get(key=remote_config_flag.key, team=target_project)
        self.assertTrue(copied_flag.is_remote_configuration)
        self.assertFalse(copied_flag.has_encrypted_payloads)

    def test_copy_encrypted_payloads_flag(self):
        """Test that copying a flag with encrypted payloads decrypts them before copying."""
        from products.feature_flags.backend.encrypted_flag_payloads import encrypt_flag_payloads

        target_project = self.team_2

        # Create a flag with encrypted payloads
        flag_data = {
            "groups": [{"rollout_percentage": 100}],
            "payloads": {"true": '{"key": "secret_value"}'},
        }
        encrypt_flag_payloads({"has_encrypted_payloads": True, "filters": flag_data})

        encrypted_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="encrypted-flag",
            filters=flag_data,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        response = self._post_copy_flag(encrypted_flag, [target_project.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertEqual(len(response.json()["success"]), 1)

        flag_response = response.json()["success"][0]
        self.assertEqual(flag_response["is_remote_configuration"], True)
        self.assertEqual(flag_response["has_encrypted_payloads"], True)
        self.assertEqual(flag_response["key"], encrypted_flag.key)

        # Verify the flag in the database has encrypted payloads
        copied_flag = FeatureFlag.objects.get(key=encrypted_flag.key, team=target_project)
        self.assertTrue(copied_flag.is_remote_configuration)
        self.assertTrue(copied_flag.has_encrypted_payloads)

        # Verify the encrypted payload can be decrypted back to the original value
        from products.feature_flags.backend.encrypted_flag_payloads import get_decrypted_flag_payload

        decrypted_payload = get_decrypted_flag_payload(copied_flag.filters["payloads"]["true"], should_decrypt=True)
        self.assertEqual(decrypted_payload, '{"key": "secret_value"}')

    def test_copy_encrypted_payloads_flag_to_multiple_projects(self):
        """Test that copying a flag with encrypted payloads to multiple projects works correctly."""
        from products.feature_flags.backend.encrypted_flag_payloads import (
            encrypt_flag_payloads,
            get_decrypted_flag_payload,
        )

        # Create third team for testing multiple targets
        team_3 = Team.objects.create(organization=self.organization)
        team_3.api_token = "phc_test_copy_token_3"
        team_3.save()

        # Create a flag with encrypted payloads
        flag_data = {
            "groups": [{"rollout_percentage": 100}],
            "payloads": {"true": '{"key": "secret_value"}'},
        }
        encrypt_flag_payloads({"has_encrypted_payloads": True, "filters": flag_data})

        encrypted_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="encrypted-multi-flag",
            filters=flag_data,
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

        response = self._post_copy_flag(encrypted_flag, [self.team_2.id, team_3.id])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("success", response.json())
        self.assertEqual(len(response.json()["success"]), 2)

        # Verify both copied flags have correctly encrypted payloads
        for target_team in [self.team_2, team_3]:
            copied_flag = FeatureFlag.objects.get(key=encrypted_flag.key, team=target_team)
            self.assertTrue(copied_flag.is_remote_configuration)
            self.assertTrue(copied_flag.has_encrypted_payloads)

            # Verify the encrypted payload can be decrypted back to the original value
            decrypted_payload = get_decrypted_flag_payload(copied_flag.filters["payloads"]["true"], should_decrypt=True)
            self.assertEqual(decrypted_payload, '{"key": "secret_value"}')

    def test_copy_feature_flag_dependency_requirements_returns_no_dependencies(self):
        response = self._post_dependency_requirements(self.feature_flag_to_copy)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertFalse(body["can_copy_dependencies"])
        self.assertEqual(body["dependency_count"], 0)
        self.assertEqual(body["copied_dependency_keys"], [])
        self.assertEqual(body["reused_dependency_keys"], [])
        self.assertEqual(body["warnings"], [])
        self.assertIn("doesn't have dependencies", body["reason"])

    def test_copy_feature_flag_dependency_requirements_returns_missing_dependencies(self):
        flag_a, _, _ = self._create_dependency_chain("flag-a", "flag-b", "flag-c")

        response = self._post_dependency_requirements(flag_a)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertTrue(body["can_copy_dependencies"])
        self.assertEqual(body["dependency_count"], 2)
        self.assertEqual(body["copied_dependency_keys"], ["flag-c", "flag-b"])
        self.assertEqual(body["reused_dependency_keys"], [])

    def test_copy_feature_flag_rejects_more_than_50_target_projects(self):
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-to-copy",
            active=True,
        )
        target_project_ids = list(range(51))

        requirements_response = self._post_dependency_requirements(flag_to_copy, target_project_ids)
        copy_response = self._post_copy_flag(flag_to_copy, target_project_ids)

        self.assertEqual(requirements_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(copy_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no more than 50", requirements_response.content.decode())
        self.assertIn("no more than 50", copy_response.content.decode())

    def test_copy_feature_flag_dependency_requirements_returns_disabled_target_blocker(self):
        source_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="parent-flag", active=True
        )
        FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key="parent-flag", active=False)
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_parent)]}]
            },
        )

        response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertFalse(body["can_copy_dependencies"])
        self.assertEqual(body["copied_dependency_keys"], [])
        self.assertEqual(body["reused_dependency_keys"], [])
        self.assertIn("disabled in the target project", body["reason"])
        self.assertEqual(body["warnings"], [body["reason"]])

    def test_copy_feature_flag_with_dependencies_copies_direct_dependency_even_when_intermediate_is_reused(self):
        flag_c = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-c",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-b",
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(flag_c)]}]},
        )
        flag_a = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-a",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            self._flag_dependency_property(flag_b),
                            self._flag_dependency_property(flag_c),
                        ],
                    }
                ]
            },
        )
        target_b = FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key="flag-b", active=True)

        requirements_response = self._post_dependency_requirements(flag_a)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertTrue(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], ["flag-c"])
        self.assertEqual(requirements["reused_dependency_keys"], ["flag-b"])

        response = self._post_copy_flag(flag_a, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        self.assertEqual(response.json()["success"][0]["copied_dependency_keys"], ["flag-c"])

        copied_c = FeatureFlag.objects.get(team=self.team_2, key="flag-c")
        copied_a = FeatureFlag.objects.get(team=self.team_2, key="flag-a")
        copied_dependency_keys = [prop["key"] for prop in copied_a.filters["groups"][0]["properties"]]
        self.assertEqual(copied_dependency_keys, [str(target_b.id), str(copied_c.id)])

    def test_copy_feature_flag_with_dependencies_ignores_restricted_transitive_dependency_under_reused_target(self):
        from ee.models.rbac.access_control import AccessControl

        self._enable_access_control()
        copying_user = self._create_user("copy-reused-branch-restricted-child@posthog.com")
        flag_c = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-c",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_b = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-b",
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(flag_c)]}]},
        )
        flag_d = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-d",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_a = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="flag-a",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            self._flag_dependency_property(flag_b),
                            self._flag_dependency_property(flag_d),
                        ],
                    }
                ]
            },
        )
        target_b = FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key=flag_b.key, active=True)
        target_c = FeatureFlag.objects.create(team=self.team_2, created_by=self.user, key=flag_c.key, active=True)
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=str(target_c.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        requirements_response = self._post_dependency_requirements(flag_a)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertTrue(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], [flag_d.key])
        self.assertEqual(requirements["reused_dependency_keys"], [flag_b.key])
        self.assertEqual(requirements["warnings"], [])

        response = self._post_copy_flag(flag_a, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertEqual(success["copied_dependency_keys"], [flag_d.key])
        self.assertNotIn("flag_dependency_warnings", success)
        self.assertNotIn("dependency_copy_warnings", success)

        copied_d = FeatureFlag.objects.get(team=self.team_2, key=flag_d.key)
        copied_a = FeatureFlag.objects.get(team=self.team_2, key=flag_a.key)
        copied_dependency_keys = [prop["key"] for prop in copied_a.filters["groups"][0]["properties"]]
        self.assertEqual(copied_dependency_keys, [str(target_b.id), str(copied_d.id)])
        self.assertTrue(copied_a.active)

    def test_copy_feature_flag_with_dependencies_copies_transitive_graph_dependency_first(self):
        flag_a, _, _ = self._create_dependency_chain("flag-a", "flag-b", "flag-c")

        response = self._post_copy_flag(flag_a, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        self.assertEqual(response.json()["success"][0]["copied_dependency_keys"], ["flag-c", "flag-b"])

        copied_c = FeatureFlag.objects.get(team=self.team_2, key="flag-c")
        copied_b = FeatureFlag.objects.get(team=self.team_2, key="flag-b")
        copied_a = FeatureFlag.objects.get(team=self.team_2, key="flag-a")

        self.assertEqual(copied_b.filters["groups"][0]["properties"][0]["key"], str(copied_c.id))
        self.assertEqual(copied_a.filters["groups"][0]["properties"][0]["key"], str(copied_b.id))
        self.assertTrue(copied_a.active)
        self.assertTrue(copied_b.active)
        self.assertTrue(copied_c.active)

    def test_copy_feature_flag_with_dependencies_preserves_dependency_active_state_when_root_copy_disabled(self):
        flag_a, flag_b = self._create_dependency_chain("flag-a", "flag-b")

        response = self._post_copy_flag(
            flag_a,
            copy_dependencies=True,
            disable_copied_flag=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])

        copied_a = FeatureFlag.objects.get(team=self.team_2, key=flag_a.key)
        copied_b = FeatureFlag.objects.get(team=self.team_2, key=flag_b.key)
        self.assertFalse(copied_a.active)
        self.assertTrue(copied_b.active)
        self.assertEqual(copied_a.filters["groups"][0]["properties"][0]["key"], str(copied_b.id))

    def test_copy_feature_flag_with_dependencies_preserves_key_based_dependency_reference(self):
        source_parent = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="parent-flag",
            active=True,
        )
        target_parent = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=source_parent.key,
            active=True,
        )
        key_based_dependency = self._flag_dependency_property(source_parent)
        key_based_dependency["key"] = source_parent.key
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": [key_based_dependency]}]},
        )

        requirements_response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertEqual(requirements["dependency_count"], 1)
        self.assertFalse(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], [])
        self.assertEqual(requirements["reused_dependency_keys"], [source_parent.key])
        self.assertEqual(requirements["warnings"], [])

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertNotIn("copied_dependency_keys", success)
        self.assertNotIn("flag_dependency_warnings", success)

        copied_flag = FeatureFlag.objects.get(team=self.team_2, key=dependent_flag.key)
        self.assertTrue(copied_flag.active)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"][0]["key"], str(target_parent.id))

    def test_copy_feature_flag_with_dependencies_preserves_numeric_key_based_dependency_reference(self):
        source_parent = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="temporary-parent",
            active=True,
        )
        numeric_dependency_key = str(source_parent.id + 1000000)
        source_parent.key = numeric_dependency_key
        source_parent.save(update_fields=["key"])
        target_parent = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=numeric_dependency_key,
            active=True,
        )
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": numeric_dependency_key,
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            }
                        ],
                    }
                ]
            },
        )

        requirements_response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertEqual(requirements["dependency_count"], 1)
        self.assertFalse(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], [])
        self.assertEqual(requirements["reused_dependency_keys"], [numeric_dependency_key])
        self.assertEqual(requirements["warnings"], [])

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertNotIn("copied_dependency_keys", success)
        self.assertNotIn("flag_dependency_warnings", success)

        copied_flag = FeatureFlag.objects.get(team=self.team_2, key=dependent_flag.key)
        self.assertTrue(copied_flag.active)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"][0]["key"], str(target_parent.id))

    def test_copy_feature_flag_with_dependencies_prefers_id_over_numeric_key_collision(self):
        id_matched_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="id-matched-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        key_matched_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=str(id_matched_flag.id),
            active=True,
        )
        target_numeric_key_flag = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=key_matched_flag.key,
            active=True,
        )
        dependency = self._flag_dependency_property(id_matched_flag)
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": [dependency]}]},
        )

        requirements_response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertTrue(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["dependency_count"], 1)
        self.assertEqual(requirements["copied_dependency_keys"], [id_matched_flag.key])
        self.assertEqual(requirements["reused_dependency_keys"], [])
        self.assertEqual(requirements["warnings"], [])

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertEqual(success["copied_dependency_keys"], [id_matched_flag.key])

        copied_dependency = FeatureFlag.objects.get(team=self.team_2, key=id_matched_flag.key)
        copied_flag = FeatureFlag.objects.get(team=self.team_2, key=dependent_flag.key)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"][0]["key"], str(copied_dependency.id))
        self.assertNotEqual(copied_flag.filters["groups"][0]["properties"][0]["key"], str(target_numeric_key_flag.id))

    def test_copy_feature_flag_with_dependencies_does_not_reuse_restricted_target_dependency(self):
        from posthog.constants import AvailableFeature

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        copying_user = self._create_user("copy-restricted-target-dependencies@posthog.com")

        source_parent = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="restricted-target-parent",
            active=True,
        )
        target_parent = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=source_parent.key,
            active=True,
        )
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_parent)]}]
            },
        )
        AccessControl.objects.create(
            team=self.team_2,
            resource="feature_flag",
            resource_id=str(target_parent.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        requirements_response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertFalse(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], [])
        self.assertEqual(requirements["reused_dependency_keys"], [])
        self.assertIn("restricted", requirements["reason"])
        self.assertNotIn(source_parent.key, requirements_response.content.decode())

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertNotIn("copied_dependency_keys", success)
        self.assertIn("restricted", success["flag_dependency_warnings"][0])
        self.assertNotIn(source_parent.key, response.content.decode())

        copied_flag = FeatureFlag.objects.get(team=self.team_2, key=dependent_flag.key)
        self.assertFalse(copied_flag.active)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"], [])

    def test_copy_feature_flag_with_dependencies_leaves_disabled_same_key_target_dependency(self):
        source_parent = FeatureFlag.objects.create(
            team=self.team_1, created_by=self.user, key="parent-flag", active=True
        )
        target_parent = FeatureFlag.objects.create(
            team=self.team_2, created_by=self.user, key="parent-flag", active=False
        )
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_parent)]}]
            },
        )
        ScheduledChange.objects.create(
            record_id=str(dependent_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": True}},
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True, copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        target_parent.refresh_from_db()
        self.assertFalse(target_parent.active)

        success = response.json()["success"][0]
        self.assertNotIn("copied_dependency_keys", success)
        self.assertIn("disabled in the target project", success["flag_dependency_warnings"][0])
        self.assertIn("Skipped scheduled changes", success["schedule_copy_warning"])
        copied_flag = FeatureFlag.objects.get(team=self.team_2, key="dependent-flag")
        self.assertFalse(copied_flag.active)
        self.assertFalse(
            ScheduledChange.objects.filter(
                record_id=str(copied_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
            ).exists()
        )

    def test_copy_feature_flag_with_dependencies_copies_unblocked_dependency_when_one_target_dependency_disabled(self):
        disabled_source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="disabled-target-parent",
            active=True,
            filters={"groups": [{"rollout_percentage": 25}]},
        )
        missing_source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="missing-parent",
            active=True,
            filters={"groups": [{"rollout_percentage": 50}]},
        )
        target_disabled_dependency = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=disabled_source_dependency.key,
            active=False,
            filters={"groups": [{"rollout_percentage": 75}]},
        )
        dependent_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="mixed-dependency-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            self._flag_dependency_property(disabled_source_dependency),
                            self._flag_dependency_property(missing_source_dependency),
                        ],
                    }
                ]
            },
        )

        requirements_response = self._post_dependency_requirements(dependent_flag)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        requirements = requirements_response.json()
        self.assertTrue(requirements["can_copy_dependencies"])
        self.assertEqual(requirements["copied_dependency_keys"], [missing_source_dependency.key])
        self.assertEqual(requirements["reused_dependency_keys"], [])
        self.assertIn("disabled in the target project", requirements["warnings"][0])
        self.assertIn("Some dependencies will be left unchanged", requirements["reason"])

        response = self._post_copy_flag(dependent_flag, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        success = response.json()["success"][0]
        self.assertEqual(success["copied_dependency_keys"], [missing_source_dependency.key])
        self.assertIn("disabled in the target project", success["flag_dependency_warnings"][0])

        target_disabled_dependency.refresh_from_db()
        self.assertFalse(target_disabled_dependency.active)
        copied_dependency = FeatureFlag.objects.get(team=self.team_2, key=missing_source_dependency.key)
        copied_flag = FeatureFlag.objects.get(team=self.team_2, key=dependent_flag.key)
        self.assertFalse(copied_flag.active)
        self.assertEqual(copied_flag.filters["groups"][0]["properties"][0]["key"], str(copied_dependency.id))

    def test_copy_feature_flag_with_more_than_50_dependencies_returns_400(self):
        previous_dependency = None
        for index in range(51):
            properties: list[dict[str, Any]] = (
                [self._flag_dependency_property(previous_dependency)] if previous_dependency else []
            )
            previous_dependency = FeatureFlag.objects.create(
                team=self.team_1,
                created_by=self.user,
                key=f"dependency-{index}",
                active=True,
                filters={"groups": [{"rollout_percentage": 100, "properties": properties}]},
            )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="flag-with-too-many-dependencies",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(previous_dependency)]}
                ]
            },
        )

        response = self._post_copy_flag(flag_to_copy, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["error"],
            "This flag depends on more than 50 flags, so dependencies can't be copied automatically. Copy the flag without dependencies or reduce the dependency chain.",
        )
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_to_copy.key).exists())

    def test_copy_feature_flag_with_dependency_cycle_returns_400(self):
        flag_a = FeatureFlag.objects.create(team=self.team_1, created_by=self.user, key="flag-a", active=True)
        flag_b = FeatureFlag.objects.create(team=self.team_1, created_by=self.user, key="flag-b", active=True)
        flag_a.filters = {
            "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(flag_b)]}]
        }
        flag_a.save()
        flag_b.filters = {
            "groups": [{"rollout_percentage": 100, "properties": [self._flag_dependency_property(flag_a)]}]
        }
        flag_b.save()

        response = self._post_copy_flag(flag_a, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json()["error"],
            "A circular flag dependency was detected, so dependencies can't be copied automatically. Copy the flag without dependencies or remove the cycle first.",
        )
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_a.key).exists())

    def test_copy_feature_flag_dependency_failure_rolls_back_only_that_target(self):
        successful_target = Team.objects.create(organization=self.organization)
        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependency-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_dependency)]}
                ]
            },
        )
        blocked_tombstone = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=source_dependency.key,
            deleted=True,
        )
        Experiment.objects.create(team=self.team_2, created_by=self.user, feature_flag_id=blocked_tombstone.id)

        response = self._post_copy_flag(
            flag_to_copy,
            target_project_ids=[self.team_2.id, successful_target.id],
            copy_dependencies=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 1)
        self.assertEqual(response.json()["success"][0]["key"], flag_to_copy.key)
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertEqual(response.json()["failed"][0]["project_id"], self.team_2.id)

        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_to_copy.key).exists())
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=source_dependency.key).exists())
        self.assertTrue(FeatureFlag.objects.filter(team=successful_target, key=flag_to_copy.key).exists())
        self.assertTrue(FeatureFlag.objects.filter(team=successful_target, key=source_dependency.key).exists())

    def test_copy_feature_flag_with_dependencies_does_not_update_dependency_created_during_copy(self):
        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependency-created-during-copy",
            active=True,
            filters={"groups": [{"rollout_percentage": 10}]},
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-created-during-copy",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_dependency)]}
                ]
            },
        )
        original_get_existing_target_flag_for_copy = OrganizationFeatureFlagView._get_existing_target_flag_for_copy

        def create_target_dependency_before_copy(
            view: OrganizationFeatureFlagView,
            user: User,
            source_flag: FeatureFlag,
            target_team: Team,
            update_existing_target: bool = True,
        ) -> FeatureFlag | None:
            if source_flag.key == source_dependency.key and target_team == self.team_2:
                FeatureFlag.objects.get_or_create(
                    team=self.team_2,
                    key=source_dependency.key,
                    defaults={
                        "created_by": self.user,
                        "active": True,
                        "filters": {"groups": [{"rollout_percentage": 99}]},
                    },
                )
            return original_get_existing_target_flag_for_copy(
                view, user, source_flag, target_team, update_existing_target=update_existing_target
            )

        with patch.object(
            OrganizationFeatureFlagView,
            "_get_existing_target_flag_for_copy",
            autospec=True,
            side_effect=create_target_dependency_before_copy,
        ):
            response = self._post_copy_flag(flag_to_copy, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["success"], [])
        self.assertEqual(len(response.json()["failed"]), 1)
        self.assertIn("already exists", response.json()["failed"][0]["error_message"])
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_to_copy.key).exists())

    def test_copy_feature_flag_with_dependencies_copies_dependency_schedules(self):
        source_nested_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="nested-dependency-flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependency-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [self._flag_dependency_property(source_nested_dependency)],
                    }
                ]
            },
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_dependency)]}
                ]
            },
        )
        ScheduledChange.objects.create(
            record_id=str(source_dependency.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload=_add_release_condition_payload([self._flag_dependency_property(source_nested_dependency)]),
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(flag_to_copy, copy_dependencies=True, copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        copied_dependency = FeatureFlag.objects.get(team=self.team_2, key=source_dependency.key)
        copied_nested_dependency = FeatureFlag.objects.get(team=self.team_2, key=source_nested_dependency.key)
        self.assertEqual(
            ScheduledChange.objects.filter(
                record_id=str(copied_dependency.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
            ).count(),
            1,
        )
        copied_schedule = ScheduledChange.objects.get(
            record_id=str(copied_dependency.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        schedule_dependency_key = copied_schedule.payload["value"]["groups"][0]["properties"][0]["key"]
        self.assertEqual(schedule_dependency_key, str(copied_nested_dependency.id))
        self.assertNotEqual(schedule_dependency_key, str(source_nested_dependency.id))

    def test_copy_feature_flag_with_dependency_denied_returns_forbidden(self):
        from posthog.constants import AvailableFeature

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        copying_user = self._create_user("copy-dependencies@posthog.com")

        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="dependency-flag",
            active=True,
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": "hidden-child-dependency",
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            }
                        ],
                    }
                ]
            },
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="dependent-flag",
            active=True,
            filters={
                "groups": [
                    {"rollout_percentage": 100, "properties": [self._flag_dependency_property(source_dependency)]}
                ]
            },
        )
        AccessControl.objects.create(
            team=self.team_1,
            resource="feature_flag",
            resource_id=str(source_dependency.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        requirements_response = self._post_dependency_requirements(flag_to_copy)

        self.assertEqual(requirements_response.status_code, status.HTTP_200_OK)
        self.assertFalse(requirements_response.json()["can_copy_dependencies"])
        self.assertIn("dependency flags", requirements_response.json()["reason"])
        self.assertNotIn(source_dependency.key, requirements_response.content.decode())
        self.assertNotIn("hidden-child-dependency", requirements_response.content.decode())

        response = self._post_copy_flag(flag_to_copy, copy_dependencies=True)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("dependency flags", response.json()["error"])
        self.assertNotIn(source_dependency.key, response.content.decode())
        self.assertNotIn("hidden-child-dependency", response.content.decode())
        self.assertFalse(FeatureFlag.objects.filter(team=self.team_2, key=flag_to_copy.key).exists())


class TestOrganizationFeatureFlagCopyPersonalAPIKey(APIBaseTest):
    """Verify the `copy_flags` action accepts personal API keys with `feature_flag:write` scope.

    The viewset declares `scope_object = "INTERNAL"`, which would normally block all personal
    API key access. The action-level `required_scopes=["feature_flag:write"]` overrides that gate
    for this single action while keeping the rest of the viewset INTERNAL.
    """

    CONFIG_AUTO_LOGIN = False

    def setUp(self):
        super().setUp()
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        self.feature_flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="key-to-copy",
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        self.url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        self.body = {
            "feature_flag_key": self.feature_flag_to_copy.key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }

    def _create_key(
        self,
        scopes: list[str],
        scoped_organizations: list[str] | None = None,
        scoped_teams: list[int] | None = None,
    ) -> str:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="test",
            user=self.user,
            secure_value=hash_key_value(value),
            scopes=scopes,
            scoped_organizations=scoped_organizations or [],
            scoped_teams=scoped_teams or [],
        )
        return value

    def _post_with_key(self, value: str):
        return self.client.post(self.url, self.body, headers={"authorization": f"Bearer {value}"})

    def test_allows_personal_api_key_with_feature_flag_write_scope(self):
        value = self._create_key(scopes=["feature_flag:write"])

        response = self._post_with_key(value)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["success"]) == 1
        assert len(response.json()["failed"]) == 0

    @parameterized.expand(
        [
            # Read scope cannot satisfy a write-scoped action.
            ("read_scope_only", ["feature_flag:read"], False),
            # `*` consent intentionally does not satisfy INTERNAL viewsets even when the
            # action declares explicit `required_scopes`. See posthog/permissions.py:498-499.
            ("wildcard_scope_on_internal_viewset", ["*"], False),
            # Team-scoped keys cannot reach org-level endpoints. The user must use an
            # org-scoped or unscoped key. Confirms `check_team_and_org_permissions` at
            # posthog/permissions.py:541-552 still gates this behind explicit team membership.
            ("team_scoped_key", ["feature_flag:write"], True),
        ]
    )
    def test_rejects_insufficient_or_overly_scoped_key(self, _name, scopes, scoped_to_team):
        scoped_teams = [self.team_1.id] if scoped_to_team else None
        value = self._create_key(scopes=scopes, scoped_teams=scoped_teams)

        response = self._post_with_key(value)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_rejects_cross_organization_personal_api_key(self):
        # A key scoped to a different org than the source flag's org should be rejected.
        other_organization, _, _ = Organization.objects.bootstrap(self.user)
        value = self._create_key(
            scopes=["feature_flag:write"],
            scoped_organizations=[str(other_organization.id)],
        )

        response = self._post_with_key(value)

        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestOrganizationFeatureFlagCopySchedules(APIBaseTest):
    def setUp(self):
        self.team_1 = self.team
        self.team_2 = Team.objects.create(organization=self.organization)

        self.team_1.api_token = "phc_test_schedule_token_1"
        self.team_1.save()
        self.team_2.api_token = "phc_test_schedule_token_2"
        self.team_2.save()

        self.feature_flag_key = "flag-with-schedules"
        self.feature_flag = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key=self.feature_flag_key,
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        super().setUp()

    def _post_copy_flag(self, **overrides: Any) -> Any:
        data: dict[str, Any] = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
        }
        data.update(overrides)
        return self.client.post(f"/api/organizations/{self.organization.id}/feature_flags/copy_flags", data)

    def test_copy_flag_without_schedules(self):
        """Copying a flag without copy_schedule=True should not copy schedules."""
        scheduled_time = timezone.now() + timedelta(days=1)
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            team=self.team_1,
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
            "copy_schedule": False,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 1)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        target_schedules = ScheduledChange.objects.filter(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        self.assertEqual(target_schedules.count(), 0)

    def test_copy_flag_with_dropped_dependency_warns_about_existing_target_schedule(self):
        source_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="current-parent-flag",
            active=True,
        )
        self.feature_flag.filters = {
            "groups": [
                {
                    "rollout_percentage": 50,
                    "properties": [_flag_dependency_property(source_dependency)],
                }
            ]
        }
        self.feature_flag.save()
        existing_target_flag = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=self.feature_flag_key,
            active=True,
            filters={"groups": [{"rollout_percentage": 10}]},
        )
        ScheduledChange.objects.create(
            record_id=str(existing_target_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": True}},
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_2,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=False)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        result = response.json()["success"][0]
        self.assertIn("flag_dependency_warnings", result)
        self.assertIn("schedule_copy_warning", result)
        self.assertIn("Pending scheduled changes already attached", result["schedule_copy_warning"])

        existing_target_flag.refresh_from_db()
        self.assertFalse(existing_target_flag.active)
        self.assertEqual(result["id"], existing_target_flag.id)
        self.assertEqual(
            ScheduledChange.objects.filter(
                record_id=str(existing_target_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
                executed_at__isnull=True,
            ).count(),
            1,
        )

    def test_copy_flag_warns_about_existing_target_schedule_without_dependency_warnings(self):
        existing_target_flag = FeatureFlag.objects.create(
            team=self.team_2,
            created_by=self.user,
            key=self.feature_flag_key,
            active=True,
            filters={"groups": [{"rollout_percentage": 10}]},
        )
        ScheduledChange.objects.create(
            record_id=str(existing_target_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_2,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=False)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["failed"], [])
        result = response.json()["success"][0]
        self.assertNotIn("flag_dependency_warnings", result)
        self.assertIn("schedule_copy_warning", result)
        self.assertIn(EXISTING_TARGET_SCHEDULE_DEPENDENCY_WARNING, result["schedule_copy_warning"])
        self.assertEqual(result["id"], existing_target_flag.id)
        self.assertEqual(
            ScheduledChange.objects.filter(
                record_id=str(existing_target_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
                executed_at__isnull=True,
            ).count(),
            1,
        )

    def test_copy_flag_with_single_schedule(self):
        """Copying a flag with copy_schedule=True should copy the schedule."""
        scheduled_time = timezone.now() + timedelta(days=1)
        source_schedule = ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            team=self.team_1,
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
            "copy_schedule": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 1)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        target_schedules = ScheduledChange.objects.filter(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        self.assertEqual(target_schedules.count(), 1)

        copied_schedule = target_schedules.first()
        self.assertEqual(copied_schedule.payload, source_schedule.payload)
        self.assertEqual(copied_schedule.scheduled_at, source_schedule.scheduled_at)
        self.assertEqual(copied_schedule.created_by, self.user)

    def test_copy_flag_with_multiple_schedules(self):
        """Copying a flag should copy all pending schedules."""
        scheduled_time_1 = timezone.now() + timedelta(days=1)
        scheduled_time_2 = timezone.now() + timedelta(days=2)

        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time_1,
            team=self.team_1,
            created_by=self.user,
        )
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": True}},
            scheduled_at=scheduled_time_2,
            team=self.team_1,
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
            "copy_schedule": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        target_schedules = ScheduledChange.objects.filter(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        self.assertEqual(target_schedules.count(), 2)

    def test_copy_flag_does_not_copy_executed_schedules(self):
        """Only pending schedules should be copied, not executed ones."""
        scheduled_time = timezone.now() + timedelta(days=1)

        # Create a pending schedule
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            team=self.team_1,
            created_by=self.user,
            executed_at=None,
        )

        # Create an already executed schedule
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": True}},
            scheduled_at=timezone.now() - timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
            executed_at=timezone.now(),
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
            "copy_schedule": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        target_schedules = ScheduledChange.objects.filter(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        # Only the pending schedule should be copied
        self.assertEqual(target_schedules.count(), 1)

    def test_copy_flag_with_recurring_schedule(self):
        """Recurring schedules should preserve their recurrence settings."""
        scheduled_time = timezone.now() + timedelta(days=1)
        end_date = timezone.now() + timedelta(days=30)

        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            is_recurring=True,
            recurrence_interval="weekly",
            end_date=end_date,
            team=self.team_1,
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id],
            "copy_schedule": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        copied_schedule = ScheduledChange.objects.get(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        self.assertTrue(copied_schedule.is_recurring)
        self.assertEqual(copied_schedule.recurrence_interval, "weekly")
        self.assertEqual(copied_schedule.end_date, end_date)

    def test_copy_flag_with_cron_recurring_schedule(self):
        scheduled_time = timezone.now() + timedelta(days=1)
        end_date = timezone.now() + timedelta(days=30)
        source_schedule = ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            is_recurring=True,
            cron_expression="0 9 * * 1-5",
            timezone="America/New_York",
            end_date=end_date,
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        copied_schedule = ScheduledChange.objects.get(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        self.assertTrue(copied_schedule.is_recurring)
        self.assertEqual(copied_schedule.cron_expression, source_schedule.cron_expression)
        self.assertEqual(copied_schedule.timezone, source_schedule.timezone)
        self.assertEqual(copied_schedule.end_date, source_schedule.end_date)

    @parameterized.expand(
        [
            ("canonical_value", "value"),
            ("legacy_filters", "filters"),
        ]
    )
    def test_copy_flag_with_schedule_containing_cohort(self, _name, filter_payload_key):
        """Schedule payloads with cohort references should be remapped to target project cohorts."""
        source_cohort = Cohort.objects.create(
            team=self.team_1,
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "email", "value": "@example.com", "type": "person", "operator": "icontains"}],
                }
            },
        )

        scheduled_time = timezone.now() + timedelta(days=1)
        filters: dict[str, Any] = {
            "groups": [
                {"rollout_percentage": 100, "properties": [{"key": "id", "type": "cohort", "value": source_cohort.id}]}
            ],
            "payloads": {},
            "multivariate": None,
        }
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "add_release_condition", filter_payload_key: filters},
            scheduled_at=scheduled_time,
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify cohort was created in target project
        target_cohort = Cohort.objects.get(name="Test Cohort", team=self.team_2)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        copied_schedule = ScheduledChange.objects.get(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )

        # Verify the cohort ID in the schedule payload was remapped
        schedule_cohort_id = copied_schedule.payload[filter_payload_key]["groups"][0]["properties"][0]["value"]
        self.assertEqual(schedule_cohort_id, target_cohort.id)
        self.assertNotEqual(schedule_cohort_id, source_cohort.id)

    def test_copy_flag_with_schedule_containing_nested_cohort(self):
        source_child_cohort = Cohort.objects.create(
            team=self.team_1,
            name="Schedule Child Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "email", "value": "@example.com", "type": "person", "operator": "icontains"}],
                }
            },
        )
        source_parent_cohort = Cohort.objects.create(
            team=self.team_1,
            name="Schedule Parent Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "id", "type": "cohort", "value": source_child_cohort.id}],
                }
            },
        )
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload=_add_release_condition_payload([{"key": "id", "type": "cohort", "value": source_parent_cohort.id}]),
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        target_child_cohort = Cohort.objects.get(name="Schedule Child Cohort", team=self.team_2)
        target_parent_cohort = Cohort.objects.get(name="Schedule Parent Cohort", team=self.team_2)

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        copied_schedule = ScheduledChange.objects.get(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        schedule_parent_cohort_id = copied_schedule.payload["value"]["groups"][0]["properties"][0]["value"]
        self.assertEqual(schedule_parent_cohort_id, target_parent_cohort.id)
        self.assertNotEqual(schedule_parent_cohort_id, source_parent_cohort.id)

        target_parent_filters = cast(dict[str, Any], target_parent_cohort.filters)
        target_parent_child_cohort_id = target_parent_filters["properties"]["values"][0]["value"]
        self.assertEqual(target_parent_child_cohort_id, target_child_cohort.id)
        self.assertNotEqual(target_parent_child_cohort_id, source_child_cohort.id)

    def test_copy_flag_schedule_prefers_value_over_legacy_filters(self):
        legacy_cohort = Cohort.objects.create(
            team=self.team_1,
            name="Legacy Schedule Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "email", "value": "@legacy.com", "type": "person", "operator": "icontains"}],
                }
            },
        )
        canonical_cohort = Cohort.objects.create(
            team=self.team_1,
            name="Canonical Schedule Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "email", "value": "@canonical.com", "type": "person", "operator": "icontains"}],
                }
            },
        )
        payload = _add_release_condition_payload([{"key": "id", "type": "cohort", "value": canonical_cohort.id}])
        payload["filters"] = {
            "groups": [
                {"rollout_percentage": 100, "properties": [{"key": "id", "type": "cohort", "value": legacy_cohort.id}]}
            ]
        }
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload=payload,
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        target_canonical_cohort = Cohort.objects.get(name="Canonical Schedule Cohort", team=self.team_2)
        self.assertFalse(Cohort.objects.filter(name="Legacy Schedule Cohort", team=self.team_2).exists())

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        copied_schedule = ScheduledChange.objects.get(
            record_id=str(copied_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            team=self.team_2,
        )
        schedule_cohort_id = copied_schedule.payload["value"]["groups"][0]["properties"][0]["value"]
        self.assertEqual(schedule_cohort_id, target_canonical_cohort.id)
        self.assertNotEqual(schedule_cohort_id, canonical_cohort.id)

    @parameterized.expand(
        [
            ("missing_target_dependency", False, "no flag with that key exists"),
            ("disabled_target_dependency", True, "disabled in the target project"),
        ]
    )
    def test_copy_flag_schedule_dependency_warning_skips_unsafe_schedule(
        self, _name, create_disabled_target_dependency, expected_warning
    ):
        source_schedule_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="schedule-parent",
            active=True,
        )
        if create_disabled_target_dependency:
            FeatureFlag.objects.create(
                team=self.team_2,
                created_by=self.user,
                key=source_schedule_dependency.key,
                active=False,
            )

        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload=_add_release_condition_payload([_flag_dependency_property(source_schedule_dependency)]),
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["success"][0]
        self.assertIn("schedule_copy_warning", result)
        self.assertIn("scheduled changes had dependency warnings", result["schedule_copy_warning"])
        self.assertIn(expected_warning, result["schedule_copy_warning"])
        self.assertIn("Skipped scheduled change", result["schedule_copy_warning"])

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        self.assertFalse(
            ScheduledChange.objects.filter(
                record_id=str(copied_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
            ).exists()
        )

    def test_copy_flag_schedule_unresolved_dependency_warning_skips_unsafe_schedule(self):
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload=_add_release_condition_payload(
                [
                    {
                        "key": "999999999",
                        "type": "flag",
                        "value": "true",
                        "operator": "flag_evaluates_to",
                    }
                ]
            ),
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=self.user,
        )

        response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["success"][0]
        self.assertIn("schedule_copy_warning", result)
        self.assertIn("could not be resolved", result["schedule_copy_warning"])
        self.assertIn("Skipped scheduled change", result["schedule_copy_warning"])

        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        self.assertFalse(
            ScheduledChange.objects.filter(
                record_id=str(copied_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
            ).exists()
        )

    def test_copy_flag_schedule_dependency_denied_does_not_disclose_key(self):
        from posthog.constants import AvailableFeature

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        copying_user = self._create_user("copy-schedule-dependencies@posthog.com")

        denied_dependency = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=self.user,
            key="hidden-schedule-parent",
            active=True,
        )
        flag_to_copy = FeatureFlag.objects.create(
            team=self.team_1,
            created_by=copying_user,
            key="flag-with-denied-schedule-dependency",
            active=True,
            filters={"groups": [{"rollout_percentage": 50}]},
        )
        ScheduledChange.objects.create(
            record_id=str(flag_to_copy.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload=_add_release_condition_payload([_flag_dependency_property(denied_dependency)]),
            scheduled_at=timezone.now() + timedelta(days=1),
            team=self.team_1,
            created_by=copying_user,
        )
        AccessControl.objects.create(
            team=self.team_1,
            resource="feature_flag",
            resource_id=str(denied_dependency.id),
            organization_member=None,
            role=None,
            access_level="none",
        )
        self.client.force_login(copying_user)

        response = self._post_copy_flag(
            feature_flag_key=flag_to_copy.key,
            copy_schedule=True,
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result = response.json()["success"][0]
        self.assertIn("schedule_copy_warning", result)
        self.assertIn("scheduled flag dependencies", result["schedule_copy_warning"])
        self.assertNotIn(denied_dependency.key, response.content.decode())

        copied_flag = FeatureFlag.objects.get(key=flag_to_copy.key, team=self.team_2)
        self.assertFalse(
            ScheduledChange.objects.filter(
                record_id=str(copied_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
            ).exists()
        )

    def test_copy_flag_schedule_failure_surfaces_warning(self):
        """If schedule copying fails, the flag should still be copied with a warning."""
        scheduled_time = timezone.now() + timedelta(days=1)
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            team=self.team_1,
            created_by=self.user,
        )

        def fail_after_partial_schedule_copy(source_schedules, target_flag, user, *_args):
            ScheduledChange.objects.create(
                record_id=str(target_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                payload=source_schedules[0].payload,
                scheduled_at=source_schedules[0].scheduled_at,
                team=target_flag.team,
                created_by=user,
            )
            raise Exception("Database error")

        with patch(
            "products.feature_flags.backend.api.organization_feature_flag.OrganizationFeatureFlagView._copy_feature_flag_schedules"
        ) as mock_copy:
            mock_copy.side_effect = fail_after_partial_schedule_copy
            response = self._post_copy_flag(copy_schedule=True)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 1)
        self.assertEqual(len(response.json()["failed"]), 0)

        # Flag should still be copied
        self.assertTrue(FeatureFlag.objects.filter(key=self.feature_flag_key, team=self.team_2).exists())

        # Response should include a warning
        result = response.json()["success"][0]
        self.assertIn("schedule_copy_warning", result)
        self.assertIn("Database error", result["schedule_copy_warning"])
        copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=self.team_2)
        self.assertFalse(
            ScheduledChange.objects.filter(
                record_id=str(copied_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=self.team_2,
            ).exists()
        )

    def test_copy_flag_to_multiple_projects_with_schedules(self):
        """Schedules should be copied to all target projects."""
        team_3 = Team.objects.create(organization=self.organization)
        team_3.api_token = "phc_test_schedule_token_3"
        team_3.save()

        scheduled_time = timezone.now() + timedelta(days=1)
        ScheduledChange.objects.create(
            record_id=str(self.feature_flag.id),
            model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
            payload={"operation": "update_status", "value": {"active": False}},
            scheduled_at=scheduled_time,
            team=self.team_1,
            created_by=self.user,
        )

        url = f"/api/organizations/{self.organization.id}/feature_flags/copy_flags"
        data = {
            "feature_flag_key": self.feature_flag_key,
            "from_project": self.team_1.id,
            "target_project_ids": [self.team_2.id, team_3.id],
            "copy_schedule": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["success"]), 2)

        # Verify schedules exist in both target projects
        for target_team in [self.team_2, team_3]:
            copied_flag = FeatureFlag.objects.get(key=self.feature_flag_key, team=target_team)
            target_schedules = ScheduledChange.objects.filter(
                record_id=str(copied_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                team=target_team,
            )
            self.assertEqual(target_schedules.count(), 1)


class TestOrganizationFeatureFlagEvaluations(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.other_team = self.organization.teams.create(name="Other")
        FeatureFlag.objects.create(team=self.team, key="shared_flag", created_by=self.user, active=True)
        FeatureFlag.objects.create(team=self.other_team, key="shared_flag", created_by=self.user, active=False)

    def _url(self, key: str) -> str:
        return f"/api/organizations/{self.organization.id}/feature_flags/{key}/"

    def test_response_includes_evaluations_field(self):
        response = self.client.get(self._url("shared_flag"))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 2
        for entry in body:
            assert "evaluations_7d" in entry

    def test_evaluation_counts_match_events(self):
        _create_event(
            team=self.team,
            distinct_id="u1",
            event="$feature_flag_called",
            properties={"$feature_flag": "shared_flag", "$feature_flag_response": True},
        )
        _create_event(
            team=self.team,
            distinct_id="u2",
            event="$feature_flag_called",
            properties={"$feature_flag": "shared_flag", "$feature_flag_response": True},
        )
        _create_event(
            team=self.other_team,
            distinct_id="u3",
            event="$feature_flag_called",
            properties={"$feature_flag": "shared_flag", "$feature_flag_response": False},
        )
        flush_persons_and_events()

        body = self.client.get(self._url("shared_flag")).json()
        by_team = {entry["team_id"]: entry["evaluations_7d"] for entry in body}

        assert by_team[self.team.id] == 2
        assert by_team[self.other_team.id] == 1

    def test_clickhouse_failure_returns_null_evaluations(self):
        with patch(
            "products.feature_flags.backend.api.organization_feature_flag.get_cached_evaluations_7d_by_team",
            return_value=None,
        ):
            body = self.client.get(self._url("shared_flag")).json()
        for entry in body:
            assert entry["evaluations_7d"] is None
