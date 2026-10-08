"""Disabling and soft-deleting a stored v2 row are the pilot's incident controls, so they must
work with both writer flags off; creating and enabling need the project's flags on.
"""

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.api.utils import ServiceRequest
from posthog.exceptions import Conflict
from posthog.models import Team

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.approvals.backend.serializers import ApprovalPolicySerializer
from products.feature_flags.backend.api.feature_flag import (
    FeatureFlagSerializer,
    _get_flag_rollout_info,
    flag_version_conflict_message,
)
from products.feature_flags.backend.api.test.test_feature_flag_config_v2_updates import (
    AdmittedV2TestCase,
    JsonValue,
    V2UpdateTestCase,
    admit_v2,
    config,
    rollout,
    targeted,
)
from products.feature_flags.backend.facade import api as flag_facade
from products.feature_flags.backend.flags_cache import _get_feature_flags_for_service
from products.feature_flags.backend.local_evaluation import _get_flags_response_for_local_evaluation_batch
from products.feature_flags.backend.models import FeatureFlag


def nested_list(levels: int) -> JsonValue:
    value: JsonValue = 1
    for _ in range(levels):
        value = [value]
    return value


class TestV2SafetyWritesNeedNoAdmission(V2UpdateTestCase):
    """Disabling and soft-deleting are the pilot's incident controls: they work with both writer flags off."""

    @parameterized.expand(["patch", "put"])
    def test_disabling_needs_only_the_row_version(self, method: str) -> None:
        flag = self.flag(active=True)
        response = self.patch_flag(flag, {"key": flag.key, "version": 3, "active": False}, method=method)
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert (flag.active, flag.version) == (False, 4)
        (entry,) = self.activity(flag)
        assert entry.activity == "updated"
        assert self.changed_fields(entry) == {"active", "version"}

    def test_an_echoed_deleted_false_does_not_undo_a_soft_delete_that_kept_the_version(self) -> None:
        flag = self.flag(active=True)
        stale = FeatureFlag.objects.get(pk=flag.pk)
        FeatureFlag.objects.filter(pk=flag.pk).update(deleted=True)  # as the file-system trash does
        updated = flag_facade.update_flag(
            stale, {"version": 3, "deleted": False, "active": False}, team=self.team, user=self.user
        )
        assert (updated.deleted, updated.active, updated.version) == (True, False, 4)

    def test_bulk_delete_disables_and_bumps_the_version_like_a_single_delete(self) -> None:
        flag = self.flag(active=True)
        v1_flag = FeatureFlag.objects.create(
            team=self.team,
            key="v1-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            version=5,
        )
        self._activity_qs(v1_flag).delete()
        stale = FeatureFlag.objects.get(pk=flag.pk)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/", {"ids": [flag.id, v1_flag.id]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert {item["id"] for item in response.json()["deleted"]} == {flag.id, v1_flag.id}
        flag.refresh_from_db()
        assert (flag.deleted, flag.active, flag.version) == (True, False, 4)
        (entry,) = self.activity(flag)
        assert entry.activity == "deleted"
        assert {c["field"]: (c["before"], c["after"]) for c in (entry.detail or {})["changes"]} == {
            "deleted": (False, True),
            "active": (True, False),
            "version": (3, 4),
        }
        v1_flag.refresh_from_db()
        assert (v1_flag.deleted, v1_flag.active, v1_flag.version) == (True, True, 5)
        (v1_entry,) = self.activity(v1_flag)
        assert (v1_entry.activity, (v1_entry.detail or {})["changes"]) == ("deleted", [])
        with self.assertRaises(Conflict):
            flag_facade.update_flag(stale, {"version": 3, "active": False}, team=self.team, user=self.user)

    def test_bulk_delete_reports_a_row_the_single_delete_refuses(self) -> None:
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.disable",
            approver_config={},
            enabled=True,
        )
        flag = self.flag(active=True)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/", {"ids": [flag.id]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["deleted"] == []
        assert response.json()["errors"] == [
            {
                "id": flag.id,
                "key": flag.key,
                "reason": "This flag cannot be written while an approval policy is enabled.",
            }
        ]
        flag.refresh_from_db()
        assert (flag.deleted, flag.active, flag.version) == (False, True, 3)
        assert self.activity(flag) == []
        assert not ChangeRequest.objects.filter(organization=self.organization).exists()

    def test_bulk_delete_reports_a_row_that_changed_after_the_read_and_deletes_the_rest(self) -> None:
        moved = self.flag(active=True, key="moved")
        other = self.flag(active=True, key="other")

        def read_then_move(flag, checker):
            if flag.pk == moved.pk:
                FeatureFlag.objects.filter(pk=moved.pk).update(version=4)
            return _get_flag_rollout_info(flag, checker)

        with patch(
            "products.feature_flags.backend.api.feature_flag._get_flag_rollout_info", side_effect=read_then_move
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
                {"ids": [moved.id, other.id]},
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["errors"] == [
            {"id": moved.id, "key": moved.key, "reason": flag_version_conflict_message(3, 4)}
        ]
        assert [item["id"] for item in response.json()["deleted"]] == [other.id]
        moved.refresh_from_db()
        assert (moved.deleted, moved.active, moved.version) == (False, True, 4)
        other.refresh_from_db()
        assert (other.deleted, other.active, other.version) == (True, False, 4)

    def test_bulk_delete_still_soft_deletes_a_row_in_an_unsupported_format(self) -> None:
        flag = self.flag({"version": 99}, active=True)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/", {"ids": [flag.id]}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["id"] for item in response.json()["deleted"]] == [flag.id]
        flag.refresh_from_db()
        assert (flag.deleted, flag.active, flag.version) == (True, True, 3)

    def test_soft_deleting_disables_an_enabled_row_in_the_same_write(self) -> None:
        flag = self.flag(active=True)
        response = self.patch_flag(flag, {"version": 3, "deleted": True})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert (flag.deleted, flag.active, flag.version) == (True, False, 4)
        (entry,) = self.activity(flag)
        assert entry.activity == "deleted"

    @parameterized.expand(
        [
            ("missing_token", {"active": False}, status.HTTP_400_BAD_REQUEST),
            ("stale_token", {"version": 2, "active": False}, status.HTTP_409_CONFLICT),
            ("stale_delete", {"version": 2, "deleted": True}, status.HTTP_409_CONFLICT),
            ("restore", {"version": 3, "deleted": False}, status.HTTP_400_BAD_REQUEST),
            ("archived_flag_field", {"version": 3, "archived": True, "active": False}, status.HTTP_400_BAD_REQUEST),
            ("rename", {"version": 3, "active": False, "name": "Renamed"}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_everything_else_stays_closed(self, _name: str, data: dict, expected: int) -> None:
        flag = self.flag(active=True, deleted=data.get("deleted") is False)
        response = self.patch_flag(flag, data)
        assert response.status_code == expected, response.json()
        flag.refresh_from_db()
        assert flag.active
        assert flag.version == 3
        assert self.activity(flag) == []

    @parameterized.expand(
        [
            ("enable", False, "unsupported_config_version"),
            ("disable", True, "required"),
            ("archive", True, "unsupported_config_version"),
        ]
    )
    def test_body_less_lifecycle_actions_reject_v2_rows_explicitly(self, action: str, active: bool, code: str) -> None:
        flag = self.flag(active=active)
        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/{action}/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == code
        flag.refresh_from_db()
        assert (flag.active, flag.archived, flag.version) == (active, False, 3)


class TestAdmittedV2Creation(AdmittedV2TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(admit_v2(self.team.id, creation=True))

    def test_create_is_disabled_with_server_identity_and_round_trips(self) -> None:
        submitted = config(targeted(rule_id=None), rollout(rule_id=None, seed=None))
        response = self.post_flag({"key": "new-v2", "name": "Pilot", "filters": submitted})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flag = FeatureFlag.objects.get(team=self.team, key="new-v2")
        assert (flag.active, flag.version, flag.name) == (False, 1, "Pilot")
        rules = flag.filters["rules"]
        assert [rule["rule_type"] for rule in rules] == ["targeted_release", "percentage_rollout"]
        assert len({rule["id"] for rule in rules}) == 2 and rules[1]["seed"]
        assert {
            **flag.filters,
            "rules": [{k: v for k, v in r.items() if k not in ("id", "seed")} for r in rules],
        } == submitted
        assert response.json()["filters"] == flag.filters
        read = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        assert read.status_code == status.HTTP_200_OK
        assert (read.json()["filters"], read.json()["active"]) == (flag.filters, False)
        (entry,) = self.activity(flag)
        assert entry.activity == "created"

    @parameterized.expand(
        [
            ("string", "compact", "standard"),
            ("number", -2.5, 0),
            ("object", {"layout": "compact", "options": [1, True, None]}, {}),
        ]
    )
    def test_typed_documents_are_created_and_round_trip(
        self, return_type: str, value: JsonValue, default: JsonValue
    ) -> None:
        submitted = config(
            targeted(rule_id=None, value=value), rollout(rule_id=None, seed=None, value=value), return_type=return_type
        )
        submitted["default_value"] = default
        response = self.post_flag({"key": "typed-v2", "filters": submitted})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        flag = FeatureFlag.objects.get(team=self.team, key="typed-v2")
        assert [rule["value"] for rule in flag.filters["rules"]] == [value, value]
        assert (flag.filters["return_type"], flag.filters["default_value"]) == (return_type, default)
        read = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        assert read.json()["filters"] == flag.filters

    @parameterized.expand(
        [
            ("string_bool_default", "string", True, "compact", "filters.default_value"),
            ("string_empty_value", "string", None, "", "filters.rules[0].value"),
            ("number_string_value", "number", 0, "1", "filters.rules[0].value"),
            ("number_unsafe_integer", "number", 2**53, 1, "filters.default_value"),
            ("object_array_value", "object", None, [1], "filters.rules[0].value"),
            ("object_too_deep", "object", None, {"a": nested_list(20)}, "filters.rules[0].value"),
        ]
    )
    def test_values_that_do_not_match_the_return_type_are_rejected(
        self, _name: str, return_type: str, default: JsonValue, value: JsonValue, attr: str
    ) -> None:
        submitted = config(targeted(rule_id=None, value=value), return_type=return_type)
        submitted["default_value"] = default
        response = self.post_flag({"key": "typed-v2", "filters": submitted})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == attr, response.json()
        assert not FeatureFlag.objects.filter(team=self.team, key="typed-v2").exists()

    def test_active_on_create_is_rejected_not_downgraded(self) -> None:
        response = self.post_flag({"key": "new-v2", "filters": config(targeted(rule_id=None)), "active": True})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (response.json()["code"], response.json()["attr"]) == ("unsupported_config_version", "active")
        assert not FeatureFlag.objects.filter(team=self.team, key="new-v2").exists()

    @parameterized.expand(
        [
            ("client_id", {"filters": config(targeted())}, "invalid_input"),
            ("fragment", {"filters": {"version": 2, "rules": []}}, "required"),
            ("remote_config", {"filters": config(), "is_remote_configuration": True}, "unsupported_config_version"),
            ("encrypted", {"filters": config(), "has_encrypted_payloads": True}, "unsupported_config_version"),
            ("archived", {"filters": config(), "archived": True}, "unsupported_config_version"),
            ("deleted", {"filters": config(), "deleted": True}, "unsupported_config_version"),
            ("continuity", {"filters": config(), "ensure_experience_continuity": True}, "unsupported_config_version"),
            ("unknown", {"filters": config(), "naem": "x"}, "unsupported_config_version"),
        ]
    )
    def test_invalid_documents_and_unsupported_fields_are_rejected(self, _name: str, data: dict, code: str) -> None:
        response = self.post_flag({"key": "new-v2", **data})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == code, response.json()
        assert not FeatureFlag.objects.filter(team=self.team, key="new-v2").exists()

    def test_v1_creates_and_version_1_stay_as_before(self) -> None:
        response = self.post_flag(
            {"key": "v1-flag", "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]}}
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert FeatureFlag.objects.get(team=self.team, key="v1-flag").active
        response = self.post_flag({"key": "reserved", "filters": {"version": 1, "groups": []}})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "reserved_config_version"

    def test_another_team_stays_reserved_while_this_one_creates(self) -> None:
        other = Team.objects.create(organization=self.organization, name="not admitted")
        response = self.client.post(
            f"/api/projects/{other.id}/feature_flags/", {"key": "new-v2", "filters": config()}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "reserved_config_version"

    def test_an_enabled_approval_policy_denies_the_create(self) -> None:
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            approver_config={},
            enabled=True,
        )
        response = self.post_flag({"key": "new-v2", "filters": config()})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unsupported_config_version"
        assert not FeatureFlag.objects.filter(team=self.team, key="new-v2").exists()
        assert not ChangeRequest.objects.filter(organization=self.organization).exists()

    def test_a_policy_enabled_after_validation_denies_the_create(self) -> None:
        tombstone = self.flag(key="new-v2", deleted=True)
        serializer = FeatureFlagSerializer(
            data={"key": "new-v2", "filters": config()},
            context={
                "request": ServiceRequest(self.user),
                "team_id": self.team.id,
                "project_id": self.team.project_id,
            },
        )
        serializer.is_valid(raise_exception=True)
        policy = ApprovalPolicySerializer(
            data={"action_key": "feature_flag.update", "approver_config": {"quorum": 1}, "enabled": True}
        )
        policy.is_valid(raise_exception=True)
        policy.save(organization=self.organization, team=self.team)

        with self.assertRaises(ValidationError) as error:
            serializer.save()

        assert error.exception.get_codes() == ["unsupported_config_version"]
        assert not FeatureFlag.objects.filter(team=self.team, key="new-v2").exists()
        tombstone.refresh_from_db()
        assert (tombstone.key, tombstone.deleted) == ("new-v2", True)

    def test_approval_replay_cannot_create(self) -> None:
        serializer = FeatureFlagSerializer(
            data={"key": "new-v2", "filters": config()},
            context={
                "request": ServiceRequest(self.user),
                "team_id": self.team.id,
                "project_id": self.team.project_id,
                "approval_apply": True,
            },
        )
        assert not serializer.is_valid()
        assert "unsupported_config_version" in str(serializer.errors)

    @override_settings(MIDDLEWARE=[])
    def test_duplicate_keys_in_the_create_bytes_are_rejected(self) -> None:
        self.client.force_authenticate(user=self.user)
        body = '{"key": "new-v2", "filters": {"version": 2, "version": 2, "return_type": "boolean", "default_value": false, "rules": []}}'
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", body, content_type="application/json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert '"version"' in response.json()["detail"]
        assert not FeatureFlag.objects.filter(team=self.team, key="new-v2").exists()


class TestAdmittedV2Enabling(AdmittedV2TestCase):
    def test_enable_and_disable_are_one_version_checked_toggle(self) -> None:
        flag = self.flag(active=False)
        response = self.patch_flag(flag, {"version": 3, "active": True})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert (flag.active, flag.version) == (True, 4)
        assert self.patch_flag(flag, {"version": 3, "active": False}).status_code == status.HTTP_409_CONFLICT
        assert self.patch_flag(flag, {"version": 4, "active": False}).status_code == status.HTTP_200_OK
        flag.refresh_from_db()
        assert (flag.active, flag.version) == (False, 5)
        assert [entry.activity for entry in self.activity(flag)] == ["updated", "updated"]

    def test_enabling_reports_a_disabled_flag_the_rule_targeting_depends_on(self) -> None:
        dependency = FeatureFlag.objects.create(team=self.team, key="base-flag", active=False, created_by=self.user)
        # Stored past the validator, which does not admit flag targeting yet. The non-integer key is skipped.
        targeting = {
            "properties": [
                {"key": str(dependency.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                {"key": "checkout-flow", "type": "flag", "value": True, "operator": "flag_evaluates_to"},
            ]
        }
        stored = config(targeted(targeting=targeting))
        flag = self.flag(stored, active=False)

        response = self.patch_flag(flag, {"version": 3, "active": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()["detail"]
        assert "Cannot enable this feature flag because it depends on disabled flags" in detail
        assert f"base-flag (ID: {dependency.id})" in detail
        flag.refresh_from_db()
        assert (flag.active, flag.version, flag.filters) == (False, 3, stored)

    @parameterized.expand(
        [
            ("malformed", {"version": 2, "rules": "broken"}, settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES),
            (
                "flag_reference",
                config(
                    targeted(
                        targeting={
                            "properties": [{"key": "1", "type": "flag", "value": True, "operator": "flag_evaluates_to"}]
                        }
                    )
                ),
                settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES,
            ),
            ("over_the_current_limit", config(targeted(description="x" * 400)), 200),
        ]
    )
    def test_enabling_rechecks_the_stored_document(
        self, _name: str, stored: dict, max_config_bytes: int | None
    ) -> None:
        flag = self.flag(stored, active=False)
        with override_settings(
            MAX_FEATURE_FLAG_FILTER_SIZE_BYTES=max_config_bytes or settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES
        ):
            response = self.patch_flag(flag, {"version": 3, "active": True})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert (flag.active, flag.version, flag.filters) == (False, 3, stored)
        assert self.activity(flag) == []

    def test_an_enabled_approval_policy_denies_enabling(self) -> None:
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            approver_config={},
            enabled=True,
        )
        flag = self.flag(active=False)
        response = self.patch_flag(flag, {"version": 3, "active": True})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unsupported_config_version"
        flag.refresh_from_db()
        assert not flag.active
        assert not ChangeRequest.objects.filter(organization=self.organization).exists()


class TestV2PilotLifecycle(AdmittedV2TestCase):
    """Create, read, enable, replace, stale write, disable, re-enable, delete through the public API:
    one activity entry and one version step per write.
    """

    def check(self, response, flag_id: int, *, version: int, entries: int, expected: int = status.HTTP_200_OK):
        assert response.status_code == expected, response.json()
        flag = FeatureFlag.objects_including_soft_deleted.get(pk=flag_id)
        assert flag.version == version
        assert len(self.activity(flag)) == entries
        return flag

    def test_create_read_enable_update_close_disable_recover_delete(self) -> None:
        initial = config(targeted(rule_id=None), rollout(rule_id=None, seed=None))
        with admit_v2(self.team.id, creation=True):
            response = self.post_flag({"key": "pilot-flag", "filters": initial})
        flag = self.check(response, response.json()["id"], version=1, entries=1, expected=status.HTTP_201_CREATED)
        assert not flag.active
        stored = flag.filters
        read = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/").json()
        assert (read["filters"], read["active"], read["version"]) == (stored, False, 1)

        flag = self.check(self.patch_flag(flag, {"version": 1, "active": True}), flag.id, version=2, entries=2)
        assert flag.active
        assert "pilot-flag" not in {
            f["key"] for f in _get_flags_response_for_local_evaluation_batch([self.team])[self.team.id]["flags"]
        }
        assert "pilot-flag" in {f["key"] for f in _get_feature_flags_for_service(self.team)["flags"]}

        replacement = config(
            targeted(rule_id=stored["rules"][0]["id"], value=False),
            rollout(rule_id=None, seed=None, rollout_percentage=50),
        )
        flag = self.check(self.patch_flag(flag, {"version": 2, "filters": replacement}), flag.id, version=3, entries=3)
        assert flag.filters["rules"][0] == replacement["rules"][0]
        assert flag.filters["rules"][1]["rollout_percentage"] == 50 and flag.filters["rules"][1]["seed"]
        stale = self.patch_flag(flag, {"version": 2, "filters": config()})
        flag = self.check(stale, flag.id, version=3, entries=3, expected=status.HTTP_409_CONFLICT)

        flag = self.check(self.patch_flag(flag, {"version": 3, "active": False}), flag.id, version=4, entries=4)
        assert not flag.active
        flag = self.check(self.patch_flag(flag, {"version": 4, "active": True}), flag.id, version=5, entries=5)
        assert flag.active
        flag = self.check(self.patch_flag(flag, {"version": 5, "active": False}), flag.id, version=6, entries=6)
        flag = self.check(self.patch_flag(flag, {"version": 6, "deleted": True}), flag.id, version=7, entries=7)
        assert (flag.deleted, flag.active) == (True, False)
        assert not FeatureFlag.objects.filter(pk=flag.id).exists()

        entries = self.activity(flag)
        assert [entry.activity for entry in entries] == ["created", *["updated"] * 5, "deleted"]
        assert [self.changed_fields(entry) for entry in entries[1:]] == [
            {"active", "version"},
            {"filters", "version"},
            {"active", "version"},
            {"active", "version"},
            {"active", "version"},
            {"deleted", "version"},
        ]
        history = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")
        assert history.status_code == status.HTTP_200_OK, history.json()
        assert (history.json()["filters"]["rules"], history.json()["active"]) == (stored["rules"], False)
