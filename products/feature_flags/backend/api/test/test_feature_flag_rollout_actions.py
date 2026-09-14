from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import RequestFactory

from parameterized import parameterized
from rest_framework import status
from rest_framework.request import Request as DRFRequest

from posthog.constants import AvailableFeature
from posthog.exceptions import Conflict
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.feature_flags.backend.api.feature_flag import FlagRolloutWriteRequest
from products.feature_flags.backend.facade.api import update_flag
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Deliberately wider than what either action writes: every one of these must survive a rollout call.
TARGETING: dict[str, Any] = {
    "groups": [
        {
            "properties": [{"key": "email", "type": "person", "value": "@example.com", "operator": "icontains"}],
            "rollout_percentage": 10,
            "description": "internal users",
        },
        {"properties": [], "rollout_percentage": 5},
    ],
    "multivariate": {
        "variants": [
            {"key": "control", "rollout_percentage": 60, "name": "Control"},
            {"key": "test", "rollout_percentage": 40},
        ]
    },
    "payloads": {"control": '{"copy": "a"}'},
    "aggregation_group_type_index": None,
}

BOOLEAN_TARGETING: dict[str, Any] = {
    "groups": [
        {"properties": [{"key": "email", "type": "person", "value": "@example.com"}], "rollout_percentage": 10},
    ],
    "payloads": {"true": '"on"'},
    "holdout": {"id": 7, "exclusion_percentage": 5},
}


def persisted(filters: dict) -> dict:
    """What the shared flag write path stores for these filters.

    Every write that sends `filters` stamps the flag-level aggregation index onto each release
    condition, whichever endpoint sends it. It changes no targeting, so the rollout actions
    inherit the normalization rather than work around it.
    """
    aggregation = filters.get("aggregation_group_type_index")
    return {
        **filters,
        "aggregation_group_type_index": aggregation,
        "groups": [{"aggregation_group_type_index": aggregation, **group} for group in filters.get("groups") or []],
    }


# (action, body without `version`)
ROLLOUT_ACTIONS = [
    ("set_release_condition_rollout", {"condition_index": 0, "rollout_percentage": 25}),
    ("roll_out_to_everyone", {"variant_key": "test"}),
]


class TestFeatureFlagRolloutActions(APIBaseTest):
    def _flag(self, *, key: str = "rollout-flag", filters: dict | None = None) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name="rollout flag",
            active=True,
            filters=TARGETING if filters is None else filters,
        )

    def _act(self, flag: FeatureFlag, action: str, body: dict) -> Any:
        return self.client.post(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/{action}/", body, format="json")

    def _read(self, flag: FeatureFlag) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/").json()

    def _gate_flag_updates_on_approval(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    @parameterized.expand([("first", 0), ("second", 1)])
    def test_indexed_rollout_changes_only_that_condition(self, _name, condition_index):
        flag = self._flag()

        response = self._act(
            flag,
            "set_release_condition_rollout",
            {"condition_index": condition_index, "rollout_percentage": 25, "version": flag.version},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        expected = {
            **TARGETING,
            "groups": [
                {**group, "rollout_percentage": 25} if index == condition_index else group
                for index, group in enumerate(TARGETING["groups"])
            ],
        }
        assert flag.filters == persisted(expected)

    @parameterized.expand(
        [
            ("past_the_end", {"condition_index": 2, "rollout_percentage": 25}, "It has 2"),
            ("negative", {"condition_index": -1, "rollout_percentage": 25}, "greater than or equal to 0"),
            ("percentage_over_100", {"condition_index": 0, "rollout_percentage": 101}, "less than or equal to 100"),
        ]
    )
    def test_indexed_rollout_refuses_an_input_it_cannot_apply(self, _name, body, expected_message):
        flag = self._flag()

        response = self._act(flag, "set_release_condition_rollout", {**body, "version": flag.version})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert expected_message in str(response.json())
        flag.refresh_from_db()
        assert flag.filters == TARGETING
        assert flag.version == 1

    def test_indexed_rollout_on_a_flag_with_no_conditions_says_so(self):
        flag = self._flag(filters={"groups": []})

        response = self._act(
            flag, "set_release_condition_rollout", {"condition_index": 0, "rollout_percentage": 25, "version": 1}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "no release conditions" in response.json()["detail"]

    def test_roll_out_to_everyone_prepends_a_catch_all_on_a_boolean_flag(self):
        flag = self._flag(filters=BOOLEAN_TARGETING)

        response = self._act(flag, "roll_out_to_everyone", {"version": flag.version})

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.filters == persisted(
            {
                **BOOLEAN_TARGETING,
                "groups": [{"properties": [], "rollout_percentage": 100}, *BOOLEAN_TARGETING["groups"]],
            }
        )

    def test_roll_out_to_everyone_gives_the_named_variant_the_whole_distribution(self):
        flag = self._flag()

        response = self._act(flag, "roll_out_to_everyone", {"variant_key": "test", "version": flag.version})

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.filters == persisted(
            {
                **TARGETING,
                "groups": [{"properties": [], "rollout_percentage": 100}, *TARGETING["groups"]],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 0, "name": "Control"},
                        {"key": "test", "rollout_percentage": 100},
                    ]
                },
            }
        )

    def test_roll_out_to_everyone_refuses_a_multivariate_flag_with_no_variant(self):
        # "Roll it out to everyone" reads two ways on a multivariate flag: serve everyone and keep
        # the split, or serve everyone one variant. Refusing makes the caller say which.
        flag = self._flag()

        response = self._act(flag, "roll_out_to_everyone", {"version": flag.version})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "control, test" in response.json()["detail"]
        flag.refresh_from_db()
        assert flag.filters == TARGETING

    @parameterized.expand(
        [
            ("unknown_variant", None, "green", "has no variant 'green'"),
            ("flag_has_no_variants", BOOLEAN_TARGETING, "test", "has no variants"),
        ]
    )
    def test_roll_out_to_everyone_refuses_a_variant_the_flag_does_not_define(
        self, _name, filters, variant_key, expected_message
    ):
        flag = self._flag(filters=filters)
        original = flag.filters

        response = self._act(flag, "roll_out_to_everyone", {"variant_key": variant_key, "version": flag.version})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert expected_message in response.json()["detail"]
        flag.refresh_from_db()
        assert flag.filters == original

    @parameterized.expand(ROLLOUT_ACTIONS)
    def test_rollout_action_refuses_a_version_that_is_no_longer_current(self, action, body):
        flag = self._flag()
        stale_version = flag.version
        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": {**TARGETING, "groups": [{"properties": [], "rollout_percentage": 80}]}},
            format="json",
        )

        response = self._act(flag, action, {**body, "version": stale_version})

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        assert f"changed since version {stale_version}" in response.json()["detail"]
        flag.refresh_from_db()
        assert flag.filters["groups"] == [
            {"properties": [], "rollout_percentage": 80, "aggregation_group_type_index": None}
        ]

    @parameterized.expand(ROLLOUT_ACTIONS)
    def test_a_fresh_read_after_a_conflict_lets_the_change_through(self, action, body):
        flag = self._flag()
        stale_version = flag.version
        self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"name": "renamed"}, format="json")
        assert self._act(flag, action, {**body, "version": stale_version}).status_code == status.HTTP_409_CONFLICT

        response = self._act(flag, action, {**body, "version": self._read(flag)["version"]})

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.filters != TARGETING
        assert flag.name == "renamed"

    @parameterized.expand(ROLLOUT_ACTIONS)
    def test_repeating_a_rollout_action_writes_nothing(self, action, body):
        flag = self._flag()

        first = self._act(flag, action, {**body, "version": flag.version})
        assert first.status_code == status.HTTP_200_OK, first.content

        second = self._act(flag, action, {**body, "version": first.json()["version"]})

        assert second.status_code == status.HTTP_200_OK, second.content
        assert second.json()["version"] == first.json()["version"]
        assert ActivityLog.objects.filter(scope="FeatureFlag", item_id=str(flag.id), activity="updated").count() == 1

    @parameterized.expand(ROLLOUT_ACTIONS)
    def test_rollout_action_refuses_a_soft_deleted_flag(self, action, body):
        flag = self._flag()
        flag.deleted = True
        flag.save()

        response = self._act(flag, action, {**body, "version": flag.version})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "has been deleted" in response.json()["error"]

    @parameterized.expand(ROLLOUT_ACTIONS)
    def test_rollout_action_requires_the_feature_flag_write_scope(self, action, body):
        flag = self._flag()
        read_only_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read only", user=self.user, scopes=["feature_flag:read"], secure_value=hash_key_value(read_only_key)
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/{action}/",
            {**body, "version": flag.version},
            format="json",
            headers={"authorization": f"Bearer {read_only_key}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        flag.refresh_from_db()
        assert flag.filters == TARGETING

    @parameterized.expand(ROLLOUT_ACTIONS)
    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_a_rollout_policy_opens_a_change_request_instead_of_writing(self, action, body, _mock_enabled):
        self._gate_flag_updates_on_approval()
        flag = self._flag()

        response = self._act(flag, action, {**body, "version": flag.version})

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        change_request = ChangeRequest.objects.get(team=self.team)
        assert change_request.resource_id == str(flag.id)
        # A fallback to the request body would open a change request carrying no filters, which
        # approving would then apply as no change at all.
        assert change_request.intent["full_request_data"]["filters"] != TARGETING
        flag.refresh_from_db()
        assert flag.filters == TARGETING

    @parameterized.expand(ROLLOUT_ACTIONS)
    @patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
    def test_a_stale_version_is_refused_before_a_policy_opens_a_change_request(self, action, body, _mock_enabled):
        # The gate raises before the serializer's version check runs, so only the action's own
        # pre-check keeps a stale caller out of it.
        self._gate_flag_updates_on_approval()
        flag = self._flag()
        stale_version = flag.version
        FeatureFlag.objects.filter(pk=flag.id).update(version=(flag.version or 0) + 1)

        response = self._act(flag, action, {**body, "version": stale_version})

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        assert f"changed since version {stale_version}" in response.json()["detail"]
        assert ChangeRequest.objects.filter(team=self.team).count() == 0
        flag.refresh_from_db()
        assert flag.filters == TARGETING

    def test_the_serializer_refuses_a_stale_version_under_its_row_lock(self):
        # The action's own check cannot close the window: an edit can land between it and the
        # save. Only the serializer's check, under the row lock, makes the window closed.
        flag = self._flag()
        http_request = RequestFactory().post("/")
        http_request.user = self.user
        drf_request = DRFRequest(http_request)
        drf_request.user = self.user

        with self.assertRaises(Conflict):
            update_flag(
                flag,
                {"filters": {**TARGETING, "groups": [{"properties": [], "rollout_percentage": 100}]}},
                team=self.team,
                user=self.user,
                request=FlagRolloutWriteRequest(drf_request, version=(flag.version or 0) + 5),
            )

        flag.refresh_from_db()
        assert flag.filters == TARGETING
