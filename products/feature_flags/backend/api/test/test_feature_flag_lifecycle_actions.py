from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE, flag_payload_codec
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Deliberately more than the state fields: every one of these must survive a lifecycle call.
TARGETING: dict[str, Any] = {
    "groups": [
        {
            "properties": [{"key": "email", "type": "person", "value": "@example.com", "operator": "icontains"}],
            "rollout_percentage": 37,
            "variant": "control",
        },
        {"properties": [], "rollout_percentage": 5},
    ],
    "multivariate": {
        "variants": [
            {"key": "control", "rollout_percentage": 60},
            {"key": "test", "rollout_percentage": 40},
        ]
    },
    "payloads": {"control": '{"copy": "a"}'},
}

# (action, starting active, starting archived, resulting active, resulting archived)
STATE_CASES = [
    ("enable", False, False, True, False),
    ("disable", True, False, False, False),
    # Both archive paths: the facade only sends `active` when the flag is still enabled, and
    # only that write engages the disable approval policy.
    ("archive_enabled", True, False, False, True),
    ("archive_disabled", False, False, False, True),
    ("unarchive", False, True, False, False),
]

LIFECYCLE_ACTIONS = [("enable",), ("disable",), ("archive",), ("unarchive",)]


class TestFeatureFlagLifecycleActions(APIBaseTest):
    def _flag(
        self,
        *,
        key: str = "lifecycle-flag",
        active: bool = True,
        archived: bool = False,
        filters: dict | None = None,
    ) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            name="lifecycle flag",
            active=active,
            archived=archived,
            filters=TARGETING if filters is None else filters,
        )

    def _act(self, flag: FeatureFlag, action: str, data: dict | None = None) -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/{action}/",
            data if data is not None else {},
            format="json",
        )

    def _dependent_of(self, flag: FeatureFlag, *, key: str = "dependent-flag", active: bool = True) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            active=active,
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag.id), "type": "flag", "value": "true", "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

    @parameterized.expand(STATE_CASES)
    def test_action_changes_only_the_state_fields(self, case, active, archived, expected_active, expected_archived):
        action = case.split("_")[0]
        flag = self._flag(active=active, archived=archived)

        response = self._act(flag, action)

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["active"] is expected_active
        assert response.json()["archived"] is expected_archived
        flag.refresh_from_db()
        assert flag.active is expected_active
        assert flag.archived is expected_archived
        assert flag.filters == TARGETING
        assert flag.key == "lifecycle-flag"
        assert flag.name == "lifecycle flag"

    @parameterized.expand(STATE_CASES)
    def test_action_ignores_a_caller_supplied_body(self, case, active, archived, expected_active, expected_archived):
        # A caller-supplied stale targeting object cannot overwrite another edit, because
        # lifecycle actions ignore the request body. `version` and `original_flag` are
        # in the body because the flag UI sends both on every PATCH, so an agent porting a
        # PATCH call keeps them. Together they used to make the serializer discard the state
        # change and still return 200.
        action = case.split("_")[0]
        flag = self._flag(active=active, archived=archived)

        response = self._act(
            flag,
            action,
            {
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "key": "hijacked",
                "active": not expected_active,
                "archived": not expected_archived,
                "version": 999,
                "original_flag": {"active": expected_active, "archived": expected_archived},
            },
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.filters == TARGETING
        assert flag.key == "lifecycle-flag"
        assert flag.active is expected_active
        assert flag.archived is expected_archived

    @parameterized.expand(STATE_CASES)
    def test_repeating_an_action_writes_nothing(self, case, active, archived, _expected_active, _expected_archived):
        action = case.split("_")[0]
        flag = self._flag(active=active, archived=archived)

        first = self._act(flag, action)
        assert first.status_code == status.HTTP_200_OK, first.content

        second = self._act(flag, action)

        assert second.status_code == status.HTTP_200_OK, second.content
        assert second.json()["version"] == first.json()["version"]
        assert ActivityLog.objects.filter(scope="FeatureFlag", item_id=str(flag.id), activity="updated").count() == 1

    @parameterized.expand(
        [
            ("enable", False, False),
            ("disable", True, False),
            ("archive", True, False),
            ("unarchive", False, True),
        ]
    )
    def test_action_preserves_legacy_filter_keys(self, action, active, archived):
        # The serializer opportunistically strips `holdout_groups` and `super_groups` on any
        # save, falling back to the stored filters when the write sent none. That silently
        # rewrote targeting on a state flip, which is exactly what these endpoints promise not
        # to do. TARGETING carries neither key, so nothing else here would catch it.
        legacy = {
            "groups": [{"properties": [], "rollout_percentage": 30}],
            "holdout_groups": [{"properties": [], "rollout_percentage": 5, "variant": "holdout-1"}],
            "super_groups": [{"properties": [], "rollout_percentage": 15}],
        }
        flag = self._flag(active=active, archived=archived, filters=legacy)

        response = self._act(flag, action)

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.filters == legacy

    def test_enable_refuses_an_archived_flag(self):
        flag = self._flag(active=False, archived=True)

        response = self._act(flag, "enable")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Cannot enable an archived feature flag. Unarchive it first."
        flag.refresh_from_db()
        assert flag.active is False

    @parameterized.expand([("disable",), ("archive",)])
    def test_action_refuses_a_flag_other_active_flags_depend_on(self, action):
        flag = self._flag(active=True)
        dependent = self._dependent_of(flag)

        response = self._act(flag, action)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Cannot disable this feature flag because other flags depend on it" in response.json()["detail"]
        assert f"{dependent.key} (ID: {dependent.id})" in response.json()["detail"]
        flag.refresh_from_db()
        assert flag.active is True
        assert flag.archived is False

    def test_enable_refuses_a_flag_whose_dependency_is_disabled(self):
        dependency = self._flag(key="dependency-flag", active=False, filters={"groups": []})
        flag = self._dependent_of(dependency, key="depends-on-disabled", active=False)

        response = self._act(flag, "enable")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "depends on disabled flags" in response.json()["detail"]
        flag.refresh_from_db()
        assert flag.active is False

    def test_action_records_the_state_change_in_the_activity_log(self):
        flag = self._flag(active=False)

        assert self._act(flag, "enable").status_code == status.HTTP_200_OK

        entry = ActivityLog.objects.get(scope="FeatureFlag", item_id=str(flag.id), activity="updated")
        changed_fields = {change["field"] for change in (entry.detail or {})["changes"]}
        assert "active" in changed_fields
        assert "filters" not in changed_fields
        assert entry.user == self.user

    @override_settings(FLAGS_REDIS_URL="redis://test")
    @patch("products.feature_flags.backend.flags_cache._enqueue_invalidation")
    def test_action_invalidates_the_flags_cache(self, mock_enqueue):
        flag = self._flag(active=False)
        mock_enqueue.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            assert self._act(flag, "enable").status_code == status.HTTP_200_OK

        mock_enqueue.assert_called_with(self.team.id)

    @parameterized.expand(
        [
            ("enable", False, False),
            ("disable", True, False),
            ("archive", True, False),
            ("unarchive", False, True),
        ]
    )
    def test_action_works_when_the_team_requires_evaluation_contexts(self, action, active, archived):
        # The actions are POST but they update, and FeatureFlagSerializer.validate runs
        # create-only validation on POST. Reported as POST, every one of these returned
        # "at least one evaluation context is required to create a new feature flag".
        self.team.require_evaluation_contexts = True
        self.team.save()
        flag = self._flag(active=active, archived=archived)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self._act(flag, action)

        assert response.status_code == status.HTTP_200_OK, response.content

    @parameterized.expand([("session", False), ("personal_api_key", True)])
    def test_encrypted_payload_is_never_returned_as_ciphertext(self, _name, use_personal_api_key):
        # `filters` serializes the stored dict, so without the response step these endpoints
        # hand out the raw Fernet blob that every other flag surface withholds.
        ciphertext = flag_payload_codec().encrypt(b'"secret"').decode("utf-8")
        flag = self._flag(
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": ciphertext}},
        )
        flag.is_remote_configuration = True
        flag.has_encrypted_payloads = True
        flag.save()

        headers: dict[str, str] = {}
        if use_personal_api_key:
            token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="write", user=self.user, scopes=["*"], secure_value=hash_key_value(token)
            )
            self.client.logout()
            headers = {"authorization": f"Bearer {token}"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/enable/", {}, format="json", headers=headers
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        payload = response.json()["filters"]["payloads"]["true"]
        # Same rule as retrieve: a personal API key decrypts, anything else gets the placeholder.
        assert payload == ('"secret"' if use_personal_api_key else REDACTED_PAYLOAD_VALUE)
        flag.refresh_from_db()
        assert flag.filters["payloads"]["true"] == ciphertext

    def test_write_scoped_key_can_change_state(self):
        # The denial tests below pass just as well if the declared scope stops resolving to
        # anything a write key satisfies, which would 403 every MCP flag flip.
        flag = self._flag(active=False)
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="write", user=self.user, scopes=["feature_flag:write"], secure_value=hash_key_value(token)
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/enable/",
            {},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        flag.refresh_from_db()
        assert flag.active is True

    @parameterized.expand(LIFECYCLE_ACTIONS)
    def test_action_requires_the_feature_flag_write_scope(self, action):
        flag = self._flag(active=False, archived=False)
        read_only_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="read only",
            user=self.user,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(read_only_key),
        )
        self.client.logout()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/{action}/",
            {},
            format="json",
            headers={"authorization": f"Bearer {read_only_key}"},
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        flag.refresh_from_db()
        assert flag.active is False
        assert flag.archived is False
