"""Disabling and soft-deleting a stored v2 row are the pilot's incident controls, so they must
work with both writer flags off; creating and enabling need the project's flags on.
"""

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.utils import ServiceRequest
from posthog.models import Team

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.api.test.test_feature_flag_config_v2_updates import (
    AdmittedV2TestCase,
    V2UpdateTestCase,
    admit_v2,
    config,
    rollout,
    targeted,
)
from products.feature_flags.backend.flags_cache import _get_feature_flags_for_service
from products.feature_flags.backend.local_evaluation import _get_flags_response_for_local_evaluation_batch
from products.feature_flags.backend.models import FeatureFlag


class TestV2SafetyWritesNeedNoAdmission(V2UpdateTestCase):
    """Disabling and archiving are the pilot's incident controls: they work with both settings closed."""

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

    def test_archiving_disables_an_enabled_row_in_the_same_write(self) -> None:
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
            ("stale_archive", {"version": 2, "deleted": True}, status.HTTP_409_CONFLICT),
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

    def test_active_on_create_is_rejected_not_downgraded(self) -> None:
        response = self.post_flag({"key": "new-v2", "filters": config(targeted(rule_id=None)), "active": True})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (response.json()["code"], response.json()["attr"]) == ("unsupported_config_version", "active")
        assert not FeatureFlag.objects.filter(team=self.team, key="new-v2").exists()

    @parameterized.expand(
        [
            ("client_id", {"filters": config(targeted())}),
            ("fragment", {"filters": {"version": 2, "rules": []}}),
            ("remote_config", {"filters": config(), "is_remote_configuration": True}),
            ("encrypted", {"filters": config(), "has_encrypted_payloads": True}),
            ("archived", {"filters": config(), "archived": True}),
            ("deleted", {"filters": config(), "deleted": True}),
            ("continuity", {"filters": config(), "ensure_experience_continuity": True}),
            ("unknown", {"filters": config(), "naem": "x"}),
        ]
    )
    def test_invalid_documents_and_unsupported_fields_are_rejected(self, _name: str, data: dict) -> None:
        response = self.post_flag({"key": "new-v2", **data})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
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


class TestM1PilotScenario(AdmittedV2TestCase):
    """The final-plan M1 sequence through the public API, one activity entry and one version step per write."""

    def check(self, response, flag_id: int, *, version: int, entries: int, expected: int = status.HTTP_200_OK):
        assert response.status_code == expected, response.json()
        flag = FeatureFlag.objects_including_soft_deleted.get(pk=flag_id)
        assert flag.version == version
        assert len(self.activity(flag)) == entries
        return flag

    def test_create_read_enable_update_close_disable_recover_archive(self) -> None:
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
        assert "pilot-flag" not in {f["key"] for f in _get_feature_flags_for_service(self.team)["flags"]}

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
        # A generic reconstruction is acceptable for the pilot; a v2 row must only not break the endpoint.
        history = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")
        assert history.status_code in (status.HTTP_200_OK, status.HTTP_422_UNPROCESSABLE_ENTITY)
        if history.status_code == status.HTTP_200_OK:
            assert (history.json()["filters"]["rules"], history.json()["active"]) == (stored["rules"], False)
