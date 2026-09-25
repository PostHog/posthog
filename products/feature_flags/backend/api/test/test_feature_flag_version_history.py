import copy
import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import transaction
from django.db.models import QuerySet
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.activity_logging.activity_log import ActivityLog, Trigger
from posthog.models.activity_logging.utils import activity_storage

from products.feature_flags.backend.api.test.test_feature_flag_config_v2_updates import (
    RULE_A,
    RULE_B,
    admit_v2_updates,
    config,
    rollout,
    targeted,
)
from products.feature_flags.backend.facade import api as flag_facade
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFeatureFlagVersionHistoryAPI(APIBaseTest):
    def _create_remote_config_flag(self, *, encrypted: bool = False) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="ios-minimum-version",
            name="Minimum app version required",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '"1.0.0"'},
            },
            is_remote_configuration=True,
            has_encrypted_payloads=encrypted,
            version=1,
        )

    def test_plaintext_remote_config_flag_returns_historical_payload(self):
        flag = self._create_remote_config_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"2.0.0"'},
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertTrue(payload["is_historical"])
        # The point of reconstruction: the payload served at the time, not the current one.
        self.assertEqual(payload["filters"]["payloads"], {"true": '"1.0.0"'})

    def test_encrypted_payload_flag_is_refused(self):
        flag = self._create_remote_config_flag(encrypted=True)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn("filters", response.json())

    def test_version_encrypted_before_downgrade_is_refused(self):
        ciphertext = "gAAAAA-ciphertext-sentinel"
        flag = self._create_remote_config_flag(encrypted=True)
        flag.filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "payloads": {"true": ciphertext},
        }
        flag.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"has_encrypted_payloads": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        flag.refresh_from_db()
        self.assertFalse(flag.has_encrypted_payloads)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/versions/1/")

        # The live row is plaintext now, but version 1 still holds ciphertext in the activity log.
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertNotIn(ciphertext, response.content.decode())


class TestV2FeatureFlagVersionHistoryAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="ordered-history",
            active=False,
            filters=config(
                targeted(description="Original", metadata={"opaque": {"empty": [], "null": None, "enabled": False}}),
                rollout(),
            ),
        )
        self.url = f"/api/projects/{self.team.id}/feature_flags/{self.flag.pk}/"

    def update(self, **data: Any) -> dict[str, Any]:
        with admit_v2_updates():
            response = self.client.patch(self.url, {"version": self.flag.version, **data}, format="json")
        assert response.status_code == 200, response.json()
        self.flag.refresh_from_db()
        return response.json()

    def history(self, version: int) -> dict[str, Any]:
        response = self.client.get(f"{self.url}versions/{version}/")
        assert response.status_code == 200, response.json()
        return response.json()

    def updates(self) -> QuerySet[ActivityLog]:
        return ActivityLog.objects.filter(
            team_id=self.team.id, scope="FeatureFlag", item_id=str(self.flag.pk), activity="updated"
        )

    def test_rules_and_metadata_reconstruct_exactly_after_further_live_changes(self) -> None:
        states = [copy.deepcopy(self.flag.filters)]
        tags: list[list[str]] = [[]]
        candidates = [
            config(
                rollout(rollout_percentage=50),
                targeted(
                    value=False,
                    targeting={
                        "properties": [{"key": "plan", "type": "person", "operator": "exact", "value": "preview"}]
                    },
                    metadata={},
                ),
                targeted(None),
            ),
            config(targeted(metadata={"value": None}), default_value=None),
            config(default_value=True),
        ]
        for candidate in candidates:
            previous = copy.deepcopy(self.flag.filters)
            response = self.update(filters=candidate)
            states.append(copy.deepcopy(self.flag.filters))
            tags.append([])
            entry = self.updates().latest("created_at")
            assert entry.detail is not None
            filters_change = next(c for c in entry.detail["changes"] if c["field"] == "filters")
            assert filters_change["before"] == previous
            assert filters_change["after"] == self.flag.filters == response["filters"]
            assert entry.user_id == self.user.id
            assert entry.organization_id == self.organization.id
            assert not entry.is_system
            assert entry.detail["context"]["filters_version"] == 2
        first = self.updates().earliest("created_at")
        assert first.detail is not None
        summary = first.detail["context"]["config_changes"]
        added_id = states[1]["rules"][2]["id"]
        assert {
            "field": f"rules/{added_id}",
            "action": "created",
            "type": "FeatureFlag",
            "before": None,
            "after": None,
        } in summary
        assert any(c["field"] == f"rules/{RULE_B}/rollout_percentage" for c in summary)
        assert any(c["field"] == f"rules/{RULE_A}/targeting" for c in summary)
        assert summary[-1]["before"] == [RULE_A, RULE_B]
        assert summary[-1]["after"] == [RULE_B, RULE_A, added_id]
        assert "preview" not in json.dumps(summary)

        self.update(name="History label", tags=["  preview  ", "preview"], key="renamed-history")
        states.append(copy.deepcopy(self.flag.filters))
        tags.append(["preview"])
        metadata_entry = self.updates().latest("created_at")
        assert metadata_entry.detail is not None
        assert {c["field"] for c in metadata_entry.detail["changes"]} == {"version", "name", "key", "tags"}
        self.update(filters=config(rollout(None, None, metadata={"later": True})), tags=[])
        assert self.flag.version == 6
        assert self.updates().count() == 5
        for version, expected in enumerate(states, 1):
            result = self.history(version)
            assert result["filters"] == expected
            assert result["tags"] == tags[version - 1]
            assert result["version"] == version
            assert result["filters"]["version"] == 2
            assert result["is_historical"]
        assert self.history(5)["name"] == "History label"
        assert self.history(4)["name"] == ""
        assert self.history(6)["filters"] == self.flag.filters
        assert not self.history(6)["is_historical"]

    @parameterized.expand(
        [
            ("absent_to_null", {}, {"value": None}),
            ("null_to_false", {"value": None}, {"value": False}),
            ("false_to_zero", {"value": False}, {"value": 0}),
            ("array_to_object", {"value": []}, {"value": {}}),
            ("empty_to_absent", {"value": {}}, {}),
        ]
    )
    def test_opaque_metadata_distinctions(self, _name: str, before: dict, after: dict) -> None:
        self.update(filters=config(targeted(metadata=before)))
        self.update(filters=config(targeted(metadata=after)))
        entry = self.updates().latest("created_at")
        assert entry.detail is not None
        assert any(c["field"] == f"rules/{RULE_A}/metadata" for c in entry.detail["context"]["config_changes"])
        assert self.history(2)["filters"]["rules"][0]["metadata"] == before

    def test_object_key_order_does_not_change_config_but_rule_order_does(self) -> None:
        before = copy.deepcopy(self.flag.filters)
        reordered_keys = dict(reversed(list(before.items())))
        reordered_keys["rules"] = [dict(reversed(list(rule.items()))) for rule in before["rules"]]
        self.update(filters=reordered_keys)
        key_order_entry = self.updates().latest("created_at")
        assert key_order_entry.detail is not None
        assert key_order_entry.detail["changes"] == [
            {"type": "FeatureFlag", "field": "version", "action": "changed", "before": 1, "after": 2}
        ]
        self.update(filters={**before, "rules": list(reversed(before["rules"]))})
        rule_order_entry = self.updates().latest("created_at")
        assert rule_order_entry.detail is not None
        summary = rule_order_entry.detail["context"]["config_changes"]
        assert summary == [
            {
                "type": "FeatureFlag",
                "field": "rule_order",
                "action": "changed",
                "before": [RULE_A, RULE_B],
                "after": [RULE_B, RULE_A],
            }
        ]
        assert self.history(1)["filters"] == before

    @parameterized.expand([1, 2, 3])
    def test_missing_transition_refuses_reconstruction(self, missing_version: int) -> None:
        for value in (True, None, False):
            self.update(filters=config(default_value=value))
        entries = list(self.updates().order_by("created_at"))
        entries[missing_version - 1].delete()
        response = self.client.get(f"{self.url}versions/1/")
        assert response.status_code == 422
        assert "incomplete" in response.json()["detail"]

    @parameterized.expand(
        [({"version": 3},), ({"version": True},), ({"version": None},), ({"version": 2, "rules": []},), ([],)]
    )
    def test_unsupported_or_malformed_current_config_is_not_normalized(self, filters: object) -> None:
        FeatureFlag.objects.filter(pk=self.flag.pk).update(filters=filters)
        response = self.client.get(f"{self.url}versions/1/")
        assert response.status_code == 422
        assert "filters" not in response.json()

    def test_stale_invalid_and_closed_writes_have_no_history(self) -> None:
        self.update(name="Accepted")
        with admit_v2_updates():
            stale = self.client.patch(self.url, {"version": 1, "name": "Stale"}, format="json")
            invalid = self.client.patch(
                self.url, {"version": 2, "filters": config(rollout(rollout_percentage=101))}, format="json"
            )
        closed = self.client.patch(self.url, {"version": 2, "name": "Closed"}, format="json")
        assert (stale.status_code, invalid.status_code, closed.status_code) == (409, 400, 400)
        assert self.updates().count() == 1
        self.flag.refresh_from_db()
        assert self.flag.version == 2
        assert self.flag.name == "Accepted"

    @override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True)
    def test_facade_rollback_discards_history_and_commit_keeps_attribution(self) -> None:
        trigger = Trigger(job_type="audit_test", job_id="synthetic-job", payload={})
        self.flag._activity_trigger = trigger
        with self.captureOnCommitCallbacks(execute=True), admit_v2_updates():
            with transaction.atomic():
                flag_facade.update_flag(
                    self.flag, {"version": 1, "name": "Rolled back"}, team=self.team, user=self.user
                )
                assert self.updates().count() == 0
                transaction.set_rollback(True)
        assert self.updates().count() == 0
        self.flag.refresh_from_db()
        assert self.flag.version == 1
        activity_storage.set_was_impersonated(True)
        try:
            with self.captureOnCommitCallbacks(execute=True), admit_v2_updates():
                flag_facade.update_flag(self.flag, {"version": 1, "name": "Committed"}, team=self.team, user=self.user)
                assert self.updates().count() == 0
        finally:
            activity_storage.clear_was_impersonated()
        entry = self.updates().get()
        assert entry.user_id == self.user.id
        assert entry.was_impersonated
        assert entry.detail is not None
        assert entry.detail["trigger"] == {"job_type": "audit_test", "job_id": "synthetic-job", "payload": {}}

    def test_internal_event_masks_config_without_losing_authorized_history(self) -> None:
        before = copy.deepcopy(self.flag.filters)
        with patch("posthog.cdp.internal_events.produce_internal_event") as produce:
            self.update(filters=config(rollout(metadata={"secret": "opaque-sentinel"})))
        event = next(
            call.kwargs["event"]
            for call in produce.call_args_list
            if call.kwargs["event"].properties.get("scope") == "FeatureFlag"
        )
        encoded = json.dumps(event.properties)
        assert "opaque-sentinel" not in encoded
        assert before["rules"][1]["seed"] not in encoded
        assert any(c["field"] == "filters" and c["after"] == "masked" for c in event.properties["detail"]["changes"])
        assert self.history(1)["filters"] == before
        assert self.history(2)["filters"]["rules"][0]["metadata"] == {"secret": "opaque-sentinel"}

    def test_facade_audits_the_locked_row_and_resolved_identity(self) -> None:
        stale = FeatureFlag.objects.get(pk=self.flag.pk)
        self.update(filters=config(rollout()), name="Changed before locking")
        before = copy.deepcopy(self.flag.filters)
        submitted = config(rollout(), targeted(None, metadata={"new": []}))
        original_request = copy.deepcopy(submitted)
        with admit_v2_updates():
            saved = flag_facade.update_flag(stale, {"version": 2, "filters": submitted}, team=self.team, user=self.user)
        assert submitted == original_request
        assert saved.name == "Changed before locking"
        assert saved.version == 3
        entry = self.updates().latest("created_at")
        assert entry.detail is not None
        change = next(c for c in entry.detail["changes"] if c["field"] == "filters")
        assert change["before"] == before
        assert change["after"] == saved.filters
        assert change["after"]["rules"][1]["id"]
        assert self.history(2)["filters"] == before

    @parameterized.expand(["context", "before", "after", "version", "missing_snapshot", "malformed_changes"])
    def test_incomplete_or_malformed_audit_data_is_not_repaired(self, field: str) -> None:
        self.update(filters=config(default_value=True))
        entry = self.updates().get()
        detail = entry.detail
        assert detail is not None
        if field == "context":
            detail.pop("context")
        elif field == "missing_snapshot":
            detail["changes"] = [c for c in detail["changes"] if c["field"] != "filters"]
        elif field == "malformed_changes":
            detail["changes"] = ["invalid"]
        elif field == "version":
            next(c for c in detail["changes"] if c["field"] == "version")["before"] = 0
        else:
            next(c for c in detail["changes"] if c["field"] == "filters")[field] = {"version": 2}
        entry.detail = detail
        entry.save()
        assert self.client.get(f"{self.url}versions/1/").status_code == 422

    @override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True)
    def test_later_mutation_of_returned_config_does_not_change_deferred_history(self) -> None:
        before = copy.deepcopy(self.flag.filters)
        with self.captureOnCommitCallbacks(execute=True), admit_v2_updates():
            saved = flag_facade.update_flag(
                self.flag, {"version": 1, "filters": config(rollout(None, None))}, team=self.team, user=self.user
            )
            persisted = copy.deepcopy(saved.filters)
            saved.filters["rules"][0]["metadata"] = {"later": True}
        entry = self.updates().get()
        assert entry.detail is not None
        change = next(c for c in entry.detail["changes"] if c["field"] == "filters")
        assert change["before"] == before
        assert change["after"] == persisted

    def test_version_read_is_scoped_to_the_flag_team(self) -> None:
        self.update(name="Second version")
        other = self.organization.teams.create(name="Other project")
        response = self.client.get(f"/api/projects/{other.id}/feature_flags/{self.flag.pk}/versions/1/")
        assert response.status_code == 404

    @parameterized.expand(
        [(field, version) for field in ("version", "filters", "name", "key", "tags") for version in (2, 3)]
    )
    def test_inconsistent_transition_snapshots_are_rejected(self, field: str, entry_version: int) -> None:
        self.update(filters=config(default_value=True), name="Second", key="second", tags=["second"])
        self.update(filters=config(default_value=False), name="Third", key="third", tags=["third"])
        entry = self.updates().order_by("created_at")[entry_version - 2]
        assert entry.detail is not None
        change = next(c for c in entry.detail["changes"] if c["field"] == field)
        if field == "version":
            change["before"] = 0
        else:
            change["after"] = {"filters": config(default_value=None), "tags": [], "name": "Wrong", "key": "wrong"}[
                field
            ]
        entry.save()

        response = self.client.get(f"{self.url}versions/2/")
        assert response.status_code == 422
        assert "incomplete" in response.json()["detail"]

    @override_settings(ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True)
    def test_deferred_audit_failure_leaves_history_explicitly_incomplete(self) -> None:
        with (
            self.assertRaisesMessage(RuntimeError, "Synthetic audit failure"),
            patch.object(ActivityLog.objects, "create", side_effect=RuntimeError("Synthetic audit failure")),
        ):
            with self.captureOnCommitCallbacks(execute=True), admit_v2_updates():
                saved = flag_facade.update_flag(
                    self.flag, {"version": 1, "filters": config(default_value=True)}, team=self.team, user=self.user
                )
                persisted = copy.deepcopy(saved.filters)
                assert self.updates().count() == 0
        self.flag.refresh_from_db()
        assert self.flag.version == 2
        assert self.flag.filters == persisted
        assert self.updates().count() == 0
        assert self.history(2)["filters"] == persisted
        response = self.client.get(f"{self.url}versions/1/")
        assert response.status_code == 422
        assert "incomplete" in response.json()["detail"]
