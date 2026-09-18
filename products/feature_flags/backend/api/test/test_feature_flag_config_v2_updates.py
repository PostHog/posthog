"""Config version 2 update path: closed in production, exercised through a test-only admission.

`config_writes.V2_UPDATE_LIMITS` is None in every deployed configuration, so the closed-path
tests here run with production settings and the admitted ones patch that one attribute.
Admitting updates is not PH-GATE-001 and not the common safety gate: no production v2 row may
exist, and these flags are invented test rows.
"""

import copy
import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.api.utils import ServiceRequest
from posthog.models import Organization, Team

from products.approvals.backend.models import ApprovalPolicy
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.facade import (
    api as flag_facade,
    config_writes,
)
from products.feature_flags.backend.facade.config_validation import ValidationLimits
from products.feature_flags.backend.models import FeatureFlag

ADMITTED_LIMITS = ValidationLimits(
    max_config_bytes=settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES, max_metadata_bytes=2048
)

RULE_A = "3f3b7a9e-8f2e-4f4b-9c7d-2a1e5b6c8d90"
RULE_B = "b1c2d3e4-f5a6-4b7c-8d9e-0f1a2b3c4d5e"
SEED_B = "7c9e6f82-1a2b-4c3d-9e8f-5a6b7c8d9e0f"
UNKNOWN_RULE = "00000000-0000-4000-8000-000000000000"


def admit_v2_updates():
    return patch.object(config_writes, "V2_UPDATE_LIMITS", ADMITTED_LIMITS)


def targeted(rule_id: str | None = RULE_A, **extra: Any) -> dict:
    rule = {"rule_type": "targeted_release", "targeting": {"properties": []}, "value": True, **extra}
    return {"id": rule_id, **rule} if rule_id is not None else rule


def rollout(rule_id: str | None = RULE_B, seed: str | None = SEED_B, **extra: Any) -> dict:
    rule: dict[str, Any] = {
        "rule_type": "percentage_rollout",
        "targeting": {"properties": []},
        "value": True,
        "rollout_percentage": 25,
        "on_rollout_miss": "continue",
        "assignment_algorithm": "sha1_60_v1",
        **extra,
    }
    if rule_id is not None:
        rule = {"id": rule_id, **rule}
    if seed is not None:
        rule["seed"] = seed
    return rule


def config(*rules: dict, **extra: Any) -> dict:
    return {"version": 2, "return_type": "boolean", "default_value": False, "rules": list(rules), **extra}


class V2UpdateTestCase(APIBaseTest):
    def flag(self, filters: dict | None = None, **extra: Any) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=extra.pop("key", "v2-flag"),
            filters=filters if filters is not None else config(targeted(), rollout()),
            version=3,
            created_by=self.user,
            **extra,
        )

    def patch_flag(self, flag: FeatureFlag, data: dict, method: str = "patch"):
        return getattr(self.client, method)(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", data, format="json"
        )


class TestV2UpdatesAreClosed(V2UpdateTestCase):
    """With production settings nothing reaches the v2 path, through any entrypoint."""

    @parameterized.expand(["patch", "put"])
    def test_http_v2_replacement_is_rejected_and_writes_nothing(self, method: str) -> None:
        flag = self.flag()
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"key": flag.key, "version": 3, "filters": config(targeted())}, method=method)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # A supplied discriminator is refused before the stored format is read: unchanged
        # precedence, unchanged code.
        assert response.json()["code"] == "reserved_config_version"
        flag.refresh_from_db()
        assert flag.filters == stored
        assert flag.version == 3

    def test_http_metadata_only_update_is_rejected(self) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "name": "Renamed"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unsupported_config_version"
        flag.refresh_from_db()
        assert flag.version == 3

    def test_http_v2_create_is_reserved(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", {"key": "new-v2", "filters": config()}, format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "reserved_config_version"
        assert not FeatureFlag.objects.filter(key="new-v2").exists()

    def test_facade_update_is_rejected(self) -> None:
        flag = self.flag()
        with self.assertRaises(Exception) as caught:
            flag_facade.update_flag(flag, {"version": 3, "filters": config(targeted())}, team=self.team, user=self.user)
        assert "reserved_config_version" in str(caught.exception.detail)  # type: ignore[attr-defined]
        flag.refresh_from_db()
        assert flag.version == 3

    def test_system_write_is_rejected(self) -> None:
        flag = self.flag()
        with self.assertRaises(Exception):
            flag_facade.update_flag(flag, {"version": 3, "filters": config(targeted())}, team=self.team, user=None)
        flag.refresh_from_db()
        assert flag.version == 3

    def test_direct_serializer_is_rejected(self) -> None:
        flag = self.flag()
        serializer = FeatureFlagSerializer(flag, data={"filters": config(targeted())}, partial=True)
        assert not serializer.is_valid()
        assert serializer.errors["filters"][0].code == "reserved_config_version"

    def test_approval_replay_is_rejected(self) -> None:
        flag = self.flag()
        serializer = FeatureFlagSerializer(
            flag,
            data={"filters": config(targeted())},
            partial=True,
            context={"request": ServiceRequest(self.user, method="PATCH"), "approval_apply": True},
        )
        assert not serializer.is_valid()
        assert serializer.errors["filters"][0].code == "reserved_config_version"


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"*"})
class TestAdmittedV2Updates(V2UpdateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(admit_v2_updates())

    def test_full_document_replaces_and_saves_once(self) -> None:
        flag = self.flag()
        replacement = config(targeted(description="Kept", metadata={"owner": "growth"}))
        response = self.patch_flag(flag, {"version": 3, "filters": replacement})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters == replacement  # the removed rollout rule is gone, nothing merged back
        assert flag.version == 4

    def test_empty_rules_list_is_a_valid_document(self) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "filters": config()})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters == config()

    def test_optional_fields_omitted_by_the_replacement_are_removed(self) -> None:
        flag = self.flag(config(targeted(description="Old", metadata={"a": 1})))
        response = self.patch_flag(flag, {"version": 3, "filters": config(targeted())})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters["rules"][0] == targeted()

    @parameterized.expand(
        [
            ("empty", {}),
            ("fragment", {"version": 2, "rules": []}),
            ("v1_shape", {"version": 2, "return_type": "boolean", "default_value": False, "groups": []}),
            ("downgrade", {"version": 1, "groups": []}),
            ("no_discriminator", {"return_type": "boolean", "default_value": False, "rules": []}),
        ]
    )
    def test_incomplete_or_reshaped_documents_are_rejected(self, _name: str, filters: dict) -> None:
        flag = self.flag()
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"version": 3, "filters": filters})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.filters == stored
        assert flag.version == 3

    @parameterized.expand([("null", None), ("list", []), ("string", "x")])
    def test_non_object_filters_are_rejected(self, _name: str, filters: Any) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "filters": filters})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    def test_omitted_filters_preserves_the_config_exactly(self) -> None:
        flag = self.flag()
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"version": 3, "name": "Renamed"})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters == stored
        assert flag.name == "Renamed"
        assert flag.version == 4

    @parameterized.expand(
        [
            ("false_default", {"default_value": False}),
            ("null_default", {"default_value": None}),
            ("true_default", {"default_value": True}),
        ]
    )
    def test_document_level_values_round_trip(self, _name: str, extra: dict) -> None:
        flag = self.flag()
        document = config(targeted(), **extra)
        response = self.patch_flag(flag, {"version": 3, "filters": document})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters == document

    @parameterized.expand([("zero", 0), ("hundred", 100), ("two_decimals", 33.33)])
    def test_percentages_round_trip(self, _name: str, percentage: Any) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "filters": config(rollout(rollout_percentage=percentage))})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters["rules"][0]["rollout_percentage"] == percentage


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"*"})
class TestServerOwnedIdentity(V2UpdateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(admit_v2_updates())

    def test_new_rules_get_server_identity(self) -> None:
        flag = self.flag(config())
        submitted = config(targeted(rule_id=None), rollout(rule_id=None, seed=None))
        sent = copy.deepcopy(submitted)
        response = self.patch_flag(flag, {"version": 3, "filters": submitted})
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert submitted == sent  # the request document is never mutated in place
        flag.refresh_from_db()
        ids = [rule["id"] for rule in flag.filters["rules"]]
        assert len(set(ids)) == 2
        assert flag.filters["rules"][1]["seed"] not in (None, "")

    def test_identity_survives_reorder_and_unrelated_edits(self) -> None:
        flag = self.flag()
        response = self.patch_flag(
            flag,
            {"version": 3, "filters": config(rollout(rollout_percentage=90), targeted(value=False))},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert [rule["id"] for rule in flag.filters["rules"]] == [RULE_B, RULE_A]
        assert flag.filters["rules"][0]["seed"] == SEED_B

    def test_an_omitted_seed_is_taken_from_the_locked_row(self) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "filters": config(rollout(seed=None))})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters["rules"][0]["seed"] == SEED_B

    def test_a_rule_that_becomes_randomized_gets_a_fresh_seed(self) -> None:
        flag = self.flag(config(targeted()))
        response = self.patch_flag(flag, {"version": 3, "filters": config(rollout(rule_id=RULE_A, seed=None))})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert flag.filters["rules"][0]["id"] == RULE_A
        assert flag.filters["rules"][0]["seed"] not in (None, "", SEED_B)

    @parameterized.expand(
        [
            ("unknown_id", config(targeted(rule_id=UNKNOWN_RULE))),
            ("hijacked_id", config(targeted(), targeted(rule_id=RULE_A, value=False))),
            ("null_id", config(targeted(rule_id=None) | {"id": None})),
            ("chosen_seed", config(rollout(rule_id=None, seed="chosen-by-client"))),
            ("changed_seed", config(rollout(seed="chosen-by-client"))),
        ]
    )
    def test_client_chosen_identity_is_rejected(self, _name: str, filters: dict) -> None:
        flag = self.flag()
        stored = copy.deepcopy(flag.filters)
        response = self.patch_flag(flag, {"version": 3, "filters": filters})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.filters == stored
        assert flag.version == 3


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"*"})
class TestV2Concurrency(V2UpdateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(admit_v2_updates())

    @parameterized.expand([("missing", {}), ("null", {"version": None}), ("string", {"version": "3"})])
    def test_an_absent_or_malformed_token_is_rejected(self, _name: str, data: dict) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"filters": config(targeted()), **data})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    def test_a_stale_token_conflicts_even_without_conflicting_fields(self) -> None:
        flag = self.flag()
        response = self.patch_flag(
            flag,
            {
                "version": 2,
                "filters": config(targeted()),
                # v1 would accept this as a non-conflicting stale update; a v2 replacement
                # rewrites the whole document, so the stale token alone is the conflict.
                "original_flag": {"name": flag.name},
            },
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        flag.refresh_from_db()
        assert flag.version == 3

    def test_the_token_applies_to_metadata_only_updates(self) -> None:
        flag = self.flag()
        assert self.patch_flag(flag, {"name": "No token"}).status_code == status.HTTP_400_BAD_REQUEST
        assert self.patch_flag(flag, {"version": 1, "name": "Stale"}).status_code == status.HTTP_409_CONFLICT
        flag.refresh_from_db()
        assert flag.version == 3

    def test_a_second_writer_on_a_stale_instance_cannot_reuse_a_version(self) -> None:
        flag = self.flag()
        stale = FeatureFlag.objects.get(pk=flag.pk)
        assert self.patch_flag(flag, {"version": 3, "filters": config(targeted())}).status_code == 200
        response = self.patch_flag(stale, {"version": 3, "filters": config(rollout())})
        assert response.status_code == status.HTTP_409_CONFLICT
        flag.refresh_from_db()
        assert flag.version == 4
        assert flag.filters == config(targeted())


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"*"})
class TestV2AdmissionBoundary(V2UpdateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(admit_v2_updates())

    @parameterized.expand(
        [
            ("malformed", {"version": 2, "rules": "broken"}),
            ("deferred_experiment", config({"id": RULE_A, "rule_type": "experiment", "targeting": {}})),
            ("deferred_string", config(return_type="string")),
        ]
    )
    def test_unsupported_stored_configs_are_not_replaced(self, _name: str, stored: dict) -> None:
        flag = self.flag(stored)
        response = self.patch_flag(flag, {"version": 3, "filters": config(targeted(rule_id=None))})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.filters == stored
        assert flag.version == 3

    def test_an_experiment_rule_cannot_be_written(self) -> None:
        flag = self.flag()
        response = self.patch_flag(
            flag,
            {"version": 3, "filters": config({"id": RULE_A, "rule_type": "experiment", "targeting": {}})},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    @parameterized.expand(
        [
            ("active", {"active": False}),
            ("archived", {"archived": True, "active": False}),
            ("deleted", {"deleted": True}),
            ("remote_config", {"is_remote_configuration": True}),
            ("encrypted", {"has_encrypted_payloads": True}),
            ("continuity", {"ensure_experience_continuity": True}),
            ("runtime", {"evaluation_runtime": "server"}),
        ]
    )
    def test_unsupported_metadata_operations_are_rejected(self, _name: str, data: dict) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, **data})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unsupported_config_version"
        flag.refresh_from_db()
        assert flag.version == 3

    def test_supported_metadata_operations_work(self) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "name": "Renamed", "key": "v2-renamed", "tags": []})
        assert response.status_code == status.HTTP_200_OK, response.json()
        flag.refresh_from_db()
        assert (flag.name, flag.key, flag.version) == ("Renamed", "v2-renamed", 4)

    def test_a_row_with_encrypted_payloads_is_not_admitted(self) -> None:
        # Not in the admitted family, so the write falls back to the closed path rather
        # than gaining a v2 route through it.
        flag = self.flag(has_encrypted_payloads=True)
        response = self.patch_flag(flag, {"version": 3, "filters": config(targeted())})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "reserved_config_version"

    def test_an_enabled_approval_policy_denies_the_update(self) -> None:
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.update",
            approver_config={},
            enabled=True,
        )
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "filters": config(targeted())})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "unsupported_config_version"
        flag.refresh_from_db()
        assert flag.version == 3

    def test_approval_replay_is_rejected_even_when_admitted(self) -> None:
        flag = self.flag()
        serializer = FeatureFlagSerializer(
            flag,
            data={"version": 3, "filters": config(targeted())},
            partial=True,
            context={"request": ServiceRequest(self.user, method="PATCH"), "approval_apply": True},
        )
        assert not serializer.is_valid()
        assert "unsupported_config_version" in str(serializer.errors)

    def test_the_facade_reaches_the_admitted_path(self) -> None:
        flag = self.flag()
        updated = flag_facade.update_flag(
            flag, {"version": 3, "filters": config(targeted())}, team=self.team, user=self.user
        )
        assert updated.filters == config(targeted())
        assert updated.version == 4

    def test_another_team_cannot_reach_the_flag(self) -> None:
        other = FeatureFlag.objects.create(
            team=Team.objects.create(organization=Organization.objects.create(name="other org")),
            key="other-v2",
            filters=config(targeted()),
            version=1,
        )
        response = self.patch_flag(other, {"version": 1, "filters": config()})
        assert response.status_code == status.HTTP_404_NOT_FOUND


@override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES={"*"})
class TestV2RequestBytes(V2UpdateTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(admit_v2_updates())

    def post_bytes(self, flag: FeatureFlag, body: str):
        return self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", body, content_type="application/json"
        )

    def test_duplicate_keys_in_the_request_bytes_are_rejected(self) -> None:
        flag = self.flag()
        body = '{"version": 3, "filters": {"version": 1, "version": 2, "return_type": "boolean", "default_value": false, "rules": []}}'
        assert json.loads(body)["filters"]["version"] == 2  # normalization would hide the first key
        response = self.post_bytes(flag, body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    @parameterized.expand([("nan", "NaN"), ("infinity", "Infinity"), ("precision", "33.333")])
    def test_lossy_numbers_never_become_valid(self, _name: str, literal: str) -> None:
        flag = self.flag()
        body = (
            '{"version": 3, "filters": {"version": 2, "return_type": "boolean", "default_value": false, '
            '"rules": [{"rule_type": "percentage_rollout", "targeting": {"properties": []}, "value": true, '
            f'"rollout_percentage": {literal}, "on_rollout_miss": "continue", '
            '"assignment_algorithm": "sha1_60_v1"}]}}'
        )
        response = self.post_bytes(flag, body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    def test_the_deployment_byte_limit_applies(self) -> None:
        flag = self.flag()
        with override_settings(MAX_FEATURE_FLAG_FILTER_SIZE_BYTES=200):
            response = self.patch_flag(flag, {"version": 3, "filters": config(targeted(description="x" * 400))})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    def test_the_metadata_byte_limit_applies(self) -> None:
        flag = self.flag()
        response = self.patch_flag(flag, {"version": 3, "filters": config(targeted(metadata={"note": "x" * 4000}))})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3

    def test_v1_only_keys_are_not_stripped_into_validity(self) -> None:
        # The v1 write path opportunistically drops these keys on save; doing that to a v2
        # document would turn a request the validator rejects into an accepted one.
        flag = self.flag()
        response = self.patch_flag(
            flag, {"version": 3, "filters": config(targeted(), super_groups=[], holdout_groups=[])}
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        flag.refresh_from_db()
        assert flag.version == 3
