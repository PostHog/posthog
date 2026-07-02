import json
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from freezegun.api import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    FuzzyInt,
    _create_person,
    flush_persons_and_events,
    snapshot_clickhouse_queries,
    snapshot_postgres_queries_context,
)
from unittest.mock import ANY, MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils.timezone import now

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY
from rest_framework import status
from rest_framework.relations import ManyRelatedField

from posthog import redis
from posthog.api.cohort import BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS, get_cohort_actors_for_feature_flag
from posthog.api.services.flags_service import FlagVersionConflictError
from posthog.constants import AvailableFeature
from posthog.models import TaggedItem, User
from posthog.models.group.util import create_group
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.db_context_capturing import capture_db_queries
from posthog.test.persons import (
    create_group as create_test_group,
    create_group_type_mapping,
    create_person,
)
from posthog.test.test_utils import create_group_type_mapping_without_created_at

from products.cohorts.backend.models.calculation_history import CohortCalculationHistory
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import CohortErrorCode, get_friendly_error_message
from products.dashboards.backend.models.dashboard import Dashboard
from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer, parse_created_by_ids
from products.feature_flags.backend.encrypted_flag_payloads import (
    REDACTED_PAYLOAD_VALUE,
    flag_payload_codec,
    get_decrypted_flag_payload,
)
from products.feature_flags.backend.flag_status import FeatureFlagStatus
from products.feature_flags.backend.models.feature_flag import (
    FeatureFlag,
    FeatureFlagDashboards,
    get_feature_flags_for_team_in_cache,
)
from products.feature_flags.backend.user_blast_radius import get_user_blast_radius_persons
from products.product_analytics.backend.models.insight import Insight
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

from ee.models.rbac.access_control import AccessControl


def _make_feature_flag_psak(
    team: Team, label: str = "psak", scopes: list[str] | None = None
) -> tuple[str, ProjectSecretAPIKey]:
    # Token must match _SECRET_API_KEY_RE = r"^phs_[a-zA-Z0-9]+$", so only alphanumerics after phs_.
    suffix = "".join(c for c in label if c.isalnum())
    token = "phs_" + ("b" * 35) + suffix
    psak = ProjectSecretAPIKey.objects.create(
        team=team,
        label=label,
        mask_value=f"phs_...{suffix[:4]}",
        secure_value=hash_key_value(token),
        scopes=["feature_flag:read"] if scopes is None else scopes,
    )
    return token, psak


class TestFeatureFlag(APIBaseTest, ClickhouseTestMixin):
    feature_flag: FeatureFlag = None  # type: ignore

    maxDiff = None

    def setUp(self):
        cache.clear()

        # delete all keys in redis
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)

        # Temporary: keep the remote_config Rust shadow (phase 2) inert so endpoint tests never make
        # a real outbound call. Delete with remote_config_shadow.py at the phase-3 cutover.
        shadow_patcher = patch("products.feature_flags.backend.api.feature_flag.shadow_compare_remote_config")
        shadow_patcher.start()
        self.addCleanup(shadow_patcher.stop)

        return super().setUp()

    @staticmethod
    def _insight_query_value(insight: Any) -> Any:
        query = cast(dict[str, Any], insight.query)
        return query["source"]["properties"]["values"][0]["values"][0]["value"]

    def test_cant_create_flag_with_duplicate_key(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        count = FeatureFlag.objects.count()
        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a feature flag with this key.",
                "attr": "key",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    @parameterized.expand(
        [
            ("foo?bar=baz",),
            ("foo/bar",),
            ("foo\\bar",),
            ("foo.bar",),
            ("foo bar",),
        ]
    )
    def test_cant_create_flag_with_key_with_invalid_characters(self, key):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        count = FeatureFlag.objects.count()
        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {"name": "Beta feature", "key": key},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_key",
                "detail": "Only letters, numbers, hyphens (-) & underscores (_) are allowed.",
                "attr": "key",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_create_flag_with_key_too_long(self):
        key = "a" * 400 + "b"
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        count = FeatureFlag.objects.count()
        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {"name": "Beta feature", "key": key},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "max_length",
                "detail": "Ensure this field has no more than 400 characters.",
                "attr": "key",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_create_flag_with_invalid_filters(self):
        count = FeatureFlag.objects.count()

        invalid_operators = [
            "icontains",
            "regex",
            "not_icontains",
            "not_regex",
            "lt",
            "gt",
            "lte",
            "gte",
        ]

        for operator in invalid_operators:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "name": "Beta feature",
                    "key": "beta-x",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": ["@posthog.com"],
                                        "operator": operator,
                                    }
                                ],
                            }
                        ]
                    },
                },
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_value",
                    "detail": f"Invalid value for operator {operator}: ['@posthog.com']",
                    "attr": "filters",
                },
            )

        self.assertEqual(FeatureFlag.objects.count(), count)

        # Test that a string value is still acceptable
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": '["@posthog.com"]',  # fine as long as a string
                                    "operator": "not_regex",
                                }
                            ],
                        }
                    ]
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(
        [
            ("in",),
            ("not_in",),
        ]
    )
    def test_cant_create_flag_with_in_operator_for_person_properties(self, operator: str) -> None:
        count = FeatureFlag.objects.count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": f"beta-person-{operator}",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["user1@example.com", "user2@example.com"],
                                    "operator": operator,
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_operator",
                "detail": f"The '{operator}' operator is only valid for cohort properties, not 'person' properties.",
                "attr": "filters",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    @parameterized.expand(
        [
            ("contains",),
            ("not_contains",),
            ("ICONTAINS",),
            ("foo",),
        ]
    )
    def test_cant_create_flag_with_unknown_operator(self, operator: str) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-unknown-op",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "@posthog.com",
                                    "operator": operator,
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_operator",
                "detail": f"Invalid operator: {operator}",
                "attr": "filters",
            },
        )

    @parameterized.expand(
        [
            ("exact",),
            ("icontains",),
            ("regex",),
            ("is_set",),
            ("is_date_before",),
            ("is_date_exact",),
            ("semver_gt",),
        ]
    )
    def test_can_create_flag_with_valid_operator(self, operator: str) -> None:
        value = (
            ""
            if operator == "is_set"
            else "2025-01-01"
            if "date" in operator
            else "1.2.3"
            if "semver" in operator
            else "test"
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": f"Flag with {operator}",
                "key": f"flag-valid-op-{operator}",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": value,
                                    "operator": operator,
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_can_create_flag_with_flag_evaluates_to_operator(self) -> None:
        base_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="base-flag",
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Dependent flag",
                "key": "dependent-flag",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": str(base_flag.id),
                                    "type": "flag",
                                    "value": "true",
                                    "operator": "flag_evaluates_to",
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(
        [
            ("in",),
            ("not_in",),
        ]
    )
    def test_can_create_flag_with_in_operator_for_cohort_properties(self, operator: str) -> None:
        cohort = Cohort.objects.create(team=self.team, name="test cohort", created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": f"Cohort feature {operator}",
                "key": f"cohort-feature-{operator}",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort.pk,
                                    "operator": operator,
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], f"cohort-feature-{operator}")

    def test_saving_flag_strips_legacy_holdout_groups(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="holdout-cleanup-test",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "holdout_groups": [{"properties": [], "rollout_percentage": 10, "variant": "holdout-1"}],
                "holdout": {"id": 1, "exclusion_percentage": 10},
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.pk}",
            {"name": "Updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flag.refresh_from_db()
        self.assertNotIn("holdout_groups", flag.filters)
        self.assertEqual(flag.filters["holdout"], {"id": 1, "exclusion_percentage": 10})

    def test_saving_flag_strips_legacy_super_groups(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="sg-cleanup",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "super_groups": [{"properties": [], "rollout_percentage": 100}],
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.pk}",
            {"name": "Updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flag.refresh_from_db()
        self.assertNotIn("super_groups", flag.filters)

    def test_saving_flag_strips_legacy_holdout_groups_without_holdout_key(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="holdout-cleanup-test-legacy",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "holdout_groups": [{"properties": [], "rollout_percentage": 10, "variant": "holdout-1"}],
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.pk}",
            {"name": "Updated"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flag.refresh_from_db()
        self.assertNotIn("holdout_groups", flag.filters)

    def test_cant_update_flag_with_duplicate_key(self):
        existing_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{another_feature_flag.pk}",
            {"name": "Beta feature", "key": "red_button"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a feature flag with this key.",
                "attr": "key",
            },
        )
        another_feature_flag.refresh_from_db()
        self.assertEqual(another_feature_flag.key, "some-feature")

        # Try updating the existing one
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{existing_flag.id}/",
            {"name": "Beta feature 3", "key": "red_button"},
        )
        self.assertEqual(response.status_code, 200)
        existing_flag.refresh_from_db()
        self.assertEqual(existing_flag.name, "Beta feature 3")

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_group_type_index_feature_flag(self, mock_report_user_action):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 65}],
                },
            },
            format="json",
        ).json()
        # Assert analytics are sent
        instance = FeatureFlag.objects.get(id=feature_flag["id"])
        mock_report_user_action.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": True,
                "payload_count": 0,
                "creation_context": "feature_flags",
            },
            team=ANY,
            request=ANY,
        )

    @parameterized.expand(
        [
            ("false", False, "bool"),
            ("true", True, "bool"),
            ("string", "not_an_int", "str"),
            ("float", 1.5, "float"),
        ]
    )
    def test_non_integer_aggregation_group_type_index_rejected(self, _name, bad_value, expected_type):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Bad index flag",
                "key": f"bad-index-{_name}",
                "filters": {
                    "aggregation_group_type_index": bad_value,
                    "groups": [{"rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_type, response.json()["detail"])

    @parameterized.expand(
        [
            ("false", False, "bool"),
            ("true", True, "bool"),
            ("int", 42, "int"),
        ]
    )
    def test_non_string_group_variant_rejected(self, _name, bad_value, expected_type):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Bad variant flag",
                "key": f"bad-variant-{_name}",
                "filters": {
                    "groups": [{"variant": bad_value, "rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_type, response.json()["detail"])

    def test_string_group_variant_preserved(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "String variant flag",
                "key": "string-variant-preserved",
                "filters": {
                    "groups": [{"variant": "control", "rollout_percentage": 100}],
                    "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="string-variant-preserved", team=self.team)
        self.assertEqual(flag.filters["groups"][0]["variant"], "control")

    @parameterized.expand(
        [
            ("true", True),
            ("false", False),
        ]
    )
    @patch("products.feature_flags.backend.api.feature_flag.feature_enabled_or_false")
    def test_boolean_early_exit_accepted(self, _name, value, mock_feature_enabled):
        mock_feature_enabled.return_value = True
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"Early exit {_name}",
                "key": f"early-exit-{_name}",
                "filters": {
                    "early_exit": value,
                    "groups": [{"rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key=f"early-exit-{_name}", team=self.team)
        self.assertEqual(flag.filters["early_exit"], value)

    @patch("products.feature_flags.backend.api.feature_flag.feature_enabled_or_false")
    def test_early_exit_rejected_without_feature_flag(self, mock_feature_enabled):
        mock_feature_enabled.return_value = False
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Early exit gated",
                "key": "early-exit-gated",
                "filters": {
                    "early_exit": True,
                    "groups": [{"rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("early_exit is not available", response.json()["detail"])

    @patch("products.feature_flags.backend.api.feature_flag.feature_enabled_or_false")
    def test_early_exit_false_accepted_without_feature_flag(self, mock_feature_enabled):
        mock_feature_enabled.return_value = False
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Early exit off",
                "key": "early-exit-off",
                "filters": {
                    "early_exit": False,
                    "groups": [{"rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("products.feature_flags.backend.api.feature_flag.feature_enabled_or_false")
    def test_early_exit_unchanged_truthy_allowed_when_flag_disabled(self, mock_feature_enabled):
        # A flag created while the feature was enabled keeps working if access is later revoked,
        # as long as the PATCH doesn't newly turn early_exit on.
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="early-exit-existing",
            filters={"early_exit": True, "groups": [{"rollout_percentage": 100}]},
        )
        mock_feature_enabled.return_value = False
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            data={"filters": {"early_exit": True, "groups": [{"rollout_percentage": 50}]}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_null_early_exit_accepted(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Early exit null",
                "key": "early-exit-null",
                "filters": {
                    "early_exit": None,
                    "groups": [{"rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @parameterized.expand(
        [
            ("int", 1, "int"),
            ("string_true", "true", "str"),
            ("string_false", "false", "str"),
            ("float", 1.5, "float"),
        ]
    )
    def test_non_boolean_early_exit_rejected(self, _name, bad_value, expected_type):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"Bad early_exit {_name}",
                "key": f"bad-early-exit-{_name}",
                "filters": {
                    "early_exit": bad_value,
                    "groups": [{"rollout_percentage": 100}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("early_exit must be a boolean", response.json()["detail"])
        self.assertIn(expected_type, response.json()["detail"])

    @parameterized.expand(
        [
            ("string_int", "100"),
            ("bool_false", False),
            ("string_nan", "NaN"),
            ("string_inf", "Infinity"),
            ("float_nan", float("nan")),
            ("float_inf", float("inf")),
        ]
    )
    def test_non_numeric_group_rollout_percentage_rejected(self, _name, bad_value):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Bad rollout flag",
                "key": f"bad-rollout-{_name}",
                "filters": {
                    "groups": [{"rollout_percentage": bad_value}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rollout_percentage", response.json()["detail"])

    @parameterized.expand(
        [
            ("negative_one", -1),
            ("negative_fraction", -0.1),
            ("over_hundred", 101),
            ("two_hundred", 200),
            ("just_over", 100.1),
        ]
    )
    def test_out_of_range_group_rollout_percentage_rejected(self, _name, bad_value):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Out of range rollout flag",
                "key": f"oor-rollout-{_name}",
                "filters": {
                    "groups": [{"rollout_percentage": bad_value}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("between 0 and 100", response.json()["detail"])

    @parameterized.expand(
        [
            ("zero", 0, 0),
            ("hundred", 100, 100),
            ("seventy_five", 75, 75),
            ("fifty_point_five", 50.5, 50.5),
        ]
    )
    def test_valid_group_rollout_percentage_preserved(self, _name, value, expected):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Valid rollout",
                "key": f"valid-rollout-{_name}",
                "filters": {
                    "groups": [{"rollout_percentage": value}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key=f"valid-rollout-{_name}", team=self.team)
        self.assertEqual(flag.filters["groups"][0]["rollout_percentage"], expected)

    # Same _validate_rollout_percentage function as group tests; smoke-testing the call site
    @parameterized.expand(
        [
            ("string_int", "50"),
            ("bool_true", True),
            ("null", None),
        ]
    )
    def test_non_numeric_variant_rollout_percentage_rejected(self, _name, bad_value):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Bad variant rollout",
                "key": f"bad-variant-rollout-{_name}",
                "filters": {
                    "groups": [{"rollout_percentage": 100}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": bad_value},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("rollout_percentage", response.json()["detail"])

    @parameterized.expand(
        [
            ("false", False, "bool"),
            ("true", True, "bool"),
            ("string", "not_an_int", "str"),
            ("float", 1.5, "float"),
        ]
    )
    def test_non_integer_property_group_type_index_rejected(self, _name, bad_value, expected_type):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Bad gti flag",
                "key": f"bad-prop-gti-{_name}",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {"key": "email", "type": "person", "value": "test", "group_type_index": bad_value}
                            ],
                        }
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_type, response.json()["detail"])

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_feature_flag(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        # Assert analytics are sent
        mock_report_user_action.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
                "creation_context": "feature_flags",
            },
            team=ANY,
            request=ANY,
        )

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {"first_name": "", "email": "user1@posthog.com"},
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "alpha-feature",
                        "short_id": None,
                    },
                }
            ],
        )

        self.assertEqual(instance.created_by, self.user)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_minimal_feature_flag(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "omega-feature",
                "filters": {"groups": [{"properties": [], "rollout_percentage": None}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], "omega-feature")
        self.assertEqual(response.json()["name"], "")
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "omega-feature")
        self.assertEqual(instance.name, "")

        # Assert analytics are sent
        mock_report_user_action.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": False,
                "has_filters": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
                "creation_context": "feature_flags",
            },
            team=ANY,
            request=ANY,
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_remote_config_flag_defaults_to_100_percent_rollout(self, mock_report_user_action):
        """Test that remote config flags default to 100% rollout in various scenarios."""
        test_cases = [
            (
                "no filters",
                {"key": "rc-no-filters", "name": "RC No Filters", "is_remote_configuration": True},
            ),
            (
                "explicit 0% rollout",
                {
                    "key": "rc-zero-rollout",
                    "name": "RC Zero Rollout",
                    "is_remote_configuration": True,
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 0, "variant": None}],
                        "payloads": {"true": '{"key": "value"}'},
                    },
                },
            ),
            (
                "None rollout_percentage",
                {
                    "key": "rc-null-rollout",
                    "name": "RC Null Rollout",
                    "is_remote_configuration": True,
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": None, "variant": None}],
                        "payloads": {"true": '{"key": "value"}'},
                    },
                },
            ),
            (
                "missing rollout_percentage",
                {
                    "key": "rc-missing-rollout",
                    "name": "RC Missing Rollout",
                    "is_remote_configuration": True,
                    "filters": {
                        "groups": [{"properties": [], "variant": None}],
                        "payloads": {"true": '{"key": "value"}'},
                    },
                },
            ),
        ]
        for description, payload in test_cases:
            with self.subTest(description):
                response = self.client.post(
                    f"/api/projects/{self.team.id}/feature_flags/",
                    payload,
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                response_data = response.json()
                self.assertTrue(response_data["is_remote_configuration"])
                self.assertEqual(response_data["filters"]["groups"][0]["rollout_percentage"], 100)

                instance = FeatureFlag.objects.get(id=response_data["id"])
                self.assertEqual(instance.filters["groups"][0]["rollout_percentage"], 100)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_encrypted_payloads_requires_remote_configuration(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "encrypted-without-remote",
                "name": "Encrypted Without Remote",
                "has_encrypted_payloads": True,
                "is_remote_configuration": False,
                "filters": {"groups": [{"rollout_percentage": 100}], "payloads": {"true": '"secret"'}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("remote configuration", response.json()["detail"])

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_encrypted_payloads_with_remote_configuration_succeeds(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "encrypted-with-remote",
                "name": "Encrypted With Remote",
                "has_encrypted_payloads": True,
                "is_remote_configuration": True,
                "filters": {"groups": [{"rollout_percentage": 100}], "payloads": {"true": '"secret"'}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_remote_config_flag_to_non_remote_with_encrypted_payloads_fails(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "rc-encrypted",
                "name": "RC Encrypted",
                "has_encrypted_payloads": True,
                "is_remote_configuration": True,
                "filters": {"groups": [{"rollout_percentage": 100}], "payloads": {"true": '"secret"'}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"is_remote_configuration": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("remote configuration", response.json()["detail"])

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_non_remote_flag_to_encrypted_payloads_fails(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "non-remote-flag",
                "name": "Non Remote",
                "is_remote_configuration": False,
                "filters": {"groups": [{"rollout_percentage": 100}], "payloads": {"true": '"data"'}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"has_encrypted_payloads": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("remote configuration", response.json()["detail"])

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_flag_to_remote_config_persists(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "toggle-to-remote-config",
                "name": "Toggle To Remote Config",
                "filters": {"groups": [{"rollout_percentage": 100}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        self.assertFalse(response.json()["is_remote_configuration"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"is_remote_configuration": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_remote_configuration"])
        self.assertTrue(FeatureFlag.objects.get(id=flag_id).is_remote_configuration)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_remote_config_flag_to_non_remote_without_encryption_succeeds(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "rc-unencrypted",
                "name": "RC Unencrypted",
                "is_remote_configuration": True,
                "filters": {"groups": [{"rollout_percentage": 100}], "payloads": {"true": '"data"'}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {"is_remote_configuration": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["is_remote_configuration"])
        self.assertFalse(FeatureFlag.objects.get(id=flag_id).is_remote_configuration)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_feature_flag_with_analytics_dashboards(self, mock_report_user_action):
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "feature-with-analytics-dashboards",
                "analytics_dashboards": [dashboard.pk],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], "feature-with-analytics-dashboards")
        self.assertEqual(len(response.json()["analytics_dashboards"]), 1)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "feature-with-analytics-dashboards")
        self.assertEqual(instance.analytics_dashboards.all()[0].id, dashboard.pk)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_feature_flag_rejects_dashboard_from_other_team(self, mock_report_user_action):
        other_team = Team.objects.create(organization=self.organization, api_token="token_other", name="Other Team")
        other_dashboard = Dashboard.objects.create(team=other_team, name="other team dashboard", created_by=self.user)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "flag-with-other-dashboard",
                "analytics_dashboards": [other_dashboard.pk],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "analytics_dashboards")
        self.assertIn("does not exist", response.json()["detail"])

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_feature_flag_rejects_dashboard_from_other_team(self, mock_report_user_action):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="flag-to-update",
            name="Flag to Update",
            created_by=self.user,
        )

        other_team = Team.objects.create(
            organization=self.organization,
            api_token="token_other_update",
            name="Other Team",
        )
        other_dashboard = Dashboard.objects.create(team=other_team, name="other team dashboard", created_by=self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.pk}/",
            {"analytics_dashboards": [other_dashboard.pk]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "analytics_dashboards")
        self.assertIn("does not exist", response.json()["detail"])

    def test_serializer_without_team_context_returns_empty_dashboard_queryset(self):
        """When team_id is missing from context, analytics_dashboards should allow nothing (fail safe)."""
        Dashboard.objects.create(team=self.team, name="test dashboard", created_by=self.user)

        # Instantiate serializer WITHOUT team_id in context
        serializer = FeatureFlagSerializer(context={})
        fields = serializer.get_fields()

        # The queryset should be empty (fail safe to prevent IDOR)
        analytics_field = cast(ManyRelatedField, fields["analytics_dashboards"])
        self.assertEqual(analytics_field.child_relation.get_queryset().count(), 0)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_feature_flag_with_evaluation_runtime(self, mock_report_user_action):
        # Test creating a feature flag with different evaluation_runtime values

        # Test with "server"
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "server-side-flag", "evaluation_runtime": "server"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], "server-side-flag")
        self.assertEqual(response.json()["evaluation_runtime"], "server")
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.evaluation_runtime, "server")

        # Test with "client"
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "client-side-flag", "evaluation_runtime": "client"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["evaluation_runtime"], "client")

        # Test with "all"
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "all-flag", "evaluation_runtime": "all"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["evaluation_runtime"], "all")

        # Test default value (should be "all")
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "default-flag"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["evaluation_runtime"], "all")

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_feature_flag_evaluation_runtime(self, mock_report_user_action):
        # Create a flag with default evaluation_runtime
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "flag-to-update"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        self.assertEqual(response.json()["evaluation_runtime"], "all")

        # Update to "server"
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            {"evaluation_runtime": "server"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["evaluation_runtime"], "server")

        # Verify in database
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.evaluation_runtime, "server")

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_multivariate_feature_flag(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
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
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "multivariate-feature")

        # Assert analytics are sent
        mock_report_user_action.assert_called_once_with(
            self.user,
            "feature flag created",
            {
                "groups_count": 1,
                "has_variants": True,
                "variants_count": 3,
                "has_filters": False,
                "has_rollout_percentage": False,
                "filter_count": 0,
                "created_at": instance.created_at,
                "aggregating_by_groups": False,
                "payload_count": 0,
                "creation_context": "feature_flags",
            },
            team=ANY,
            request=ANY,
        )

    @parameterized.expand(
        [
            ("lt_100", 0),  # 50 + 25 + 0 = 75
            ("gt_100", 50),  # 50 + 25 + 50 = 125
        ]
    )
    def test_cant_create_multivariate_feature_flag_with_variant_rollout_not_100(self, _name, third_variant_rollout):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
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
                                "rollout_percentage": third_variant_rollout,
                            },
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Invalid variant definitions: Variant rollout percentages must sum to 100.",
        )

    def test_cant_update_multivariate_feature_flag_with_variant_rollout_not_100(self):
        # Create initial flag
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 50},
                        ]
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        feature_flag_id = response.json()["id"]

        # Try to update with invalid percentages
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "control", "rollout_percentage": 50},
                            {"key": "test", "rollout_percentage": 40},
                        ]
                    },
                }
            },
            format="json",
        )

        # Verify error response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Invalid variant definitions: Variant rollout percentages must sum to 100.",
        )

        # Verify flag wasn't updated
        feature_flag = FeatureFlag.objects.get(id=feature_flag_id)
        self.assertEqual(
            feature_flag.filters["multivariate"]["variants"][0]["rollout_percentage"],
            50,
        )
        self.assertEqual(
            feature_flag.filters["multivariate"]["variants"][1]["rollout_percentage"],
            50,
        )

    def test_cant_create_feature_flag_without_key(self):
        count = FeatureFlag.objects.count()
        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "key",
            },
        )
        self.assertEqual(FeatureFlag.objects.count(), count)

    def test_cant_create_multivariate_feature_flag_with_invalid_variant_overrides(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": None,
                            "variant": "unknown-variant",
                        }
                    ],
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
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Filters are not valid (variant override does not exist)",
        )

    def test_cant_update_multivariate_feature_flag_with_invalid_variant_overrides(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": None,
                            "variant": "second-variant",
                        }
                    ],
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
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        feature_flag_id = response.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": None,
                            "variant": "unknown-variant",
                        }
                    ],
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
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json().get("type"), "validation_error")
        self.assertEqual(
            response.json().get("detail"),
            "Filters are not valid (variant override does not exist)",
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "Updated name",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                    }
                                ],
                            }
                        ]
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["name"], "Updated name")
        self.assertEqual(response.json()["filters"]["groups"][0]["rollout_percentage"], 65)

        # Assert analytics are sent
        mock_report_user_action.assert_called_with(
            self.user,
            "feature flag updated",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": True,
                "filter_count": 1,
                "created_at": datetime.fromisoformat("2021-08-25T22:09:14.252000+00:00"),
                "aggregating_by_groups": False,
                "payload_count": 0,
            },
            team=ANY,
            request=ANY,
        )

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "name",
                                "before": "original name",
                                "after": "Updated name",
                            },
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {"groups": []},
                                "after": {
                                    "groups": [
                                        {
                                            "properties": [
                                                {
                                                    "key": "email",
                                                    "type": "person",
                                                    "value": "@posthog.com",
                                                    "operator": "icontains",
                                                }
                                            ],
                                            "rollout_percentage": 65,
                                            "aggregation_group_type_index": None,
                                        }
                                    ],
                                    "aggregation_group_type_index": None,
                                },
                            },
                            {
                                "action": "changed",
                                "after": 2,
                                "before": 1,
                                "field": "version",
                                "type": "FeatureFlag",
                            },
                        ],
                        "trigger": None,
                        "type": None,
                        "name": "a-feature-flag-that-is-updated",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "a-feature-flag-that-is-updated",
                        "short_id": None,
                    },
                },
            ],
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_partial(self, mock_report_user_action):
        # Test that we can update a feature flag with only some of the fields
        # And the unchanged fields are not updated
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {
                    "name": "original name",
                    "key": "a-feature-flag-that-is-updated",
                    "filters": {
                        "groups": [
                            {
                                "variant": None,
                                "properties": [
                                    {
                                        "key": "plan",
                                        "type": "person",
                                        "value": ["pro"],
                                        "operator": "exact",
                                    }
                                ],
                                "rollout_percentage": 100,
                            }
                        ],
                        "payloads": {},
                        "multivariate": None,
                    },
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "Updated name",
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["name"], "Updated name")
        self.assertEqual(response.json()["filters"]["groups"][0]["rollout_percentage"], 100)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_with_different_user(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            # Create flag with original user
            original_user = self.user
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Create and login as different user
            different_user = User.objects.create_and_join(self.organization, "different_user@posthog.com", None)
            self.client.force_login(different_user)
            self.assertNotEqual(original_user, different_user)

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {"name": "Updated name"},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Grab the feature flag and assert created_by is original user and updated_by is different user
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.created_by, original_user)
            self.assertEqual(feature_flag.last_modified_by, different_user)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_fails_concurrency_check_when_version_outdated(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            # Create flag with original user: version 0
            original_user = self.user
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]
            original_version = response.json()["version"]
            self.assertEqual(original_version, 1)
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.version, 1)
            self.assertEqual(feature_flag.last_modified_by, original_user)

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Create and login as different user
            different_user = User.objects.create_and_join(self.organization, "different_user@posthog.com", None)
            self.client.force_login(different_user)
            self.assertNotEqual(original_user, different_user)

            # Successfully update the feature flag with the different user. This will increment the version
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {"name": "Updated name", "version": original_version},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            updated_version = response.json()["version"]
            self.assertEqual(updated_version, 2)
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.version, 2)
            self.assertEqual(feature_flag.last_modified_by, different_user)

            self.client.force_login(original_user)

            # Original user tries to update the feature flag with the original version
            # This should fail because the version has been incremented and the user is
            # trying to update the name
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                data={
                    "name": "Another Updated name",
                    "version": original_version,
                    "original_flag": {
                        # Name has since been changed, leading to a conflict
                        "name": "original name",
                        "key": "a-feature-flag-that-is-updated",
                    },
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(response.json().get("type"), "server_error")
            self.assertEqual(
                response.json().get("detail"),
                "The feature flag was updated by different_user@posthog.com since you started editing it. Please refresh and try again.",
            )

            # Grab the feature flag and assert created_by is original user and last_modified_by is different user
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.name, "Updated name")
            self.assertEqual(feature_flag.last_modified_by, different_user)

            # The different user refreshes and tries to update again
            self.client.force_login(different_user)
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                data={"name": "Another Updated name", "version": updated_version},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.name, "Another Updated name")
            self.assertEqual(feature_flag.last_modified_by, different_user)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_does_not_fail_concurrency_check_when_changing_different_fields(
        self, mock_report_user_action
    ):
        # If another users saves changes, but my changes don't conflict with those changes,
        # then we should not fail the concurrency check
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            # Create flag with original user: version 0
            original_user = self.user
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {
                    "name": "original name",
                    "key": "a-feature-flag-that-is-updated",
                    "filters": {
                        "groups": [
                            {
                                "variant": None,
                                "properties": [
                                    {
                                        "key": "plan",
                                        "type": "person",
                                        "value": ["pro"],
                                        "operator": "exact",
                                    }
                                ],
                                "rollout_percentage": 100,
                            }
                        ],
                        "payloads": {},
                        "multivariate": None,
                    },
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]
            original_version = response.json()["version"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Create and login as different user
            different_user = User.objects.create_and_join(self.organization, "different_user@posthog.com", None)
            self.client.force_login(different_user)

            # Successfully update the feature flag with the different user. This will increment the version
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {"name": "Updated name", "version": original_version},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.client.force_login(original_user)

            # Original user tries to update the feature flag with the original version
            # However, the user is changing a field that wasn't changed by the other user
            # This should succeed
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                data={
                    "name": "Updated name",
                    "filters": {
                        "groups": [
                            {
                                "variant": None,
                                "properties": [
                                    {
                                        "key": "plan",
                                        "type": "person",
                                        "value": ["pro"],
                                        "operator": "exact",
                                    }
                                ],
                                "rollout_percentage": 45,
                            }
                        ],
                        "payloads": {},
                        "multivariate": None,
                    },
                    "original_flag": {
                        "name": "original name",  # This is the same as the name (though not the current name)
                        "filters": {
                            "groups": [
                                {
                                    "variant": None,
                                    "properties": [
                                        {
                                            "key": "plan",
                                            "type": "person",
                                            "value": ["pro"],
                                            "operator": "exact",
                                        }
                                    ],
                                    "rollout_percentage": 100,
                                    "aggregation_group_type_index": None,
                                }
                            ],
                            "payloads": {},
                            "multivariate": None,
                            "aggregation_group_type_index": None,
                        },
                    },
                    "version": original_version,
                },
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.name, "Updated name")
            self.assertEqual(feature_flag.last_modified_by, original_user)
            self.assertEqual(response.json()["filters"]["groups"][0]["rollout_percentage"], 45)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_does_not_fail_when_version_not_in_request(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                data={"name": "Updated name"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["version"], 2)

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                data={"name": "Yet another updated name"},
                format="json",
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["version"], 3)
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.version, 3)
            self.assertEqual(feature_flag.name, "Yet another updated name")

    def test_remote_config_with_personal_api_key(self):
        FeatureFlag.objects.create(
            team=self.team,
            key="my-remote-config-flag",
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "payloads": {"true": '{"test": true}'},
            },
            is_remote_configuration=True,
        )
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X", user=self.user, scopes=["*"], secure_value=hash_key_value(personal_api_key)
        )

        self.client.logout()

        client = redis.get_client()
        client.delete(f"posthog:remote_config_requests:{self.team.pk}")

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {personal_api_key}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), '{"test": true}')
        # Personal-key requests are the app's preview feature, not SDK usage, so they aren't counted.
        self.assertEqual(client.hgetall(f"posthog:remote_config_requests:{self.team.pk}"), {})

    def test_remote_config_with_project_secret_api_key(self):
        self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)
        FeatureFlag.objects.create(
            team=self.team,
            key="my-remote-config-flag",
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "payloads": {"true": '{"test": true}'},
            },
            is_remote_configuration=True,
        )
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {self.team.secret_api_token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), '{"test": true}')

    def _create_remote_config_flag(self, key: str = "my-remote-config-flag") -> None:
        FeatureFlag.objects.create(
            team=self.team,
            key=key,
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '{"test": true}'},
            },
            is_remote_configuration=True,
        )

    def test_remote_config_with_psak(self):
        self._create_remote_config_flag()
        token, _ = _make_feature_flag_psak(self.team, label="remote-config")
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), '{"test": true}')

    def test_remote_config_psak_wrong_scope_returns_403(self):
        self._create_remote_config_flag()
        token, _ = _make_feature_flag_psak(self.team, label="wrong-scope", scopes=["endpoint:read"])
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remote_config_psak_cross_team_returns_403(self):
        self._create_remote_config_flag()
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        token, _ = _make_feature_flag_psak(other_team, label="other-team")
        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remote_config_psak_increments_remote_config_bucket(self):
        self._create_remote_config_flag()
        token, _ = _make_feature_flag_psak(self.team, label="telemetry")
        self.client.logout()

        client = redis.get_client()
        client.delete(f"posthog:remote_config_requests:{self.team.pk}")

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        buckets = client.hgetall(f"posthog:remote_config_requests:{self.team.pk}")
        self.assertEqual(sum(int(count) for count in buckets.values()), 1)

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch("products.feature_flags.backend.api.feature_flag.RemoteConfigThrottle.rate", new="2/minute")
    def test_remote_config_throttles_project_secret_api_key_requests(self, *_args):
        # PSAK requests carry no personal API key, so a plain PersonalApiKeyRateThrottle would let
        # them through unthrottled. RemoteConfigThrottle's PSAK-aware base must throttle them per key.
        self._create_remote_config_flag()
        token, _ = _make_feature_flag_psak(self.team, label="throttle")
        self.client.logout()
        cache.clear()

        url = f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config"
        headers = {"authorization": f"Bearer {token}"}
        for _ in range(2):
            self.assertEqual(self.client.get(url, headers=headers).status_code, status.HTTP_200_OK)
        self.assertEqual(self.client.get(url, headers=headers).status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    @patch(
        "products.feature_flags.backend.api.feature_flag.RemoteConfigProjectSecretApiKeyTeamThrottle.rate",
        new="2/minute",
    )
    def test_remote_config_team_throttle_caps_across_multiple_psaks(self, *_args):
        # The per-team throttle exists to stop a project from multiplying its budget by minting keys.
        # The per-key throttle stays at its default, so the only way the third request trips is the
        # shared per-team bucket — two distinct keys, one team.
        self._create_remote_config_flag()
        token_a, _ = _make_feature_flag_psak(self.team, label="teamcapa")
        token_b, _ = _make_feature_flag_psak(self.team, label="teamcapb")
        self.client.logout()
        cache.clear()

        url = f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config"
        for _ in range(2):
            self.assertEqual(
                self.client.get(url, headers={"authorization": f"Bearer {token_a}"}).status_code, status.HTTP_200_OK
            )
        self.assertEqual(
            self.client.get(url, headers={"authorization": f"Bearer {token_b}"}).status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_remote_config_returns_response_even_if_shadow_raises(self):
        # The throwaway Rust shadow (phase 2) must never break the live endpoint, even if it raises.
        self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)
        FeatureFlag.objects.create(
            team=self.team,
            key="my-remote-config-flag",
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '{"test": true}'},
            },
            is_remote_configuration=True,
        )
        self.client.logout()
        with patch(
            "products.feature_flags.backend.api.feature_flag.shadow_compare_remote_config",
            side_effect=RuntimeError("boom"),
        ) as shadow:
            response = self.client.get(
                f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
                headers={"authorization": f"Bearer {self.team.secret_api_token}"},
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), '{"test": true}')
        shadow.assert_called_once()
        self.assertEqual(shadow.call_args.kwargs["key"], "my-remote-config-flag")
        self.assertIn("project_id", shadow.call_args.kwargs)

    # Encrypted remote config payloads are decrypted only for personal API keys; project
    # secret keys get the redacted marker. This is the parity oracle for the Rust port,
    # which must replicate both.
    @parameterized.expand(
        [
            ("project_secret_key", False),
            ("personal_api_key", True),
            ("psak", False),
        ]
    )
    def test_remote_config_encrypted_payload_auth_dependent(self, _name: str, should_decrypt: bool):
        plaintext = '{"secret": "value"}'
        token = flag_payload_codec().encrypt(plaintext.encode("utf-8")).decode("utf-8")
        self._create_encrypted_flag(stored_payload=token)

        if should_decrypt:
            auth_token = generate_random_token_personal()
            PersonalAPIKey.objects.create(
                label="X", user=self.user, scopes=["*"], secure_value=hash_key_value(auth_token)
            )
        elif _name == "psak":
            auth_token, _ = _make_feature_flag_psak(self.team, label="encrypted")
        else:
            self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)
            secret_token = self.team.secret_api_token
            assert secret_token is not None
            auth_token = secret_token

        self.client.logout()
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/my-encrypted-flag/remote_config",
            headers={"authorization": f"Bearer {auth_token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), plaintext if should_decrypt else REDACTED_PAYLOAD_VALUE)

    @parameterized.expand([("plaintext_payloads", False), ("encrypted_payloads", True)])
    def test_remote_config_increments_remote_config_bucket_by_one_per_request(
        self, _name: str, has_encrypted_payloads: bool
    ):
        self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)
        FeatureFlag.objects.create(
            team=self.team,
            key="my-remote-config-flag",
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '{"test": true}'},
            },
            is_remote_configuration=True,
            has_encrypted_payloads=has_encrypted_payloads,
        )
        self.client.logout()

        client = redis.get_client()
        client.delete(f"posthog:remote_config_requests:{self.team.pk}")
        client.delete(f"posthog:decide_requests:{self.team.pk}")

        with freeze_time("2022-05-07 12:23:07"):
            for _ in range(3):
                response = self.client.get(
                    f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config",
                    headers={"authorization": f"Bearer {self.team.secret_api_token}"},
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Remote config usage is telemetry-only: it accumulates in its own bucket and must
        # never reach the decide bucket that billing consumes.
        buckets = client.hgetall(f"posthog:remote_config_requests:{self.team.pk}")
        self.assertEqual(sum(int(count) for count in buckets.values()), 3)
        self.assertEqual(client.hgetall(f"posthog:decide_requests:{self.team.pk}"), {})

    def test_remote_config_does_not_count_when_flag_is_not_remote_config(self):
        self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)
        FeatureFlag.objects.create(
            team=self.team,
            key="not-a-remote-config-flag",
            name="Regular Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            is_remote_configuration=False,
        )
        self.client.logout()

        client = redis.get_client()
        client.delete(f"posthog:remote_config_requests:{self.team.pk}")

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/not-a-remote-config-flag/remote_config",
            headers={"authorization": f"Bearer {self.team.secret_api_token}"},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(client.hgetall(f"posthog:remote_config_requests:{self.team.pk}"), {})

    def test_remote_config_does_not_count_session_authenticated_requests(self):
        # Only team-secret-token fetches are counted. A session-authenticated GET must not increment
        # usage, otherwise a logged-in member could be driven to the URL cross-site to inflate the
        # team's usage telemetry.
        FeatureFlag.objects.create(
            team=self.team,
            key="my-remote-config-flag",
            name="Remote Config Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '{"test": true}'},
            },
            is_remote_configuration=True,
        )

        client = redis.get_client()
        client.delete(f"posthog:remote_config_requests:{self.team.pk}")

        # self.client is still logged in as self.user (session auth), no secret key supplied.
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/my-remote-config-flag/remote_config")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(client.hgetall(f"posthog:remote_config_requests:{self.team.pk}"), {})

    def test_remote_config_with_secret_api_key_prevents_cross_team_access(self):
        # Create two teams with different secret keys
        self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)
        other_team = Team.objects.create(
            organization=self.organization,
            api_token="phc_other_team_token",
            name="Other Team",
        )
        other_team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)

        # Create a flag in the other team
        FeatureFlag.objects.create(
            team=other_team,
            key="other-team-flag",
            name="Other Team Flag",
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
                "payloads": {"true": '{"other_team": true}'},
            },
            is_remote_configuration=True,
        )

        self.client.logout()

        # Try to access other team's flag using this team's secret key + other team's project_api_key in body
        response = self.client.get(
            f"/api/projects/{other_team.id}/feature_flags/other-team-flag/remote_config?token={other_team.api_token}",
            headers={"authorization": f"Bearer {self.team.secret_api_token}"},
        )

        # Should be forbidden due to team mismatch
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remote_config_with_numeric_id_scopes_to_project(self):
        other_team = Team.objects.create(
            organization=self.organization,
            api_token="phc_numeric_id_test",
            name="Numeric ID Team",
        )

        other_flag = FeatureFlag.objects.create(
            team=other_team,
            key="other-flag-numeric",
            name="Other Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '{"leaked": true}'},
            },
            is_remote_configuration=True,
        )

        # Try to access the other team's flag using its numeric ID from our project endpoint
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{other_flag.pk}/remote_config")

        # Should return 404 because the flag doesn't belong to this project
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_remote_config_with_string_key_scopes_to_project(self):
        other_team = Team.objects.create(
            organization=self.organization,
            api_token="phc_string_key_test",
            name="String Key Team",
        )

        FeatureFlag.objects.create(
            team=other_team,
            key="unique-other-flag-key",
            name="Other Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": '{"leaked": true}'},
            },
            is_remote_configuration=True,
        )

        # Try to access the other team's flag using its key from our project endpoint
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/unique-other-flag-key/remote_config")

        # Should return 404 because the flag doesn't belong to this project
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_remote_config_returns_not_found_for_unknown_flag(self):
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/nonexistent_key/remote_config")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def _create_encrypted_flag(self, stored_payload: str = "original-encrypted-value") -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="my-encrypted-flag",
            name="Encrypted Flag",
            active=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": stored_payload},
            },
            is_remote_configuration=True,
            has_encrypted_payloads=True,
        )

    @parameterized.expand(
        [
            (
                "filters_omitted",
                {"name": "Updated Name"},
            ),
            (
                "payloads_omitted",
                {
                    "has_encrypted_payloads": True,
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
                },
            ),
            (
                "true_key_missing",
                {
                    "has_encrypted_payloads": True,
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "payloads": {},
                    },
                },
            ),
            (
                "redacted_placeholder_echoed",
                {
                    "has_encrypted_payloads": True,
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "payloads": {"true": REDACTED_PAYLOAD_VALUE},
                    },
                },
            ),
        ]
    )
    def test_update_encrypted_flag_preserves_payload(self, _name: str, patch_body: dict) -> None:
        flag = self._create_encrypted_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            patch_body,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        self.assertEqual(flag.filters["payloads"]["true"], "original-encrypted-value")
        self.assertTrue(flag.has_encrypted_payloads)

    def test_update_encrypted_flag_encrypts_fresh_plaintext_payload(self):
        flag = self._create_encrypted_flag()

        plaintext = '"new-secret-value"'
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "has_encrypted_payloads": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": plaintext},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        stored = flag.filters["payloads"]["true"]
        self.assertNotEqual(stored, plaintext)
        self.assertNotEqual(stored, "original-encrypted-value")
        # Verify the stored ciphertext actually round-trips back to the plaintext.
        decrypted = get_decrypted_flag_payload(stored, should_decrypt=True)
        self.assertEqual(decrypted, plaintext)

    @parameterized.expand(
        [
            ("number", 42),
            ("boolean", True),
            ("null", None),
            ("array", [1, 2, 3]),
            ("object", {"key": "value"}),
        ]
    )
    def test_update_encrypted_flag_encrypts_non_string_payload(self, _name, raw_value):
        # A non-str JSON payload is normalized to a JSON string before encryption,
        # so it encrypts cleanly instead of raising on `.encode()`.
        flag = self._create_encrypted_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "has_encrypted_payloads": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": raw_value},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        stored = flag.filters["payloads"]["true"]
        self.assertNotEqual(stored, json.dumps(raw_value))
        decrypted = get_decrypted_flag_payload(stored, should_decrypt=True)
        self.assertEqual(json.loads(decrypted), raw_value)

    def test_update_encrypted_flag_downgrade_clears_payload(self):
        flag = self._create_encrypted_flag()

        # Mirrors what the frontend sends after `resetEncryptedPayload`: the
        # form's prepare step (`indexToVariantKeyFeatureFlagPayloads`) strips
        # the falsy `true` key, so the wire body has an empty `payloads` dict.
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "has_encrypted_payloads": False,
                "is_remote_configuration": False,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        self.assertFalse(flag.has_encrypted_payloads)
        self.assertFalse(flag.is_remote_configuration)
        # The prior ciphertext must not survive a downgrade.
        self.assertNotIn("true", flag.filters["payloads"])

    def test_update_encrypted_flag_partial_downgrade_clears_ciphertext(self):
        # Even when the client sends only the boolean flip and no filters,
        # the server must strip the leftover ciphertext so it is not served
        # unredacted on subsequent reads (redaction is gated on
        # has_encrypted_payloads).
        flag = self._create_encrypted_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"has_encrypted_payloads": False, "is_remote_configuration": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        self.assertFalse(flag.has_encrypted_payloads)
        self.assertNotIn("true", (flag.filters or {}).get("payloads", {}))

    def test_update_encrypted_flag_encrypts_when_boolean_omitted(self):
        # A partial PATCH that supplies a fresh `payloads.true` plaintext but
        # omits `has_encrypted_payloads` must still encrypt; the instance is
        # already encrypted, and falling through to the un-encrypted branch
        # would write plaintext on a row marked as encrypted.
        flag = self._create_encrypted_flag()

        plaintext = '"another-secret"'
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": plaintext},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        flag.refresh_from_db()
        stored = flag.filters["payloads"]["true"]
        self.assertNotEqual(stored, plaintext)
        decrypted = get_decrypted_flag_payload(stored, should_decrypt=True)
        self.assertEqual(decrypted, plaintext)

    def test_update_encrypted_flag_rejects_enabling_without_payload(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="my-flag",
            name="Flag",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "has_encrypted_payloads": True,
                "is_remote_configuration": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": REDACTED_PAYLOAD_VALUE},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_get_conflicting_changes(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="my-flag",
            name="Beta feature",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        serializer = FeatureFlagSerializer(instance=feature_flag, context={"team_id": self.team.id})

        original_flag = {
            "key": "my-flag",
            "name": "Alpha feature",  # This has since been changed by another user
            "active": True,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
        }

        # Test 1: No conflicts when changing fields that haven't been changed by another user
        # The name is different from the current value, but the user is not trying to change it
        validated_data = {"active": False, "key": "my-flag-2", "name": "Alpha feature"}
        conflicts = serializer._get_conflicting_changes(feature_flag, validated_data, original_flag)
        self.assertEqual(conflicts, [])

        # Test 2: Detect conflict when changing a field that has been changed by another user
        feature_flag.active = False
        feature_flag.save()
        validated_data = {"name": "Gamma feature"}
        conflicts = serializer._get_conflicting_changes(feature_flag, validated_data, original_flag)
        self.assertEqual(conflicts, ["name"])

    def test_get_conflicting_changes_returns_empty_when_original_flag_is_none(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="my-flag",
            name="Beta feature",
            active=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
        )

        serializer = FeatureFlagSerializer(instance=feature_flag, context={"team_id": self.team.id})

        original_flag = None

        # Should be conflict, but since original_flag is None, it will be ignored
        feature_flag.active = False
        feature_flag.save()
        validated_data = {"name": "Gamma feature"}
        conflicts = serializer._get_conflicting_changes(feature_flag, validated_data, original_flag)
        self.assertEqual(conflicts, [])

    def test_get_conflicting_changes_with_filter_changes(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            key="my-flag",
            name="Beta feature",
            active=True,
            filters={
                # This has since been changed by another user
                "groups": [{"properties": [], "rollout_percentage": 45}]
            },
        )

        serializer = FeatureFlagSerializer(instance=feature_flag, context={"team_id": self.team.id})

        original_flag = {
            "key": "my-flag",
            # This has since been changed by another user
            "name": "Alpha feature",
            "active": True,
            "filters": {
                # This has since been changed by another user
                "groups": [{"properties": [], "rollout_percentage": 50}]
            },
        }

        # Test 1: No conflicts when changing fields that haven't been changed by another user
        # The name and fliters are different from the current value, but the user is not trying to change them
        validated_data = {
            "active": False,
            "key": "my-flag-2",
            "name": "Alpha feature",
            "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
        }
        conflicts = serializer._get_conflicting_changes(feature_flag, validated_data, original_flag)
        self.assertEqual(conflicts, [])

        # Test 2: Detect conflict when changing a field that has been changed by another user
        feature_flag.active = False
        feature_flag.save()
        validated_data = {
            "name": "Gamma feature",
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
            "active": False,
            "key": "my-flag-2",
        }
        conflicts = serializer._get_conflicting_changes(feature_flag, validated_data, original_flag)
        self.assertEqual(conflicts, ["name", "filters"])

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_treats_null_version_as_zero(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            feature_flag.version = None
            feature_flag.save()
            frozen_datetime.tick(delta=timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                data={"name": "Updated name", "version": 0},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["version"], 1)
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            self.assertEqual(feature_flag.version, 1)
            self.assertEqual(feature_flag.name, "Updated name")

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_key(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Assert that the insights were created properly.
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
            insights = feature_flag.usage_dashboard.insights
            total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
            self.assertEqual(
                total_volume_insight.description,
                "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(total_volume_insight),
                "a-feature-flag-that-is-updated",
            )
            unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
            self.assertEqual(
                unique_users_insight.description,
                "Shows the number of unique user calls made on feature flag per variant with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(unique_users_insight),
                "a-feature-flag-that-is-updated",
            )

            # Update the feature flag key
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "key": "a-new-feature-flag-key",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                    }
                                ],
                            }
                        ]
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(response.json()["key"], "a-new-feature-flag-key")
        self.assertEqual(response.json()["filters"]["groups"][0]["rollout_percentage"], 65)

        # Assert analytics are sent
        mock_report_user_action.assert_called_with(
            self.user,
            "feature flag updated",
            {
                "groups_count": 1,
                "has_variants": False,
                "variants_count": 0,
                "has_rollout_percentage": True,
                "has_filters": True,
                "filter_count": 1,
                "created_at": datetime.fromisoformat("2021-08-25T22:09:14.252000+00:00"),
                "aggregating_by_groups": False,
                "payload_count": 0,
            },
            team=ANY,
            request=ANY,
        )

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "key",
                                "before": "a-feature-flag-that-is-updated",
                                "after": "a-new-feature-flag-key",
                            },
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {"groups": []},
                                "after": {
                                    "groups": [
                                        {
                                            "properties": [
                                                {
                                                    "key": "email",
                                                    "type": "person",
                                                    "value": "@posthog.com",
                                                    "operator": "icontains",
                                                }
                                            ],
                                            "rollout_percentage": 65,
                                            "aggregation_group_type_index": None,
                                        }
                                    ],
                                    "aggregation_group_type_index": None,
                                },
                            },
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "version",
                                "before": 1,
                                "after": 2,
                            },
                        ],
                        "trigger": None,
                        "type": None,
                        "name": "a-new-feature-flag-key",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": self.user.first_name,
                        "email": self.user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "a-feature-flag-that-is-updated",
                        "short_id": None,
                    },
                },
            ],
        )

        feature_flag = FeatureFlag.objects.get(id=flag_id)
        assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
        insights = feature_flag.usage_dashboard.insights
        total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
        self.assertEqual(
            total_volume_insight.description,
            "Shows the number of total calls made on feature flag with key: a-new-feature-flag-key",
        )
        self.assertEqual(
            self._insight_query_value(total_volume_insight),
            "a-new-feature-flag-key",
        )
        unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
        self.assertEqual(
            unique_users_insight.description,
            "Shows the number of unique user calls made on feature flag per variant with key: a-new-feature-flag-key",
        )
        self.assertEqual(
            self._insight_query_value(unique_users_insight),
            "a-new-feature-flag-key",
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_key_does_not_update_insight_with_changed_description(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Assert that the insights were created properly.
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
            insights = feature_flag.usage_dashboard.insights
            total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
            self.assertEqual(
                total_volume_insight.description,
                "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(total_volume_insight),
                "a-feature-flag-that-is-updated",
            )
            unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
            self.assertEqual(
                unique_users_insight.description,
                "Shows the number of unique user calls made on feature flag per variant with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(unique_users_insight),
                "a-feature-flag-that-is-updated",
            )
            total_volume_insight.name = "This is a changed description"
            total_volume_insight.save()

            # Update the feature flag key
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "key": "a-new-feature-flag-key",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                    }
                                ],
                            }
                        ]
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Total volume insight should not be updated because we changed its description
        # unique users insight should still be updated
        feature_flag = FeatureFlag.objects.get(id=flag_id)
        assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
        insights = feature_flag.usage_dashboard.insights
        self.assertIsNone(insights.filter(name="Feature Flag Called Total Volume").first())
        total_volume_insight = insights.get(name="This is a changed description")
        self.assertEqual(
            total_volume_insight.description,
            "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
        )
        self.assertEqual(
            self._insight_query_value(total_volume_insight),
            "a-feature-flag-that-is-updated",
        )
        unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
        self.assertEqual(
            unique_users_insight.description,
            "Shows the number of unique user calls made on feature flag per variant with key: a-new-feature-flag-key",
        )
        self.assertEqual(
            self._insight_query_value(unique_users_insight),
            "a-new-feature-flag-key",
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_key_does_not_update_insight_with_changed_filter(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Assert that the insights were created properly.
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
            insights = feature_flag.usage_dashboard.insights
            total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
            self.assertEqual(
                total_volume_insight.description,
                "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(total_volume_insight),
                "a-feature-flag-that-is-updated",
            )
            unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
            self.assertEqual(
                unique_users_insight.description,
                "Shows the number of unique user calls made on feature flag per variant with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(unique_users_insight),
                "a-feature-flag-that-is-updated",
            )
            total_volume_query = cast(dict[str, Any], total_volume_insight.query)
            total_volume_query["source"]["properties"]["values"][0]["values"][0]["value"] = "something_unexpected"
            total_volume_insight.save()

            # Update the feature flag key
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "key": "a-new-feature-flag-key",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                    }
                                ],
                            }
                        ]
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Total volume insight should not be updated because we changed its description
        # unique users insight should still be updated
        feature_flag = FeatureFlag.objects.get(id=flag_id)
        assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
        insights = feature_flag.usage_dashboard.insights
        total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
        self.assertEqual(
            total_volume_insight.description,
            "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
        )
        self.assertEqual(
            self._insight_query_value(total_volume_insight),
            "something_unexpected",
        )
        unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
        self.assertEqual(
            unique_users_insight.description,
            "Shows the number of unique user calls made on feature flag per variant with key: a-new-feature-flag-key",
        )
        self.assertEqual(
            self._insight_query_value(unique_users_insight),
            "a-new-feature-flag-key",
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_updating_feature_flag_key_does_not_update_insight_with_removed_filter(self, mock_report_user_action):
        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "original name", "key": "a-feature-flag-that-is-updated"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            flag_id = response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            # Assert that the insights were created properly.
            feature_flag = FeatureFlag.objects.get(id=flag_id)
            assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
            insights = feature_flag.usage_dashboard.insights
            total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
            self.assertEqual(
                total_volume_insight.description,
                "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(total_volume_insight),
                "a-feature-flag-that-is-updated",
            )
            unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
            self.assertEqual(
                unique_users_insight.description,
                "Shows the number of unique user calls made on feature flag per variant with key: a-feature-flag-that-is-updated",
            )
            self.assertEqual(
                self._insight_query_value(unique_users_insight),
                "a-feature-flag-that-is-updated",
            )
            # clear the values from total_volume_insight.query["source"]["properties"]["values"]
            total_volume_query = cast(dict[str, Any], total_volume_insight.query)
            total_volume_query["source"]["properties"]["values"] = []
            total_volume_insight.save()

            # Update the feature flag key
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "key": "a-new-feature-flag-key",
                    "filters": {
                        "groups": [
                            {
                                "rollout_percentage": 65,
                                "properties": [
                                    {
                                        "key": "email",
                                        "type": "person",
                                        "value": "@posthog.com",
                                        "operator": "icontains",
                                    }
                                ],
                            }
                        ]
                    },
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Total volume insight should not be updated because we changed its description
        # unique users insight should still be updated
        feature_flag = FeatureFlag.objects.get(id=flag_id)
        assert feature_flag.usage_dashboard is not None, "Usage dashboard was not created"
        insights = feature_flag.usage_dashboard.insights
        total_volume_insight = insights.get(name="Feature Flag Called Total Volume")
        self.assertEqual(
            total_volume_insight.description,
            "Shows the number of total calls made on feature flag with key: a-feature-flag-that-is-updated",
        )
        self.assertEqual(
            cast(dict[str, Any], total_volume_insight.query)["source"]["properties"]["values"],
            [],
        )
        unique_users_insight = insights.get(name="Feature Flag calls made by unique users per variant")
        self.assertEqual(
            unique_users_insight.description,
            "Shows the number of unique user calls made on feature flag per variant with key: a-new-feature-flag-key",
        )
        self.assertEqual(
            self._insight_query_value(unique_users_insight),
            "a-new-feature-flag-key",
        )

    def test_hard_deleting_feature_flag_is_forbidden(self):
        new_user = User.objects.create_and_join(self.organization, "new_annotations@posthog.com", None)

        instance = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="potato")
        self.client.force_login(new_user)

        response = self.client.delete(f"/api/projects/{self.team.id}/feature_flags/{instance.pk}/")

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertTrue(FeatureFlag.objects.filter(pk=instance.pk).exists())

    def test_get_feature_flag_activity(self):
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="person_acting_and_then_viewing_activity@posthog.com",
            password=None,
            first_name="Potato",
        )
        self.client.force_login(new_user)

        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "feature flag with activity", "key": "feature_with_activity"},
            )

            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
            flag_id = create_response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "feature flag with activity",
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                },
                format="json",
            )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        self.assert_feature_flag_activity(
            flag_id,
            [
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {"groups": []},
                                "after": {
                                    "groups": [
                                        {
                                            "properties": [],
                                            "rollout_percentage": 74,
                                            "aggregation_group_type_index": None,
                                        }
                                    ],
                                    "aggregation_group_type_index": None,
                                },
                            },
                            {
                                "action": "changed",
                                "after": 2,
                                "before": 1,
                                "field": "version",
                                "type": "FeatureFlag",
                            },
                        ],
                        "trigger": None,
                        "type": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
            ],
        )

    def test_get_feature_flag_activity_for_all_flags(self):
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="person_acting_and_then_viewing_activity@posthog.com",
            password=None,
            first_name="Potato",
        )
        self.client.force_login(new_user)

        with freeze_time("2021-08-25T22:09:14.252Z") as frozen_datetime:
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "feature flag with activity", "key": "feature_with_activity"},
            )

            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
            flag_id = create_response.json()["id"]

            frozen_datetime.tick(delta=timedelta(minutes=10))

            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {
                    "name": "feature flag with activity",
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
                },
                format="json",
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

            frozen_datetime.tick(delta=timedelta(minutes=10))

            second_create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "a second feature flag", "key": "flag-two"},
            )

            self.assertEqual(second_create_response.status_code, status.HTTP_201_CREATED)
            second_flag_id = second_create_response.json()["id"]

        self.assert_feature_flag_activity(
            flag_id=None,
            expected=[
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:29:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(second_flag_id),
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "flag-two",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "updated",
                    "created_at": "2021-08-25T22:19:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [
                            {
                                "type": "FeatureFlag",
                                "action": "changed",
                                "field": "filters",
                                "before": {"groups": []},
                                "after": {
                                    "groups": [
                                        {
                                            "properties": [],
                                            "rollout_percentage": 74,
                                            "aggregation_group_type_index": None,
                                        }
                                    ],
                                    "aggregation_group_type_index": None,
                                },
                            },
                            {
                                "action": "changed",
                                "after": 2,
                                "before": 1,
                                "field": "version",
                                "type": "FeatureFlag",
                            },
                        ],
                        "trigger": None,
                        "type": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
                {
                    "user": {
                        "first_name": new_user.first_name,
                        "email": new_user.email,
                    },
                    "activity": "created",
                    "created_at": "2021-08-25T22:09:14.252000Z",
                    "scope": "FeatureFlag",
                    "item_id": str(flag_id),
                    "detail": {
                        "changes": [],
                        "trigger": None,
                        "type": None,
                        "name": "feature_with_activity",
                        "short_id": None,
                    },
                },
            ],
        )

    def test_length_of_feature_flag_activity_does_not_change_number_of_db_queries(self):
        new_user = User.objects.create_and_join(
            organization=self.organization,
            email="person_acting_and_then_viewing_activity@posthog.com",
            password=None,
            first_name="Potato",
        )
        self.client.force_login(new_user)

        # create the flag
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"name": "feature flag with activity", "key": "feature_with_activity"},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        flag_id = create_response.json()["id"]

        # get the activity and capture number of queries made
        with capture_db_queries() as first_read_context:
            self._get_feature_flag_activity(flag_id)

        if isinstance(first_read_context.final_queries, int) and isinstance(first_read_context.initial_queries, int):
            first_activity_read_query_count = first_read_context.final_queries - first_read_context.initial_queries
        else:
            raise AssertionError("must be able to read query numbers from first activity log query")

        # update the flag
        update_response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            {
                "name": "feature flag with activity",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 74}]},
            },
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # get the activity and capture number of queries made
        with capture_db_queries() as second_read_context:
            self._get_feature_flag_activity(flag_id)

        if isinstance(second_read_context.final_queries, int) and isinstance(second_read_context.initial_queries, int):
            second_activity_read_query_count = second_read_context.final_queries - second_read_context.initial_queries
        else:
            raise AssertionError("must be able to read query numbers from second activity log query")

        self.assertEqual(first_activity_read_query_count, second_activity_read_query_count)

    def test_get_feature_flag_activity_only_from_own_team(self):
        # two users in two teams
        _, org_one_team, org_one_user = User.objects.bootstrap(
            organization_name="Org 1", email="org1@posthog.com", password=None
        )

        _, org_two_team, org_two_user = User.objects.bootstrap(
            organization_name="Org 2", email="org2@posthog.com", password=None
        )

        # two flags in team 1
        self.client.force_login(org_one_user)
        team_one_flag_one = self._create_flag_with_properties(
            name="team-1-flag-1", team_id=org_one_team.id, properties=[]
        ).json()["id"]
        team_one_flag_two = self._create_flag_with_properties(
            name="team-1-flag-2", team_id=org_one_team.id, properties=[]
        ).json()["id"]

        # two flags in team 2
        self.client.force_login(org_two_user)
        team_two_flag_one = self._create_flag_with_properties(
            name="team-2-flag-1", team_id=org_two_team.id, properties=[]
        ).json()["id"]
        team_two_flag_two = self._create_flag_with_properties(
            name="team-2-flag-2", team_id=org_two_team.id, properties=[]
        ).json()["id"]

        # user in org 1 gets activity
        self.client.force_login(org_one_user)
        self._get_feature_flag_activity(
            flag_id=team_one_flag_one,
            team_id=org_one_team.id,
            expected_status=status.HTTP_200_OK,
        )
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two,
            team_id=org_one_team.id,
            expected_status=status.HTTP_200_OK,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_one,
            team_id=org_one_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_two,
            team_id=org_one_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )

        # user in org 2 gets activity
        self.client.force_login(org_two_user)
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two,
            team_id=org_two_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self._get_feature_flag_activity(
            flag_id=team_one_flag_two,
            team_id=org_two_team.id,
            expected_status=status.HTTP_404_NOT_FOUND,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_one,
            team_id=org_two_team.id,
            expected_status=status.HTTP_200_OK,
        )
        self._get_feature_flag_activity(
            flag_id=team_two_flag_two,
            team_id=org_two_team.id,
            expected_status=status.HTTP_200_OK,
        )

    def test_paging_all_feature_flag_activity(self):
        for x in range(15):
            create_response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": f"feature flag {x}", "key": f"{x}"},
            )
            self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        # check the first page of data
        url = f"/api/projects/{self.team.id}/feature_flags/activity"
        first_page_response = self.client.get(url)
        self.assertEqual(first_page_response.status_code, status.HTTP_200_OK)
        first_page_json = first_page_response.json()

        self.assertEqual(
            [log_item["detail"]["name"] for log_item in first_page_json["results"]],
            ["14", "13", "12", "11", "10", "9", "8", "7", "6", "5"],
        )
        self.assertEqual(
            first_page_json["next"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/activity?page=2&limit=10",
        )
        self.assertEqual(first_page_json["previous"], None)

        # check the second page of data
        second_page_response = self.client.get(first_page_json["next"])
        self.assertEqual(second_page_response.status_code, status.HTTP_200_OK)
        second_page_json = second_page_response.json()

        self.assertEqual(
            [log_item["detail"]["name"] for log_item in second_page_json["results"]],
            ["4", "3", "2", "1", "0"],
        )
        self.assertEqual(second_page_json["next"], None)
        self.assertEqual(
            second_page_json["previous"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/activity?page=1&limit=10",
        )

    def test_paging_specific_feature_flag_activity(self):
        create_response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", {"name": "ff", "key": "0"})
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        flag_id = create_response.json()["id"]

        for x in range(1, 15):
            update_response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
                {"key": str(x)},
                format="json",
            )
            self.assertEqual(update_response.status_code, status.HTTP_200_OK)

        # check the first page of data
        url = f"/api/projects/{self.team.id}/feature_flags/{flag_id}/activity"
        first_page_response = self.client.get(url)
        self.assertEqual(first_page_response.status_code, status.HTTP_200_OK)
        first_page_json = first_page_response.json()

        self.assertEqual(
            # feature flag activity writes the flag key to the detail name
            [log_item["detail"]["name"] for log_item in first_page_json["results"]],
            ["14", "13", "12", "11", "10", "9", "8", "7", "6", "5"],
        )
        self.assertEqual(
            first_page_json["next"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/{flag_id}/activity?page=2&limit=10",
        )
        self.assertEqual(first_page_json["previous"], None)

        # check the second page of data
        second_page_response = self.client.get(first_page_json["next"])
        self.assertEqual(second_page_response.status_code, status.HTTP_200_OK)
        second_page_json = second_page_response.json()

        self.assertEqual(
            # feature flag activity writes the flag key to the detail name
            [log_item["detail"]["name"] for log_item in second_page_json["results"]],
            ["4", "3", "2", "1", "0"],
        )
        self.assertEqual(second_page_json["next"], None)
        self.assertEqual(
            second_page_json["previous"],
            f"http://testserver/api/projects/{self.team.id}/feature_flags/{flag_id}/activity?page=1&limit=10",
        )

    def test_get_flags_with_specified_token(self):
        _, _, user = User.objects.bootstrap("Test", "team2@posthog.com", None)
        self.client.force_login(user)
        assert user.team is not None
        assert self.team is not None
        self.assertNotEqual(user.team.id, self.team.id)

        response_team_1 = self.client.get(f"/api/projects/@current/feature_flags")
        response_team_1_token = self.client.get(f"/api/projects/@current/feature_flags?token={user.team.api_token}")
        response_team_2 = self.client.get(f"/api/projects/@current/feature_flags?token={self.team.api_token}")

        self.assertEqual(response_team_1.json(), response_team_1_token.json())
        self.assertNotEqual(response_team_1.json(), response_team_2.json())

        response_invalid_token = self.client.get(f"/api/projects/@current/feature_flags?token=invalid")
        self.assertEqual(response_invalid_token.status_code, 401)

    def test_soft_delete_flag_renames_key_and_allows_reuse(self):
        # Create flag and experiment, then soft-delete experiment
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="flag1")
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag)
        exp.deleted = True
        exp.save()
        # Soft-delete flag: should rename key
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.deleted is True
        assert flag.key == f"flag1:deleted:{flag.id}"
        # Should now be able to create a new flag with the original key
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"name": "Flag1", "key": "flag1"},
        )
        assert response.status_code == 201
        assert response.json()["key"] == "flag1"

    def test_soft_delete_can_be_reversed_by_patch(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="undo-flag")
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.deleted is True

        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": False})
        assert response.status_code == 200
        flag = FeatureFlag.objects_including_soft_deleted.get(pk=flag.pk)
        assert flag.deleted is False
        assert flag.key == "undo-flag"

    def test_soft_delete_undo_restores_renamed_key(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="renamed-flag")
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag)
        exp.deleted = True
        exp.save()

        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.key == f"renamed-flag:deleted:{flag.id}"

        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": False})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.deleted is False
        assert flag.key == "renamed-flag"

    def test_soft_delete_undo_suffixes_key_when_original_is_taken(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="taken-flag")
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag)
        exp.deleted = True
        exp.save()

        # Soft-delete renames the key to free it up
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.key == f"taken-flag:deleted:{flag.id}"

        # Another flag claims the original key
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="taken-flag")

        # Restoring falls back to a suffixed key instead of crashing
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": False})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.deleted is False
        assert flag.key == "taken-flag-2"

    def test_soft_delete_undo_suffixes_key_when_original_held_by_soft_deleted_flag(self):
        """The unique constraint covers all rows including soft-deleted ones,
        so restoring a flag must check against soft-deleted flags too."""
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="held-flag")
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag)
        exp.deleted = True
        exp.save()

        # Soft-delete renames the key
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.key == f"held-flag:deleted:{flag.id}"

        # Another flag claims the original key and is then soft-deleted itself
        blocker = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="held-flag")
        blocker.deleted = True
        blocker.save()

        # Restoring must still suffix because the DB constraint spans all rows
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": False})
        assert response.status_code == 200
        flag.refresh_from_db()
        assert flag.deleted is False
        assert flag.key == "held-flag-2"

    def test_rename_flag_to_key_held_by_soft_deleted_flag(self):
        # Create a flag, soft-delete it, then create another flag and rename it
        # to the key held by the soft-deleted flag.
        first = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="56397-delete-flag")
        other = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="56397-delete-flag-v2")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{first.id}/",
            {"deleted": True},
        )
        assert response.status_code == 200

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{other.id}/",
            {"key": "56397-delete-flag"},
        )
        assert response.status_code == 200, response.content
        other.refresh_from_db()
        assert other.key == "56397-delete-flag"
        # The soft-deleted flag should have been hard-deleted to free up the key.
        assert not FeatureFlag.objects_including_soft_deleted.filter(
            team=self.team, key="56397-delete-flag", deleted=True
        ).exists()

    def test_soft_delete_flag_blocked_with_running_experiment(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="flag2")
        exp = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            name="My experiment",
            start_date=now(),
        )
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == f'Cannot delete a feature flag that is linked to running experiment(s): "My experiment" (ID: {exp.id}). Please stop the experiment(s) before deleting the flag.'
        )

    @parameterized.expand(
        [
            ("draft", None, None),
            ("stopped", now(), now()),
        ]
    )
    def test_soft_delete_flag_allowed_with_non_running_experiment(self, _name, start_date, end_date):
        # Draft and stopped experiments may keep the flag so their history is preserved;
        # deletion is allowed and the original key is freed up via the tombstone suffix.
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key=f"{_name}-exp-flag")
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            feature_flag=flag,
            start_date=start_date,
            end_date=end_date,
        )
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 200, response.content
        flag.refresh_from_db()
        assert flag.deleted is True
        assert flag.key == f"{_name}-exp-flag:deleted:{flag.id}"

    def test_soft_delete_flag_blocked_when_used_in_replay_settings(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-flag")
        # Set the flag as the session recording linked flag
        self.team.session_recording_linked_flag = {"id": flag.id, "key": flag.key}
        self.team.save()

        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"deleted": True})
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == "This feature flag is used in session replay settings. Please remove it from replay settings before deleting."
        )

    def test_is_used_in_replay_settings_serializer_field(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="replay-flag")

        # Initially should be False
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        assert response.status_code == 200
        assert response.json()["is_used_in_replay_settings"] is False

        # Set the flag as the session recording linked flag
        self.team.session_recording_linked_flag = {"id": flag.id, "key": flag.key}
        self.team.save()

        # Now should be True
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        assert response.status_code == 200
        assert response.json()["is_used_in_replay_settings"] is True

    def test_archive_flag_requires_disabled(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="enabled-flag", active=True)
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"archived": True})
        assert response.status_code == 400
        assert "Cannot archive an enabled feature flag" in response.json()["detail"]
        flag.refresh_from_db()
        assert flag.archived is False

    def test_archive_disabled_flag(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="disabled-flag", active=False)
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"archived": True})
        assert response.status_code == 200, response.content
        assert response.json()["archived"] is True
        assert response.json()["status"] == "ARCHIVED"
        flag.refresh_from_db()
        assert flag.archived is True

    def test_archive_and_disable_flag_in_one_request(self):
        flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="enabled-flag", active=True)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"archived": True, "active": False}
        )
        assert response.status_code == 200, response.content
        flag.refresh_from_db()
        assert flag.archived is True
        assert flag.active is False

    def test_cannot_enable_archived_flag(self):
        flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="archived-flag", active=False, archived=True
        )
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"active": True})
        assert response.status_code == 400
        assert response.json()["detail"] == "Cannot enable an archived feature flag. Unarchive it first."

    def test_unarchive_flag_stays_disabled(self):
        flag = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="archived-flag", active=False, archived=True
        )
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", {"archived": False})
        assert response.status_code == 200, response.content
        flag.refresh_from_db()
        assert flag.archived is False
        assert flag.active is False

    @parameterized.expand(
        [
            ("default", "", True, False),
            ("archived_true", "?archived=true", False, True),
            ("archived_false", "?archived=false", True, False),
        ]
    )
    def test_list_archived_filtering(self, _name, query, expect_visible, expect_archived):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="visible-flag")
        FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="archived-flag", active=False, archived=True
        )
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{query}")
        assert response.status_code == 200
        keys = {flag["key"] for flag in response.json()["results"]}
        assert ("visible-flag" in keys) is expect_visible
        assert ("archived-flag" in keys) is expect_archived

    def test_list_excluded_tags_filtering(self):
        for key, tags in [
            ("deprecated-flag", ["deprecated"]),
            ("multi-tag-flag", ["deprecated", "app"]),
            ("app-flag", ["app"]),
            ("untagged-flag", []),
        ]:
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {
                    "key": key,
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                    "tags": tags,
                },
                format="json",
            )
            assert response.status_code == 201, response.content

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/?excluded_tags={json.dumps(['deprecated'])}"
        )
        assert response.status_code == 200
        keys = {flag["key"] for flag in response.json()["results"]}
        assert "deprecated-flag" not in keys
        assert "multi-tag-flag" not in keys
        assert {"app-flag", "untagged-flag"} <= keys

    def test_getting_flags_is_not_nplus1(self) -> None:
        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        with self.assertNumQueries(FuzzyInt(19, 20)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        for i in range(1, 5):
            self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                data={
                    "name": f"flag",
                    "key": f"flag_{i}",
                    "filters": {"groups": [{"rollout_percentage": 5}]},
                },
                format="json",
            ).json()

        # Query count should stay constant regardless of flag count (no N+1)
        with self.assertNumQueries(FuzzyInt(19, 20)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_getting_flags_with_no_creator(self) -> None:
        FeatureFlag.objects.all().delete()

        self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": f"flag",
                "key": f"flag_0",
                "filters": {"groups": [{"rollout_percentage": 5}]},
            },
            format="json",
        ).json()

        FeatureFlag.objects.create(
            created_by=None,
            team=self.team,
            key="flag_role_access",
            name="Flag role access",
        )

        with self.assertNumQueries(FuzzyInt(19, 20)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 2)
            sorted_results = sorted(response.json()["results"], key=lambda x: x["key"])
            self.assertEqual(sorted_results[1]["created_by"], None)
            self.assertEqual(sorted_results[1]["key"], "flag_role_access")

    def test_getting_flags_with_surveys_is_not_nplus1(self) -> None:
        """
        Test that loading feature flags with linked surveys doesn't cause N+1 queries.

        Reproduces the conditions from Zendesk #40875 where a customer
        had 59 feature flags, all with linked surveys, causing 10+ second page loads.

        The issue was that SurveyAPISerializer accesses related objects
        (linked_flag.key, targeting_flag.key, internal_targeting_flag.key,
        and survey.actions.all()) which caused N+1 query problems without
        proper prefetching.
        """
        # Create 5 flags with linked surveys
        for i in range(5):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                name=f"Flag {i}",
                filters={"groups": [{"rollout_percentage": 100}]},
            )
            Survey.objects.create(
                team=self.team,
                created_by=self.user,
                name=f"Survey {i}",
                type="popover",
                linked_flag=flag,
                questions=[{"type": "open", "question": f"What do you think about flag {i}?"}],
            )

        # Capture query count with 5 flags
        with self.assertNumQueries(FuzzyInt(17, 22)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 5)

        # Add 25 more flags with surveys (total 30)
        for i in range(5, 30):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                name=f"Flag {i}",
                filters={"groups": [{"rollout_percentage": 100}]},
            )
            Survey.objects.create(
                team=self.team,
                created_by=self.user,
                name=f"Survey {i}",
                type="popover",
                linked_flag=flag,
                questions=[{"type": "open", "question": f"What do you think about flag {i}?"}],
            )

        # Query count should remain similar (not scale linearly with flag count)
        with self.assertNumQueries(FuzzyInt(17, 24)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(len(response.json()["results"]), 30)

    def test_getting_flags_with_surveys_and_targeting(self) -> None:
        """
        Test edge case: surveys with targeting flags and internal targeting flags.

        This tests the case where surveys have additional flag relationships
        that also need to be prefetched.
        """
        # Create a main flag
        main_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="main_flag",
            name="Main Flag",
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        # Create targeting flags
        targeting_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="targeting_flag",
            name="Targeting Flag",
            filters={"groups": [{"rollout_percentage": 50}]},
        )

        internal_targeting_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="internal_targeting_flag",
            name="Internal Targeting Flag",
            filters={"groups": [{"rollout_percentage": 25}]},
        )

        # Create survey with all flag relationships
        Survey.objects.create(
            team=self.team,
            created_by=self.user,
            name="Complex Survey",
            type="popover",
            linked_flag=main_flag,
            targeting_flag=targeting_flag,
            internal_targeting_flag=internal_targeting_flag,
            questions=[{"type": "open", "question": "Complex survey question?"}],
        )

        # Should not cause extra queries for the targeting flags
        with self.assertNumQueries(FuzzyInt(15, 22)):
            response = self.client.get(f"/api/projects/{self.team.id}/feature_flags")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # Should include main_flag but not targeting flags (they're filtered out)
            results = response.json()["results"]
            result_keys = [r["key"] for r in results]
            self.assertIn("main_flag", result_keys)
            # targeting_flag and internal_targeting_flag should be excluded
            # (they're survey-specific and filtered out from the main list)

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_feature_flag_usage_dashboard(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        dashboard = instance.usage_dashboard
        assert dashboard is not None
        assert dashboard.tiles is not None
        tiles = sorted(
            dashboard.tiles.all(),
            key=lambda x: str(x.insight.name if x.insight is not None else ""),
        )

        self.assertEqual(dashboard.name, "Generated Dashboard: alpha-feature Usage")
        self.assertEqual(
            dashboard.description,
            "This dashboard was generated by the feature flag with key (alpha-feature)",
        )
        assert dashboard is not None, "Usage dashboard was not created"
        self.assertEqual(dashboard.creation_mode, Dashboard.CreationMode.TEMPLATE)
        self.assertEqual(dashboard.filters, {"date_from": "-30d"})
        self.assertEqual(len(tiles), 2)
        assert tiles[0].insight is not None
        self.assertEqual(tiles[0].insight.name, "Feature Flag Called Total Volume")
        self.assertEqual(
            tiles[0].insight.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": "$feature_flag_called",
                            "event": "$feature_flag_called",
                        }
                    ],
                    "interval": "day",
                    "dateRange": {"date_from": "-30d", "explicitDate": False},
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$feature_flag",
                                        "type": "event",
                                        "value": "alpha-feature",
                                        "operator": "exact",
                                    }
                                ],
                            }
                        ],
                    },
                    "trendsFilter": {
                        "display": "ActionsLineGraph",
                        "showLegend": False,
                        "yAxisScaleType": "linear",
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "showPercentStackView": False,
                        "aggregationAxisFormat": "numeric",
                        "showAlertThresholdLines": False,
                    },
                    "breakdownFilter": {
                        "breakdown": "$feature_flag_response",
                        "breakdown_type": "event",
                    },
                    "filterTestAccounts": False,
                },
            },
        )
        assert tiles[1].insight is not None
        self.assertEqual(tiles[1].insight.name, "Feature Flag calls made by unique users per variant")
        self.assertEqual(
            tiles[1].insight.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "math": "dau",
                            "name": "$feature_flag_called",
                            "event": "$feature_flag_called",
                        }
                    ],
                    "interval": "day",
                    "dateRange": {"date_from": "-30d", "explicitDate": False},
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$feature_flag",
                                        "type": "event",
                                        "value": "alpha-feature",
                                        "operator": "exact",
                                    }
                                ],
                            }
                        ],
                    },
                    "trendsFilter": {
                        "display": "ActionsTable",
                        "showLegend": False,
                        "yAxisScaleType": "linear",
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "showPercentStackView": False,
                        "aggregationAxisFormat": "numeric",
                        "showAlertThresholdLines": False,
                    },
                    "breakdownFilter": {
                        "breakdown": "$feature_flag_response",
                        "breakdown_type": "event",
                    },
                    "filterTestAccounts": False,
                },
            },
        )

        # now enable enriched analytics
        instance.has_enriched_analytics = True
        instance.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        instance.refresh_from_db()

        dashboard = instance.usage_dashboard
        assert dashboard is not None
        assert dashboard.tiles is not None
        tiles = sorted(
            dashboard.tiles.all(),
            key=lambda x: str(x.insight.name if x.insight is not None else ""),
        )

        self.assertEqual(dashboard.name, "Generated Dashboard: alpha-feature Usage")
        self.assertEqual(
            dashboard.description,
            "This dashboard was generated by the feature flag with key (alpha-feature)",
        )
        self.assertEqual(dashboard.filters, {"date_from": "-30d"})
        self.assertEqual(len(tiles), 4)
        assert tiles[0].insight is not None
        self.assertEqual(tiles[0].insight.name, "Feature Flag Called Total Volume")
        self.assertEqual(
            tiles[0].insight.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": "$feature_flag_called",
                            "event": "$feature_flag_called",
                        }
                    ],
                    "interval": "day",
                    "dateRange": {"date_from": "-30d", "explicitDate": False},
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$feature_flag",
                                        "type": "event",
                                        "value": "alpha-feature",
                                        "operator": "exact",
                                    }
                                ],
                            }
                        ],
                    },
                    "trendsFilter": {
                        "display": "ActionsLineGraph",
                        "showLegend": False,
                        "yAxisScaleType": "linear",
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "showPercentStackView": False,
                        "aggregationAxisFormat": "numeric",
                        "showAlertThresholdLines": False,
                    },
                    "breakdownFilter": {
                        "breakdown": "$feature_flag_response",
                        "breakdown_type": "event",
                    },
                    "filterTestAccounts": False,
                },
            },
        )
        assert tiles[1].insight is not None
        self.assertEqual(tiles[1].insight.name, "Feature Flag calls made by unique users per variant")
        self.assertEqual(
            tiles[1].insight.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "math": "dau",
                            "name": "$feature_flag_called",
                            "event": "$feature_flag_called",
                        }
                    ],
                    "interval": "day",
                    "dateRange": {"date_from": "-30d", "explicitDate": False},
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "$feature_flag",
                                        "type": "event",
                                        "value": "alpha-feature",
                                        "operator": "exact",
                                    }
                                ],
                            }
                        ],
                    },
                    "trendsFilter": {
                        "display": "ActionsTable",
                        "showLegend": False,
                        "yAxisScaleType": "linear",
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "showPercentStackView": False,
                        "aggregationAxisFormat": "numeric",
                        "showAlertThresholdLines": False,
                    },
                    "breakdownFilter": {
                        "breakdown": "$feature_flag_response",
                        "breakdown_type": "event",
                    },
                    "filterTestAccounts": False,
                },
            },
        )

        # enriched insights
        assert tiles[2].insight is not None
        self.assertEqual(tiles[2].insight.name, "Feature Interaction Total Volume")
        self.assertEqual(
            tiles[2].insight.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": "Feature Interaction - Total",
                            "event": "$feature_interaction",
                        },
                        {
                            "kind": "EventsNode",
                            "math": "dau",
                            "name": "Feature Interaction - Unique users",
                            "event": "$feature_interaction",
                        },
                    ],
                    "interval": "day",
                    "dateRange": {"date_from": "-30d", "explicitDate": False},
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "feature_flag",
                                        "type": "event",
                                        "value": "alpha-feature",
                                        "operator": "exact",
                                    }
                                ],
                            }
                        ],
                    },
                    "trendsFilter": {
                        "display": "ActionsLineGraph",
                        "showLegend": False,
                        "yAxisScaleType": "linear",
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "showPercentStackView": False,
                        "aggregationAxisFormat": "numeric",
                        "showAlertThresholdLines": False,
                    },
                    "breakdownFilter": {"breakdown_type": "event"},
                    "filterTestAccounts": False,
                },
            },
        )
        assert tiles[3].insight is not None
        self.assertEqual(tiles[3].insight.name, "Feature Viewed Total Volume")
        self.assertEqual(
            tiles[3].insight.query,
            {
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {
                            "kind": "EventsNode",
                            "name": "Feature View - Total",
                            "event": "$feature_view",
                        },
                        {
                            "kind": "EventsNode",
                            "math": "dau",
                            "name": "Feature View - Unique users",
                            "event": "$feature_view",
                        },
                    ],
                    "interval": "day",
                    "dateRange": {"date_from": "-30d", "explicitDate": False},
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "AND",
                                "values": [
                                    {
                                        "key": "feature_flag",
                                        "type": "event",
                                        "value": "alpha-feature",
                                        "operator": "exact",
                                    }
                                ],
                            }
                        ],
                    },
                    "trendsFilter": {
                        "display": "ActionsLineGraph",
                        "showLegend": False,
                        "yAxisScaleType": "linear",
                        "showValuesOnSeries": False,
                        "smoothingIntervals": 1,
                        "showPercentStackView": False,
                        "aggregationAxisFormat": "numeric",
                        "showAlertThresholdLines": False,
                    },
                    "breakdownFilter": {"breakdown_type": "event"},
                    "filterTestAccounts": False,
                },
            },
        )

    @patch("posthog.personhog_client.client.get_personhog_client")
    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_group_feature_flag_usage_dashboard(self, mock_report_user_action, mock_personhog_client):
        mock_personhog_client.return_value.get_group_type_mappings_by_project_id.return_value = MagicMock(mappings=[])
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "rollout_percentage": 50,
                            "properties": [
                                {
                                    "key": "industry",
                                    "value": "finance",
                                    "type": "group",
                                    "group_type_index": 0,
                                }
                            ],
                        }
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])

        dashboard = instance.usage_dashboard
        assert dashboard is not None
        assert dashboard.tiles is not None
        tiles = sorted(
            dashboard.tiles.all(),
            key=lambda x: str(x.insight.name if x.insight is not None else ""),
        )
        self.assertEqual(len(tiles), 2)

        group_property_filter = {
            "key": "$group_0",
            "type": "event",
            "value": "is_set",
            "operator": "is_set",
        }
        flag_property_filter = {
            "key": "$feature_flag",
            "type": "event",
            "value": "group-feature",
            "operator": "exact",
        }

        assert tiles[0].insight is not None
        total_volume_query = cast(dict[str, Any], tiles[0].insight.query)
        total_volume_properties = total_volume_query["source"]["properties"]["values"][0]["values"]
        self.assertEqual(total_volume_properties, [flag_property_filter, group_property_filter])

        assert tiles[1].insight is not None
        self.assertEqual(tiles[1].insight.name, "Feature Flag calls made by unique groups per variant")
        self.assertEqual(
            tiles[1].insight.description,
            "Shows the number of unique group calls made on feature flag per variant with key: group-feature",
        )
        unique_calls_query = cast(dict[str, Any], tiles[1].insight.query)
        unique_calls_series = unique_calls_query["source"]["series"][0]
        self.assertEqual(unique_calls_series["math"], "unique_group")
        self.assertEqual(unique_calls_series["math_group_type_index"], 0)
        unique_calls_properties = unique_calls_query["source"]["properties"]["values"][0]["values"]
        self.assertEqual(unique_calls_properties, [flag_property_filter, group_property_filter])

    @patch("posthog.personhog_client.client.get_personhog_client")
    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_update_group_feature_flag_key_updates_usage_dashboard(
        self, mock_report_user_action, mock_personhog_client
    ):
        mock_personhog_client.return_value.get_group_type_mappings_by_project_id.return_value = MagicMock(mappings=[])
        create = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Group feature",
                "key": "group-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 50}],
                },
            },
            format="json",
        )
        self.assertEqual(create.status_code, status.HTTP_201_CREATED)
        flag_id = create.json()["id"]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            {
                "key": "renamed-group-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 50}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dashboard = FeatureFlag.objects.get(id=flag_id).usage_dashboard
        assert dashboard is not None
        assert dashboard.tiles is not None
        tiles = sorted(
            dashboard.tiles.all(),
            key=lambda x: str(x.insight.name if x.insight is not None else ""),
        )

        expected_properties = [
            {"key": "$feature_flag", "type": "event", "value": "renamed-group-feature", "operator": "exact"},
            {"key": "$group_0", "type": "event", "value": "is_set", "operator": "is_set"},
        ]

        assert tiles[0].insight is not None
        total_volume_query = cast(dict[str, Any], tiles[0].insight.query)
        self.assertEqual(total_volume_query["source"]["properties"]["values"][0]["values"], expected_properties)

        assert tiles[1].insight is not None
        unique_calls_query = cast(dict[str, Any], tiles[1].insight.query)
        self.assertEqual(unique_calls_query["source"]["properties"]["values"][0]["values"], expected_properties)
        self.assertEqual(
            tiles[1].insight.description,
            "Shows the number of unique group calls made on feature flag per variant with key: renamed-group-feature",
        )

    @freeze_time("2021-08-25T22:09:14.252Z")
    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_dashboard_enrichment_fails_if_already_enriched(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        # now enable enriched analytics
        instance.has_enriched_analytics = True
        instance.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # now try enriching again
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"error": "Usage dashboard already has enriched data", "success": False},
        )

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_dashboard_enrichment_fails_if_no_enriched_data(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {"groups": [{"rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag_id = response.json()["id"]
        instance = FeatureFlag.objects.get(id=flag_id)
        self.assertEqual(instance.key, "alpha-feature")

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/enrich_usage_dashboard",
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "error": "No enriched analytics available for this feature flag",
                "success": False,
            },
        )

    @patch("products.feature_flags.backend.flag_analytics.CACHE_BUCKET_SIZE", 10)
    def test_local_evaluation_billing_analytics_for_regular_feature_flag_list(self):
        FeatureFlag.objects.all().delete()

        # old style feature flags
        FeatureFlag.objects.create(
            name="Beta feature",
            key="beta-feature",
            team=self.team,
            filters={"properties": [{"key": "beta-property", "value": "beta-value"}]},
            created_by=self.user,
        )
        # and inactive flag
        FeatureFlag.objects.create(
            name="Inactive feature",
            key="inactive-flag",
            team=self.team,
            active=False,
            filters={"properties": []},
            created_by=self.user,
        )

        client = redis.get_client()

        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X", user=self.user, scopes=["*"], secure_value=hash_key_value(personal_api_key)
        )

        # request made while logged in, via client cookie auth
        response = self.client.get(f"/api/feature_flag?token={self.team.api_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 2)

        # shouldn't add to local eval requests
        self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

        self.client.logout()
        # `local_evaluation` is called by logged out clients!

        with freeze_time("2022-05-07 12:23:07"):
            # missing API key
            response = self.client.get(f"/api/feature_flag?token={self.team.api_token}")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

            response = self.client.get(f"/api/feature_flag/")
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"), {})

            response = self.client.get(
                f"/api/feature_flag/?token={self.team.api_token}",
                headers={"authorization": f"Bearer {personal_api_key}"},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"),
                {b"165192618": b"1"},
            )

            for _ in range(4):
                response = self.client.get(
                    f"/api/feature_flag/?token={self.team.api_token}",
                    headers={"authorization": f"Bearer {personal_api_key}"},
                )
                self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                client.hgetall(f"posthog:local_evaluation_requests:{self.team.pk}"),
                {b"165192618": b"5"},
            )

    @parameterized.expand(
        [
            ("malformed_relative", "6hed", "is_date_before"),
            ("malformed_absolute", "1234-02-993284", "is_date_after"),
            ("malformed_exact", "not-a-date", "is_date_exact"),
        ]
    )
    def test_create_flag_with_invalid_date(self, _name, invalid_date, operator):
        resp = self._create_flag_with_properties(
            "date-flag",
            [
                {
                    "key": "created_for",
                    "type": "person",
                    "value": invalid_date,
                    "operator": operator,
                }
            ],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "invalid_date",
                "detail": f"Invalid date value: {invalid_date}",
                "attr": "filters",
            }.items(),
            resp.json().items(),
        )

    @parameterized.expand(
        [
            ("between", "between"),
            ("not_between", "not_between"),
            ("is_cleaned_path_exact", "is_cleaned_path_exact"),
        ]
    )
    def test_cant_create_flag_with_unsupported_operator(self, _name, operator):
        resp = self._create_flag_with_properties(
            "unsupported-op-flag",
            [{"key": "age", "type": "person", "value": "test", "operator": operator}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(resp.json()["code"], "unsupported_operator")
        self.assertIn(operator, resp.json()["detail"])

    @parameterized.expand(
        [
            ("between", "between"),
            ("not_between", "not_between"),
            ("is_cleaned_path_exact", "is_cleaned_path_exact"),
        ]
    )
    def test_cant_update_flag_with_unsupported_operator(self, _name, operator):
        flag = self._create_flag_with_properties(
            f"flag-to-update-{_name}",
            [{"key": "age", "type": "person", "value": "test", "operator": "exact"}],
        )
        resp = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.json()['id']}/",
            {
                "filters": {
                    "groups": [
                        {"properties": [{"key": "age", "type": "person", "value": "test", "operator": operator}]}
                    ]
                }
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.json()["code"], "unsupported_operator")
        self.assertIn(operator, resp.json()["detail"])

    @parameterized.expand(
        [
            ("min_to_gte", "min", "gte"),
            ("max_to_lte", "max", "lte"),
        ]
    )
    def test_create_flag_aliases_operator(self, _name, input_op, saved_op):
        resp = self._create_flag_with_properties(
            f"alias-flag-{_name}",
            [{"key": "age", "type": "person", "value": "10", "operator": input_op}],
        )
        saved_operator = resp.json()["filters"]["groups"][0]["properties"][0]["operator"]
        self.assertEqual(saved_operator, saved_op)

    @parameterized.expand(
        [
            ("min_to_gte", "min", "gte"),
            ("max_to_lte", "max", "lte"),
        ]
    )
    def test_update_flag_aliases_operator(self, _name, input_op, saved_op):
        flag = self._create_flag_with_properties(
            f"flag-alias-update-{_name}",
            [{"key": "age", "type": "person", "value": "5", "operator": "exact"}],
        )
        resp = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.json()['id']}/",
            {
                "filters": {
                    "groups": [{"properties": [{"key": "age", "type": "person", "value": "10", "operator": input_op}]}]
                }
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        saved_operator = resp.json()["filters"]["groups"][0]["properties"][0]["operator"]
        self.assertEqual(saved_operator, saved_op)

    @parameterized.expand(
        [
            ("not_a_string", "semver_gt", 123),
            ("list_value", "semver_eq", ["1.2.3"]),
            ("invalid_format", "semver_lt", "not-semver"),
            ("empty_string", "semver_gte", ""),
            ("tilde_invalid", "semver_tilde", "abc"),
            ("caret_invalid", "semver_caret", "x.y.z"),
            ("wildcard_invalid", "semver_wildcard", ""),
        ]
    )
    def test_create_flag_with_invalid_semver_value(self, _name, operator, value):
        resp = self._create_flag_with_properties(
            "semver-flag",
            [{"key": "app_version", "type": "person", "value": value, "operator": operator}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(resp.json()["code"], "invalid_value")

    @parameterized.expand(
        [
            ("eq", "semver_eq", "1.2.3"),
            ("neq", "semver_neq", "2.0.0"),
            ("gt", "semver_gt", "1.0"),
            ("gte", "semver_gte", "0.1.0"),
            ("lt", "semver_lt", "10.20.30"),
            ("lte", "semver_lte", "1.0.0"),
            ("tilde", "semver_tilde", "1.2.3"),
            ("tilde_bare_major", "semver_tilde", "1"),
            ("caret", "semver_caret", "0.2.3"),
            ("wildcard", "semver_wildcard", "1.2.*"),
        ]
    )
    def test_create_flag_with_valid_semver_value(self, _name, operator, value):
        self._create_flag_with_properties(
            f"semver-flag-{_name}",
            [{"key": "app_version", "type": "person", "value": value, "operator": operator}],
            expected_status=status.HTTP_201_CREATED,
        )

    @parameterized.expand(
        [
            ("scalar_string", "icontains_multi", "just-a-string"),
            ("integer", "not_icontains_multi", 42),
        ]
    )
    def test_create_flag_with_invalid_multi_contains_value(self, _name, operator, value):
        resp = self._create_flag_with_properties(
            "multi-flag",
            [{"key": "url", "type": "person", "value": value, "operator": operator}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(resp.json()["code"], "invalid_value")
        self.assertIn("requires a list", resp.json()["detail"])

    @parameterized.expand(
        [
            ("icontains_multi_list", "icontains_multi", ["foo", "bar"]),
            ("not_icontains_multi_list", "not_icontains_multi", ["baz"]),
        ]
    )
    def test_create_flag_with_valid_multi_contains_value(self, _name, operator, value):
        self._create_flag_with_properties(
            f"multi-flag-{_name}",
            [{"key": "url", "type": "person", "value": value, "operator": operator}],
            expected_status=status.HTTP_201_CREATED,
        )

    def test_creating_feature_flag_with_non_existant_cohort(self):
        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": 5151}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "cohort_does_not_exist",
                "detail": "Cohort with id 5151 does not exist",
                "attr": "filters",
            }.items(),
            cohort_request.json().items(),
        )

    def test_validation_payloads(self):
        self._create_flag_with_properties(
            "person-flag",
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
            payloads={"true": 300},
            expected_status=status.HTTP_201_CREATED,
        )
        self._create_flag_with_properties(
            "person-flag",
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
            payloads={"some-fake-key": 300},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
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
                    "payloads": {"first-variant": {"some": "payload"}},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
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
                    "payloads": {
                        "first-variant": {"some": "payload"},
                        "fourth-variant": {"some": "payload"},
                    },
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Multivariate feature",
                "key": "multivariate-feature",
                "filters": {
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
                    "payloads": {"first-variant": {"some": "payload"}, "true": 2500},
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        valid_json_payload = self._create_flag_with_properties(
            "json-flag",
            [{"key": "key", "value": "value", "type": "person"}],
            payloads={"true": json.dumps({"key": "value"})},
            expected_status=status.HTTP_201_CREATED,
        )
        self.assertEqual(valid_json_payload.status_code, status.HTTP_201_CREATED)

        invalid_json_payload = self._create_flag_with_properties(
            "invalid-json-flag",
            [{"key": "key", "value": "value", "type": "person"}],
            payloads={"true": "{invalid_json}"},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(invalid_json_payload.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid_json_payload.json()["detail"], "Payload value is not valid JSON")

        non_string_payload = self._create_flag_with_properties(
            "non-string-json-flag",
            [{"key": "key", "value": "value", "type": "person"}],
            payloads={"true": {"key": "value"}},
            expected_status=status.HTTP_201_CREATED,
        )
        self.assertEqual(non_string_payload.status_code, status.HTTP_201_CREATED)
        # Object payloads should be normalized to JSON strings
        stored_payload = non_string_payload.json()["filters"]["payloads"]["true"]
        self.assertIsInstance(stored_payload, str)
        self.assertEqual(json.loads(stored_payload), {"key": "value"})

    @parameterized.expand(
        [
            ("number", 42),
            ("boolean", True),
            ("null", None),
            ("array", [1, 2, 3]),
        ]
    )
    def test_non_string_payloads_are_normalized_to_json_strings(self, name, raw_value):
        # Other valid JSON types (number, boolean, null, array) are accepted and
        # normalized to JSON strings, matching how object payloads are stored.
        response = self._create_flag_with_properties(
            f"{name}-payload-flag",
            [{"key": "key", "value": "value", "type": "person"}],
            payloads={"true": raw_value},
            expected_status=status.HTTP_201_CREATED,
        )
        stored = response.json()["filters"]["payloads"]["true"]
        self.assertIsInstance(stored, str)
        self.assertEqual(json.loads(stored), raw_value)

    @parameterized.expand(
        [
            ("empty", ""),
            ("whitespace", "   "),
        ]
    )
    def test_blank_string_payloads_are_rejected(self, name, blank_value):
        # An empty or whitespace-only string isn't valid JSON (the common "user cleared
        # the field" case), so it's rejected rather than coerced.
        response = self._create_flag_with_properties(
            f"{name}-payload-flag",
            [{"key": "key", "value": "value", "type": "person"}],
            payloads={"true": blank_value},
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Payload value is not valid JSON")

    def test_creating_feature_flag_with_behavioral_cohort(self):
        cohort_valid_for_ff = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "$some_prop", "value": "nomatchihope", "type": "person"}]}],
            name="cohort1",
        )

        cohort_not_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                        {"key": "email", "value": "test@posthog.com", "type": "person"},
                    ],
                }
            },
            name="cohort2",
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort_not_valid_for_ff.id}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort2' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            }.items(),
            cohort_request.json().items(),
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort_valid_for_ff.id}],
            expected_status=status.HTTP_201_CREATED,
        )
        flag_id = cohort_request.json()["id"]
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            {
                "name": "Updated name",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "id",
                                    "type": "cohort",
                                    "value": cohort_not_valid_for_ff.id,
                                }
                            ],
                        }
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort2' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            }.items(),
            response.json().items(),
        )

    def test_creating_feature_flag_with_static_snapshot_cohort_that_preserves_behavioral_filters(self) -> None:
        cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "event_type": "events",
                            "explicit_datetime": "-14d",
                            "key": "$pageview",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        }
                    ],
                }
            },
        )

        self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort.id}],
            expected_status=status.HTTP_201_CREATED,
        )

    def test_creating_feature_flag_with_cohort_depending_on_static_snapshot_cohort(self) -> None:
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "event_type": "events",
                            "explicit_datetime": "-14d",
                            "key": "$pageview",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        }
                    ],
                }
            },
        )
        static_cohort = Cohort.objects.create(
            team=self.team,
            is_static=True,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"key": "id", "type": "cohort", "value": behavioral_cohort.id}],
                }
            },
        )
        cohort = Cohort.objects.create(
            team=self.team,
            groups=[{"properties": [{"key": "id", "type": "cohort", "value": static_cohort.id}]}],
        )

        self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort.id}],
            expected_status=status.HTTP_201_CREATED,
        )

    def test_creating_feature_flag_with_nested_behavioral_cohort(self):
        cohort_not_valid_for_ff = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                        {"key": "email", "value": "test@posthog.com", "type": "person"},
                    ],
                }
            },
            name="cohort-behavioural",
        )

        nested_cohort_not_valid_for_ff = Cohort.objects.create(
            team=self.team,
            groups=[
                {
                    "properties": [
                        {
                            "key": "id",
                            "value": cohort_not_valid_for_ff.pk,
                            "type": "cohort",
                        }
                    ]
                }
            ],
            name="cohort-not-behavioural",
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [
                {
                    "key": "id",
                    "type": "cohort",
                    "value": nested_cohort_not_valid_for_ff.id,
                }
            ],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort-behavioural' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            }.items(),
            cohort_request.json().items(),
        )

        cohort_request = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort_not_valid_for_ff.id}],
            expected_status=status.HTTP_400_BAD_REQUEST,
        )

        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "behavioral_cohort_found",
                "detail": "Cohort 'cohort-behavioural' with filters on events cannot be used in feature flags.",
                "attr": "filters",
            }.items(),
            cohort_request.json().items(),
        )

    @parameterized.expand(
        [
            (
                "realtime_backfilled_flag_on",
                CohortType.REALTIME,
                True,
                True,
                status.HTTP_201_CREATED,
                None,
            ),
            (
                "realtime_not_backfilled_flag_on",
                CohortType.REALTIME,
                False,
                True,
                status.HTTP_400_BAD_REQUEST,
                "is still being backfilled",
            ),
            (
                "non_realtime_flag_on",
                None,
                False,
                True,
                status.HTTP_400_BAD_REQUEST,
                "filters on events",
            ),
            (
                "realtime_backfilled_flag_off",
                CohortType.REALTIME,
                True,
                False,
                status.HTTP_400_BAD_REQUEST,
                "filters on events",
            ),
        ]
    )
    @patch("products.feature_flags.backend.api.feature_flag.feature_enabled_or_false")
    def test_behavioral_cohort_flag_validation(
        self,
        _name,
        cohort_type,
        is_backfilled,
        flag_enabled,
        expected_status,
        expected_detail_fragment,
        mock_feature_enabled,
    ):
        mock_feature_enabled.return_value = flag_enabled

        cohort_kwargs: dict[str, Any] = {
            "team": self.team,
            "name": "test-cohort",
            "filters": {
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                    ],
                }
            },
        }
        if cohort_type is not None:
            cohort_kwargs["cohort_type"] = cohort_type
        if is_backfilled:
            cohort_kwargs["last_backfill_person_properties_at"] = datetime.now(tz=UTC)

        cohort = Cohort.objects.create(**cohort_kwargs)

        response = self._create_flag_with_properties(
            "cohort-flag",
            [{"key": "id", "type": "cohort", "value": cohort.id}],
            expected_status=expected_status,
        )
        self.assertEqual(response.status_code, expected_status)

        if expected_detail_fragment is not None:
            self.assertIn(expected_detail_fragment, response.json()["detail"])

    def test_snapshot_cohort_referencing_behavioral_cohort_is_allowed_in_flag(self):
        # A snapshot cohort is is_static=True but retains its populating criteria,
        # which can reference another (behavioral) cohort. The dependency walk must
        # be skipped for static cohorts so the referenced behavioral cohort doesn't
        # block flag creation — matching the Rust engine, whose extract_dependencies
        # returns an empty set for static cohorts.
        behavioral_cohort = Cohort.objects.create(
            team=self.team,
            name="behavioral-dep",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "$pageview",
                            "event_type": "events",
                            "time_value": 2,
                            "time_interval": "week",
                            "value": "performed_event_first_time",
                            "type": "behavioral",
                        },
                    ],
                }
            },
        )
        snapshot_cohort = Cohort.objects.create(
            team=self.team,
            name="snapshot",
            is_static=True,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"key": "id", "type": "cohort", "value": behavioral_cohort.id},
                    ],
                }
            },
        )

        self._create_flag_with_properties(
            "snapshot-cohort-flag",
            [{"key": "id", "type": "cohort", "value": snapshot_cohort.id}],
            expected_status=status.HTTP_201_CREATED,
        )

    def test_validation_group_properties(self):
        groups_request = self._create_flag_with_properties(
            "groups-flag",
            [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ],
            aggregation_group_type_index=0,
        )
        self.assertEqual(groups_request.status_code, status.HTTP_201_CREATED)

        illegal_groups_request = self._create_flag_with_properties(
            "illegal-groups-flag",
            [
                {
                    "key": "industry",
                    "value": "finance",
                    "type": "group",
                    "group_type_index": 0,
                }
            ],
            aggregation_group_type_index=3,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            illegal_groups_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (group properties must match the condition set's group type)",
                "attr": "filters",
            },
        )

        person_request = self._create_flag_with_properties(
            "person-flag",
            [
                {
                    "key": "email",
                    "type": "person",
                    "value": "@posthog.com",
                    "operator": "icontains",
                }
            ],
            aggregation_group_type_index=0,
            expected_status=status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            person_request.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Filters are not valid (group-aggregated conditions can only use group properties)",
                "attr": "filters",
            },
        )

    def test_mixed_aggregation_types_across_condition_sets(self):
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Mixed aggregation flag",
                "key": "mixed-aggregation-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 50,
                            "aggregation_group_type_index": None,  # Person aggregation
                        },
                        {
                            "properties": [],
                            "rollout_percentage": 50,
                            "aggregation_group_type_index": 0,  # Group aggregation
                        },
                    ]
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Flag-level aggregation is None when condition sets have mixed aggregation types
        self.assertIsNone(response.json()["filters"]["aggregation_group_type_index"])
        # Each condition set retains its own aggregation type
        groups = response.json()["filters"]["groups"]
        self.assertIsNone(groups[0]["aggregation_group_type_index"])
        self.assertEqual(groups[1]["aggregation_group_type_index"], 0)

    def test_mixed_aggregation_round_trip(self):
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        create_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Round-trip flag",
                "key": "round-trip-mixed",
                "filters": {
                    "groups": [
                        {"properties": [], "rollout_percentage": 50, "aggregation_group_type_index": None},
                        {"properties": [], "rollout_percentage": 75, "aggregation_group_type_index": 0},
                    ]
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        get_response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{create_response.json()['id']}/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        filters = get_response.json()["filters"]
        self.assertIsNone(filters["aggregation_group_type_index"])
        self.assertIsNone(filters["groups"][0]["aggregation_group_type_index"])
        self.assertEqual(filters["groups"][1]["aggregation_group_type_index"], 0)

    def test_mixed_aggregation_with_properties(self):
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Mixed flag with properties",
                "key": "mixed-with-props",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {"key": "email", "value": ["user@example.com"], "operator": "exact", "type": "person"}
                            ],
                            "rollout_percentage": 100,
                            "aggregation_group_type_index": None,
                        },
                        {
                            "properties": [
                                {
                                    "key": "created_at",
                                    "value": "2026-03-10",
                                    "operator": "is_date_after",
                                    "type": "group",
                                    "group_type_index": 0,
                                }
                            ],
                            "rollout_percentage": 100,
                            "aggregation_group_type_index": 0,
                        },
                    ]
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        groups = response.json()["filters"]["groups"]
        self.assertIsNone(groups[0]["aggregation_group_type_index"])
        self.assertEqual(groups[1]["aggregation_group_type_index"], 0)

    def test_patch_uniform_flag_to_mixed(self):
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        # Create a uniform person-aggregated flag
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="uniform-to-mixed",
            name="Uniform flag",
            filters={
                "groups": [
                    {"properties": [], "rollout_percentage": 100, "aggregation_group_type_index": None},
                ]
            },
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "filters": {
                    "groups": [
                        {"properties": [], "rollout_percentage": 50, "aggregation_group_type_index": None},
                        {"properties": [], "rollout_percentage": 75, "aggregation_group_type_index": 0},
                    ]
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Flag-level aggregation collapses to None once condition sets are mixed
        filters = response.json()["filters"]
        self.assertIsNone(filters["aggregation_group_type_index"])
        # Each condition set retains its own aggregation type
        self.assertIsNone(filters["groups"][0]["aggregation_group_type_index"])
        self.assertEqual(filters["groups"][1]["aggregation_group_type_index"], 0)

    def test_per_condition_aggregation_normalization(self):
        """Test that flag-level aggregation is distributed to condition sets without one"""
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Normalized aggregation flag",
                "key": "normalized-aggregation-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {"properties": [], "rollout_percentage": 100},
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        result = response.json()
        # Flag-level should be preserved
        self.assertEqual(result["filters"]["aggregation_group_type_index"], 0)
        # Condition set should have inherited the flag-level value
        self.assertEqual(result["filters"]["groups"][0]["aggregation_group_type_index"], 0)

    def test_per_condition_aggregation_roundtrip(self):
        """Test that per-condition aggregation values persist through create/read"""
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )

        # Create with explicit per-condition value
        create_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Per-condition aggregation flag",
                "key": "per-condition-aggregation-flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [],
                            "rollout_percentage": 100,
                            "aggregation_group_type_index": 0,
                        },
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        flag_id = create_response.json()["id"]

        # Read it back
        get_response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/")
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        result = get_response.json()

        # Both flag-level and condition-level should be present and consistent
        self.assertEqual(result["filters"]["aggregation_group_type_index"], 0)
        self.assertEqual(result["filters"]["groups"][0]["aggregation_group_type_index"], 0)

    def test_validation_empty_groups(self):
        """Test that creating a flag with empty groups raises validation error"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Empty groups flag",
                "key": "empty-groups-flag",
                "filters": {"groups": []},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Feature flags must have at least one condition set (group).",
                "attr": "filters",
            },
        )

    def test_create_without_filters_persists_groups_invariant(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"name": "No filters flag", "key": "no-filters-flag"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.filters, {"groups": []})

    def test_validation_groups_with_empty_properties_allowed(self):
        """Test that creating a flag with groups having empty properties but valid rollout is allowed"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Valid flag with empty properties",
                "key": "valid-empty-properties",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_validation_empty_groups_allowed_on_update(self):
        """Test that updating an existing flag with empty groups is allowed (for scheduled changes)"""
        # First create a valid flag
        flag = FeatureFlag.objects.create(
            name="Test flag",
            key="test-flag-update",
            team=self.team,
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Now try to update it with empty groups (this should be allowed)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"filters": {"groups": []}},
            format="json",
        )
        # Should succeed since it's an update, not creation
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            # name, bucketing_identifier, ensure_experience_continuity, expected_status
            ("device_with_persist_blocked", "device_id", True, status.HTTP_400_BAD_REQUEST),
            ("device_without_persist_allowed", "device_id", False, status.HTTP_201_CREATED),
        ]
    )
    def test_validation_device_bucketing_create(
        self, _name: str, bucketing_identifier: str, ensure_experience_continuity: bool, expected_status: int
    ):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": f"Device bucketing {_name}",
                "key": f"device-{_name.replace('_', '-')}-flag",
                "bucketing_identifier": bucketing_identifier,
                "ensure_experience_continuity": ensure_experience_continuity,
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.assertIn("Cannot enable 'persist across authentication steps'", response.json()["detail"])

    @parameterized.expand(
        [
            # name, initial_persist, patch_payload, expected_status
            (
                "grandfathered_combination_can_save",
                True,
                {"name": "Updated grandfathered flag"},
                status.HTTP_200_OK,
            ),
            (
                "enabling_persist_on_device_flag_blocked",
                False,
                {"ensure_experience_continuity": True},
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_validation_device_bucketing_update(
        self, _name: str, initial_persist: bool, patch_payload: dict, expected_status: int
    ):
        flag = FeatureFlag.objects.create(
            name=f"Existing flag {_name}",
            key=f"existing-{_name.replace('_', '-')}",
            team=self.team,
            created_by=self.user,
            bucketing_identifier="device_id",
            ensure_experience_continuity=initial_persist,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            patch_payload,
            format="json",
        )
        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.assertIn("Cannot enable 'persist across authentication steps'", response.json()["detail"])

    def test_validation_device_bucketing_blocked_for_surveys_creation_context(self):
        # Locks in the validation reorder: device_id + persist must be rejected even for the
        # surveys creation_context, which has its own early return in validate(). Without the
        # hoist, this combination would slip through for survey-created flags.
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Survey-created device persist flag",
                "key": "survey-device-persist-flag",
                "creation_context": "surveys",
                "bucketing_identifier": "device_id",
                "ensure_experience_continuity": True,
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot enable 'persist across authentication steps'", response.json()["detail"])

    def _create_flag_with_properties(
        self,
        name: str,
        properties,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_201_CREATED,
        **kwargs,
    ):
        if team_id is None:
            team_id = self.team.id

        create_response = self.client.post(
            f"/api/projects/{team_id}/feature_flags/",
            data={
                "name": name,
                "key": name,
                "filters": {**kwargs, "groups": [{"properties": properties}]},
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, expected_status)
        return create_response

    def _get_feature_flag_activity(
        self,
        flag_id: Optional[int] = None,
        team_id: Optional[int] = None,
        expected_status: int = status.HTTP_200_OK,
    ):
        if team_id is None:
            team_id = self.team.id

        if flag_id:
            url = f"/api/projects/{team_id}/feature_flags/{flag_id}/activity"
        else:
            url = f"/api/projects/{team_id}/feature_flags/activity"

        activity = self.client.get(url)
        self.assertEqual(activity.status_code, expected_status)
        if activity.status_code == status.HTTP_404_NOT_FOUND:
            return None
        return activity.json()

    def assert_feature_flag_activity(self, flag_id: Optional[int], expected: list[dict]):
        activity_response = self._get_feature_flag_activity(flag_id)

        activity: list[dict] = activity_response["results"]
        for item in activity:
            item.pop("id", None)
        self.maxDiff = None
        assert activity == expected

    def test_patch_api_as_form_data(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": None,
            },
            active=True,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{another_feature_flag.pk}/",
            data="active=False&name=replaced",
            content_type="application/x-www-form-urlencoded",
        )

        self.assertEqual(response.status_code, 200)
        updated_flag = FeatureFlag.objects.get(pk=another_feature_flag.pk)
        self.assertEqual(updated_flag.active, False)
        self.assertEqual(updated_flag.name, "replaced")
        self.assertEqual(
            updated_flag.filters,
            {
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": None,
            },
        )

    def test_feature_flag_threshold(self):
        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 65}],
                },
                "rollback_conditions": [
                    {
                        "threshold": 5000,
                        "threshold_metric": {
                            "insight": "trends",
                            "events": [{"order": 0, "id": "$pageview"}],
                            "properties": [
                                {
                                    "key": "$geoip_country_name",
                                    "type": "person",
                                    "value": ["france"],
                                    "operator": "exact",
                                }
                            ],
                        },
                        "operator": "lt",
                        "threshold_type": "insight",
                    }
                ],
                "auto-rollback": True,
            },
            format="json",
        ).json()

        self.assertEqual(len(feature_flag["rollback_conditions"]), 1)

    def test_get_flags_dont_return_survey_targeting_flags(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        survey = self.client.post(
            f"/api/projects/{self.team.id}/surveys/",
            data={
                "name": "Notebooks power users survey",
                "type": "popover",
                "questions": [
                    {
                        "type": "open",
                        "question": "What would you want to improve from notebooks?",
                    }
                ],
                "targeting_flag_filters": {
                    "groups": [
                        {
                            "variant": None,
                            "rollout_percentage": None,
                            "properties": [
                                {
                                    "key": "billing_plan",
                                    "value": ["cloud"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
                "conditions": {"url": "https://app.posthog.com/notebooks"},
            },
            format="json",
        )
        assert FeatureFlag.objects.filter(id=survey.json()["targeting_flag"]["id"]).exists()

        flags_list = self.client.get(f"/api/projects/@current/feature_flags")
        response = flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["id"] is not survey.json()["targeting_flag"]["id"]

    def test_get_flags_dont_return_product_tour_internal_targeting_flags(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")

        internal_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="product-tour-targeting-test-tour-abc123",
            filters={"groups": [{"rollout_percentage": 100}]},
        )
        ProductTour.objects.create(
            team=self.team,
            name="Test Tour",
            content={"steps": []},
            internal_targeting_flag=internal_flag,
        )

        flags_list = self.client.get("/api/projects/@current/feature_flags")
        response = flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "red_button"

    def test_get_flags_with_active_and_created_by_id_filters(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        another_user = User.objects.create(email="foo@bar.com")
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="blue_button")
        FeatureFlag.objects.create(team=self.team, created_by=another_user, key="orange_button", active=False)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="green_button", active=False)

        filtered_flags_list = self.client.get(
            f"/api/projects/@current/feature_flags?created_by_id={self.user.id}&active=false"
        )
        response = filtered_flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "green_button"

    @parameterized.expand(
        [
            # (name, format_filter, expected_keys)
            ("json_list", lambda ids: json.dumps([ids[0], ids[1]]), {"red_button", "blue_button"}),
            ("comma_separated", lambda ids: f"{ids[0]},{ids[2]}", {"red_button", "orange_button"}),
            ("single_id", lambda ids: str(ids[1]), {"blue_button"}),
            ("no_match", lambda ids: json.dumps([ids[3]]), set()),
        ]
    )
    def test_get_flags_with_multiple_created_by_id_filter(self, _name, format_filter, expected_keys):
        another_user = User.objects.create(email="foo@bar.com")
        third_user = User.objects.create(email="baz@bar.com")
        unrelated_user = User.objects.create(email="nobody@bar.com")
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        FeatureFlag.objects.create(team=self.team, created_by=another_user, key="blue_button")
        FeatureFlag.objects.create(team=self.team, created_by=third_user, key="orange_button")

        ids = [self.user.id, another_user.id, third_user.id, unrelated_user.id]
        response = self.client.get(f"/api/projects/@current/feature_flags?created_by_id={format_filter(ids)}")
        assert {flag["key"] for flag in response.json()["results"]} == expected_keys

    @parameterized.expand(
        [
            ("none", None, []),
            ("bool_true", True, []),
            ("int", 42, [42]),
            ("single_str", "42", [42]),
            ("empty_str", "", []),
            ("comma_separated", "1,2", [1, 2]),
            ("comma_with_invalid", "1,abc,3", [1, 3]),
            ("json_list", "[1, 2]", [1, 2]),
            ("non_numeric", "abc", []),
            ("malformed_json", "[5", []),
        ]
    )
    def test_parse_created_by_ids(self, _name, value, expected):
        assert parse_created_by_ids(value) == expected

    def test_get_flags_with_type_filters(self):
        feature_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="red_button")
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Experiment 1",
            feature_flag_id=feature_flag.id,
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="purple_button",
            filters={"multivariate": {"variants": [{"foo": "bar"}]}},
        )

        filtered_flags_list_boolean = self.client.get(f"/api/projects/@current/feature_flags?type=boolean")
        response = filtered_flags_list_boolean.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == feature_flag.key

        filtered_flags_list_multivariant = self.client.get(f"/api/projects/@current/feature_flags?type=multivariant")
        response = filtered_flags_list_multivariant.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "purple_button"

        filtered_flags_list_experiment = self.client.get(f"/api/projects/@current/feature_flags?type=experiment")
        response = filtered_flags_list_experiment.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == feature_flag.key

    def test_get_flags_with_search(self):
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="blue_search_term_button")
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="green_search_term_button",
            active=False,
        )

        # Test searching by flag key
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?active=true&search=search_term")
        response = filtered_flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "blue_search_term_button"

        # Test searching by experiment name
        flag_with_experiment = FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="experiment_flag", active=True
        )
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="unique_experiment_name",
            feature_flag=flag_with_experiment,
            deleted=False,
        )

        filtered_by_experiment = self.client.get(f"/api/projects/@current/feature_flags?search=unique_experiment_name")
        response = filtered_by_experiment.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "experiment_flag"

        # Test that deleted experiments are not included in search
        deleted_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="deleted_experiment_flag",
            active=True,
        )
        Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="deleted_unique_experiment",
            feature_flag=deleted_flag,
            deleted=True,
        )

        filtered_deleted = self.client.get(f"/api/projects/@current/feature_flags?search=deleted_unique_experiment")
        response = filtered_deleted.json()
        assert len(response["results"]) == 0

    def test_get_flags_with_search_word_boundaries(self):
        """Test that search handles word boundaries correctly (spaces, hyphens, underscores)."""
        # Create flags with different word separators
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="feature-flag-test", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="feature_flag_experiment", active=True)
        FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="my_feature_button", active=True, name="Feature Button Display"
        )
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="unrelated-item", active=True)

        # Test searching for "feature flag" should match hyphenated and underscored versions
        response = self.client.get(f"/api/projects/@current/feature_flags?search=feature flag")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}

        # Full-text search should find flags where "feature" and "flag" appear as separate words
        # This should match hyphenated and underscored versions
        expected_matches = {"feature-flag-test", "feature_flag_experiment"}
        assert expected_matches.issubset(matched_keys), f"Expected {expected_matches} to be found in {matched_keys}"
        assert "unrelated-item" not in matched_keys

        # Test searching by name (which has spaces)
        response = self.client.get(f"/api/projects/@current/feature_flags?search=Feature Button")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}

        # Should match flag by name
        assert "my_feature_button" in matched_keys, f"Expected to find flag by name, got {matched_keys}"

        # Test searching for "feature" should match all flags containing that word
        response = self.client.get(f"/api/projects/@current/feature_flags?search=feature")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}

        # Should match all flags containing "feature"
        expected_matches = {"feature-flag-test", "feature_flag_experiment", "my_feature_button"}
        assert expected_matches.issubset(matched_keys), f"Expected {expected_matches} to be found in {matched_keys}"

    def test_get_flags_with_search_partial_word_matching(self):
        """Test that search handles partial word matching using regex patterns."""
        # Create flags to test different word separators
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="web-analytics", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="web_dashboard", active=True)
        FeatureFlag.objects.create(
            team=self.team, created_by=self.user, key="web analytics", name="Web Analytics Feature", active=True
        )
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="mobile-analytics", active=True)

        # Test searching for "web ana" should match various separators
        response = self.client.get(f"/api/projects/@current/feature_flags?search=web ana")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}

        # Should match web-analytics and "web analytics" (by name)
        assert "web-analytics" in matched_keys, f"Expected 'web-analytics' in {matched_keys}"
        assert "web analytics" in matched_keys, f"Expected 'web analytics' in {matched_keys}"
        assert "mobile-analytics" not in matched_keys, "Should not match mobile-analytics"

        # Test different word separators
        response = self.client.get(f"/api/projects/@current/feature_flags?search=web dash")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "web_dashboard" in matched_keys, f"Expected 'web_dashboard' in {matched_keys}"

        # Test single word still works
        response = self.client.get(f"/api/projects/@current/feature_flags?search=web")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}

        # Should match all web flags
        web_flags = {"web-analytics", "web_dashboard", "web analytics"}
        assert web_flags.issubset(matched_keys), f"Expected {web_flags} in {matched_keys}"
        assert "mobile-analytics" not in matched_keys

    def test_get_flags_with_search_exact_api_case(self):
        """Test the exact case from the user's API call: web%20ana should match web-analytics."""
        # Create the exact flag mentioned by the user
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="web-analytics", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="other-flag", active=True)

        # Test the exact API call pattern: search=web%20ana (which becomes "web ana")
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/?search=web ana&page=1&limit=100&offset=0"
        )
        data = response.json()

        # The search should find web-analytics
        assert response.status_code == 200
        assert "results" in data
        matched_keys = {result["key"] for result in data["results"]}
        assert "web-analytics" in matched_keys, f"Expected 'web-analytics' in {matched_keys}"

    def test_get_flags_with_search_trailing_space(self):
        """Test that search handles trailing spaces correctly by trimming them."""
        # Create flags to test with
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="web-analytics", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="mobile-app", active=True)

        # Test search with trailing space (URL encoded as "web%20")
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=web ")
        data = response.json()

        assert response.status_code == 200
        assert "results" in data
        matched_keys = {result["key"] for result in data["results"]}
        assert "web-analytics" in matched_keys, (
            f"Expected 'web-analytics' with trailing space search, got {matched_keys}"
        )
        assert "mobile-app" not in matched_keys

        # Test search with leading space
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search= web")
        data = response.json()

        assert response.status_code == 200
        matched_keys = {result["key"] for result in data["results"]}
        assert "web-analytics" in matched_keys, (
            f"Expected 'web-analytics' with leading space search, got {matched_keys}"
        )

        # Test search with both leading and trailing spaces
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search= web ")
        data = response.json()

        assert response.status_code == 200
        matched_keys = {result["key"] for result in data["results"]}
        assert "web-analytics" in matched_keys, f"Expected 'web-analytics' with surrounding spaces, got {matched_keys}"

    def test_get_flags_with_search_regex_metacharacters(self):
        """Test that search handles regex metacharacters safely by escaping them."""
        # Create flags to test regex escaping
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test.period.flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test-hyphen-flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test+plus+flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test*asterisk*flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test[bracket]flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test(paren)flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="test?question?flag", active=True)
        FeatureFlag.objects.create(team=self.team, created_by=self.user, key="unrelated-flag", active=True)

        # Test that periods are treated as literal characters, not regex wildcards
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=test.period")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "test.period.flag" in matched_keys, "Should find exact period match"
        assert "test-hyphen-flag" not in matched_keys, "Should not match hyphen when searching for period"

        # Test that plus signs are escaped (URL encode + as %2B)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=test%2Bplus")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "test+plus+flag" in matched_keys, "Should find exact plus match"

        # Test that asterisks are escaped (URL encode * as %2A)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=test%2Aasterisk")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "test*asterisk*flag" in matched_keys, "Should find exact asterisk match"

        # Test that brackets are escaped (URL encode [ and ] as %5B and %5D)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=test%5Bbracket%5D")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "test[bracket]flag" in matched_keys, "Should find exact bracket match"

        # Test that parentheses are escaped (URL encode ( and ) as %28 and %29)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=test%28paren%29")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "test(paren)flag" in matched_keys, "Should find exact parentheses match"

        # Test that question marks are escaped (URL encode ? as %3F)
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search=test%3Fquestion")
        data = response.json()
        matched_keys = {result["key"] for result in data["results"]}
        assert "test?question?flag" in matched_keys, "Should find exact question mark match"

    def test_get_flags_with_search_length_limit(self):
        """Test that search terms longer than 200 characters are rejected."""
        # Test with exactly 200 characters (should work)
        search_200 = "a" * 200
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search={search_200}")
        assert response.status_code == 200, "200-character search should be allowed"

        # Test with 201 characters (should fail)
        search_201 = "a" * 201
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/?search={search_201}")
        assert response.status_code == 400, "201-character search should be rejected"

        data = response.json()
        assert "Search term cannot exceed 200 characters" in str(data), "Should return appropriate error message"

    def test_get_flags_with_stale_filter(self):
        # Create a stale flag (100% rollout with no properties and 30+ days old)
        # No last_called_at so it falls back to config-based staleness detection
        with freeze_time("2024-01-01"):
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="stale_flag",
                active=True,
                filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
            )

        # Create a non-stale flag (100% rollout but recent)
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="recent_flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        # Create another non-stale flag (old but not 100% rollout)
        with freeze_time("2024-01-01"):
            partial_flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="partial_flag",
                active=True,
                filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
            )
        partial_flag.last_called_at = datetime.now(UTC) - timedelta(days=1)
        partial_flag.save()

        # Create a non-stale flag (100% rollout but has properties)
        with freeze_time("2024-01-01"):
            filtered_flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="filtered_flag",
                active=True,
                filters={
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "test@example.com",
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        }
                    ]
                },
            )
        filtered_flag.last_called_at = datetime.now(UTC) - timedelta(days=1)
        filtered_flag.save()

        # Create a non-stale flag (100% rollout but has multiple groups, with only 1 group that has 100% rollout)
        with freeze_time("2024-01-01"):
            multi_group_flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="filtered_flag_with_multiple_groups",
                active=True,
                filters={
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "email",
                                    "value": "test@example.com",
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                        },
                        {
                            "properties": [
                                {
                                    "key": "$browser_version",
                                    "value": ["136"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                            "rollout_percentage": 50,
                        },
                    ]
                },
            )
        multi_group_flag.last_called_at = datetime.now(UTC) - timedelta(days=1)
        multi_group_flag.save()

        # Test filtering by stale status
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?active=STALE")
        response = filtered_flags_list.json()

        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "stale_flag"
        assert response["results"][0]["status"] == "STALE"

    def test_get_flags_with_stale_filter_multivariate(self):
        # Create a stale multivariate flag (no last_called_at so it falls back to config-based detection)
        with freeze_time("2023-01-01"):
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="stale_multivariate",
                active=True,
                filters={
                    "groups": [{"rollout_percentage": 100, "properties": []}],
                    "multivariate": {
                        "variants": [
                            {"key": "test", "rollout_percentage": 100},
                        ],
                        "release_percentage": 100,
                    },
                },
            )

        # Create a non-stale multivariate flag (no variant at 100%)
        with freeze_time("2024-01-01"):
            active_flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="active_multivariate",
                active=True,
                filters={
                    "groups": [{"rollout_percentage": 50, "properties": []}],
                    "multivariate": {
                        "variants": [
                            {"key": "test", "rollout_percentage": 30},
                            {"key": "test2", "rollout_percentage": 70},
                        ]
                    },
                },
            )
        active_flag.last_called_at = datetime.now(UTC) - timedelta(days=1)
        active_flag.save()

        # Test filtering by stale status
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?active=STALE")
        response = filtered_flags_list.json()

        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "stale_multivariate"
        assert response["results"][0]["status"] == "STALE"

    def test_get_flags_with_stale_filter_multivariate_condition_variant_override(self):
        # Create a stale multivariate flag (no last_called_at so it falls back to config-based detection)
        with freeze_time("2023-01-01"):
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="stale_multivariate",
                active=True,
                filters={
                    "groups": [{"rollout_percentage": 100, "properties": [], "variant": "test"}],
                    "multivariate": {
                        "variants": [
                            {"key": "test", "rollout_percentage": 50},
                            {"key": "test2", "rollout_percentage": 50},
                        ],
                        "release_percentage": 100,
                    },
                },
            )

        # Create a multivariate flag with rollout <100% should not be stale
        with freeze_time("2023-01-01"):
            low_rollout_flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="low_rollout",
                active=True,
                filters={
                    "groups": [{"rollout_percentage": 90, "properties": [], "variant": "test"}],
                    "multivariate": {
                        "variants": [
                            {"key": "test", "rollout_percentage": 50},
                            {"key": "test2", "rollout_percentage": 50},
                        ],
                        "release_percentage": 100,
                    },
                },
            )
        low_rollout_flag.last_called_at = datetime.now(UTC) - timedelta(days=1)
        low_rollout_flag.save()

        # Create a multivariate flag with rollout 100% but has properties filter, should not be stale
        with freeze_time("2023-01-01"):
            with_props_flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="with_properties",
                active=True,
                filters={
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "$browser",
                                    "value": ["Chrome"],
                                    "operator": "exact",
                                    "type": "person",
                                }
                            ],
                            "variant": "test",
                        }
                    ],
                    "multivariate": {
                        "variants": [
                            {"key": "test", "rollout_percentage": 50},
                            {"key": "test2", "rollout_percentage": 50},
                        ],
                        "release_percentage": 100,
                    },
                },
            )
        with_props_flag.last_called_at = datetime.now(UTC) - timedelta(days=1)
        with_props_flag.save()

        # Test filtering by stale status
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?active=STALE")
        response = filtered_flags_list.json()

        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "stale_multivariate"
        assert response["results"][0]["status"] == "STALE"

    def test_get_flags_with_stale_filter_explicit_multivariate_null(self):
        # Regression test: flags created via frontend have explicit multivariate: null
        # The SQL filter should handle both missing key AND explicit null value
        # No last_called_at so it falls back to config-based detection
        with freeze_time("2024-01-01"):
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key="stale_with_explicit_null",
                active=True,
                filters={
                    "groups": [{"rollout_percentage": 100, "properties": []}],
                    "multivariate": None,  # Frontend explicitly sets this to null
                    "payloads": {},
                },
            )

        # Create a non-stale flag with explicit multivariate: null (recent)
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="recent_with_explicit_null",
            active=True,
            filters={
                "groups": [{"rollout_percentage": 100, "properties": []}],
                "multivariate": None,
                "payloads": {},
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        filtered_flags_list = self.client.get("/api/projects/@current/feature_flags?active=STALE")
        response = filtered_flags_list.json()

        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "stale_with_explicit_null"
        assert response["results"][0]["status"] == "STALE"

    @parameterized.expand(
        [
            (
                "json_null_variant",
                {
                    "groups": [{"rollout_percentage": 100, "properties": [], "variant": None}],
                    "multivariate": {
                        "variants": [
                            {"key": "test", "rollout_percentage": 50},
                            {"key": "test2", "rollout_percentage": 50},
                        ],
                    },
                },
                False,  # JSON null variant is not a real override, should not be stale
            ),
            (
                "empty_multivariate_object",
                {
                    "groups": [{"rollout_percentage": 100, "properties": []}],
                    "multivariate": {},
                },
                True,  # empty multivariate {} should be treated like no multivariate
            ),
        ]
    )
    def test_get_flags_with_stale_filter_jsonb_edge_cases(self, flag_key, flag_filters, expect_stale):
        with freeze_time("2023-01-01"):
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=flag_key,
                active=True,
                filters=flag_filters,
            )

        response = self.client.get("/api/projects/@current/feature_flags?active=STALE").json()
        is_in_results = any(f["key"] == flag_key for f in response["results"])
        assert is_in_results == expect_stale

    def test_get_flags_with_evaluation_runtime_filter(self):
        # Create flags with different evaluation runtimes
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="server_flag",
            evaluation_runtime="server",
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="client_flag",
            evaluation_runtime="client",
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="all_flag",
            evaluation_runtime="all",
        )

        # Test filtering by server environment
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?evaluation_runtime=server")
        response = filtered_flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "server_flag"

        # Test filtering by client environment
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?evaluation_runtime=client")
        response = filtered_flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "client_flag"

        # Test filtering by all environment
        filtered_flags_list = self.client.get(f"/api/projects/@current/feature_flags?evaluation_runtime=all")
        response = filtered_flags_list.json()
        assert len(response["results"]) == 1
        assert response["results"][0]["key"] == "all_flag"

    @patch("django.db.transaction.on_commit", side_effect=lambda func: func())
    def test_flag_is_cached_on_create_and_update(self, mock_on_commit):
        # Ensure empty feature flag list
        FeatureFlag.objects.all().delete()

        feature_flag = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "name": "Beta feature",
                "key": "beta-feature",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [{"rollout_percentage": 65}],
                },
            },
            format="json",
        ).json()

        flags = get_feature_flags_for_team_in_cache(self.team.id)

        assert flags is not None
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].id, feature_flag["id"])
        self.assertEqual(flags[0].key, "beta-feature")
        self.assertEqual(flags[0].name, "Beta feature")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag['id']}",
            {"name": "XYZ", "key": "red_button"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flags = get_feature_flags_for_team_in_cache(self.team.id)

        assert flags is not None
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].id, feature_flag["id"])
        self.assertEqual(flags[0].key, "red_button")
        self.assertEqual(flags[0].name, "XYZ")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag['id']}",
            {"deleted": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flags = get_feature_flags_for_team_in_cache(self.team.id)

        assert flags is not None
        self.assertEqual(len(flags), 0)

    def test_feature_flag_dashboard(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        relationship = FeatureFlagDashboards.objects.create(
            feature_flag=another_feature_flag, dashboard_id=dashboard.pk
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()

        self.assertEqual(len(response_json["analytics_dashboards"]), 1)

        # check deleting the dashboard doesn't delete flag, but deletes the relationship
        dashboard.delete()
        another_feature_flag.refresh_from_db()

        with self.assertRaises(FeatureFlagDashboards.DoesNotExist):
            relationship.refresh_from_db()

    def test_feature_flag_dashboard_patch(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk),
            {"analytics_dashboards": [dashboard.pk]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()

        self.assertEqual(len(response_json["analytics_dashboards"]), 1)

    def test_feature_flag_dashboard_already_exists(self):
        another_feature_flag = FeatureFlag.objects.create(
            team=self.team,
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )
        dashboard = Dashboard.objects.create(team=self.team, name="private dashboard", created_by=self.user)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk),
            {"analytics_dashboards": [dashboard.pk]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/" + str(another_feature_flag.pk),
            {"analytics_dashboards": [dashboard.pk]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()

        self.assertEqual(len(response_json["analytics_dashboards"]), 1)

    @freeze_time("2021-01-01")
    @snapshot_clickhouse_queries
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_creating_static_cohort(self, mock_batch_evaluate):
        flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
                "multivariate": None,
            },
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )

        person1 = _create_person(
            team=self.team,
            distinct_ids=[f"person1"],
            properties={"key": "value"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person2"],
            properties={"key": "value2"},
        )
        _create_person(
            team=self.team,
            distinct_ids=[f"person3"],
            properties={"key2": "value3"},
        )
        flush_persons_and_events()

        mock_batch_evaluate.return_value = {
            "matched_person_uuids": [str(person1.uuid)],
            "next_cursor": None,
            "errors_count": 0,
        }

        with (
            snapshot_postgres_queries_context(self),
            self.settings(
                CELERY_TASK_ALWAYS_EAGER=True,
                PERSON_ON_EVENTS_OVERRIDE=False,
                PERSON_ON_EVENTS_V2_OVERRIDE=False,
            ),
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/{flag.id}/create_static_cohort_for_flag",
                {},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # fires an async task for computation, but celery runs sync in tests
        cohort_id = response.json()["cohort"]["id"]
        cohort = Cohort.objects.get(id=cohort_id)
        self.assertEqual(
            cohort.name,
            "Users with feature flag some-feature enabled at 2021-01-01 00:00:00",
        )
        self.assertEqual(cohort.count, 1)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 1, response)

    def test_cant_update_early_access_flag_with_group(self):
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            filters={
                "aggregation_group_type_index": None,
                "groups": [{"properties": [], "rollout_percentage": None}],
            },
            name="some feature",
            key="some-feature",
            created_by=self.user,
        )

        EarlyAccessFeature.objects.create(
            team=self.team,
            name="earlyAccessFeature",
            description="early access feature",
            stage="alpha",
            feature_flag=feature_flag,
        )

        update_data = {
            "filters": {
                "aggregation_group_type_index": 2,
                "groups": [{"properties": [], "rollout_percentage": 100}],
            }
        }
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag.id}/",
            update_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Cannot use group aggregation in any condition set when the flag is linked to an Early Access Feature.",
            }.items(),
            response.json().items(),
        )

    def test_feature_flag_includes_cohort_names(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="test_cohort",
            groups=[{"properties": [{"key": "email", "value": "@posthog.com", "type": "person"}]}],
        )
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Alpha feature",
                "key": "alpha-feature",
                "filters": {
                    "groups": [{"properties": [{"key": "id", "type": "cohort", "value": cohort.pk}]}],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Get the flag
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/{response.json()['id']}/",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["filters"]["groups"][0]["properties"][0],
            {
                "key": "id",
                "type": "cohort",
                "value": cohort.pk,
                "cohort_name": "test_cohort",
            },
        )

    def test_feature_flag_includes_group_key_names(self):
        create_group_type_mapping(
            team=self.team, project_id=self.team.project_id, group_type="organization", group_type_index=0
        )
        create_test_group(
            team=self.team,
            group_key="org-uuid-1",
            group_type_index=0,
            group_properties={"name": "Acme Corp"},
            version=0,
        )
        create_test_group(
            team=self.team,
            group_key="org-uuid-2",
            group_type_index=0,
            group_properties={"name": "Widget Inc"},
            version=0,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Group flag",
                "key": "group-flag",
                "filters": {
                    "aggregation_group_type_index": 0,
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "$group_key",
                                    "type": "group",
                                    "value": ["org-uuid-1", "org-uuid-2"],
                                    "operator": "exact",
                                    "group_type_index": 0,
                                }
                            ]
                        }
                    ],
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/{response.json()['id']}/",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        prop = response.json()["filters"]["groups"][0]["properties"][0]
        self.assertEqual(prop["key"], "$group_key")
        self.assertEqual(
            prop["group_key_names"],
            {"org-uuid-1": "Acme Corp", "org-uuid-2": "Widget Inc"},
        )

    def test_create_feature_flag_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            data={
                "key": "my-test-flag-in-folder",
                "name": "Test Flag in Folder",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
                "_create_in_folder": "Special Folder/Flags",
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        flag_id = response.json()["id"]
        assert flag_id is not None

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(flag_id), type="feature_flag").first()
        assert fs_entry, "No FileSystem entry found for this feature flag."
        assert "Special Folder/Flags" in fs_entry.path, (
            f"Expected 'Special Folder/Flags' in path, got: '{fs_entry.path}'"
        )

    def test_feature_flag_experiment_set(self):
        # Create a feature flag
        feature_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test-flag",
            name="Test Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Initially, experiment_set should be empty
        response = self.client.get(f"/api/projects/@current/feature_flags/{feature_flag.id}")
        assert response.status_code == 200
        assert response.json()["experiment_set"] == []

        # Create an active experiment linked to the flag
        experiment = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Test Experiment",
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
        )

        # experiment_set should now include the experiment ID
        response = self.client.get(f"/api/projects/@current/feature_flags/{feature_flag.id}")
        assert response.status_code == 200
        assert response.json()["experiment_set"] == [experiment.id]

        # Create a deleted experiment - should not be included
        experiment2 = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Another Experiment",
            feature_flag=feature_flag,
            start_date=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC),
        )

        # experiment_set should include both experiments
        response = self.client.get(f"/api/projects/@current/feature_flags/{feature_flag.id}")
        assert response.status_code == 200
        assert response.json()["experiment_set"] == [experiment.id, experiment2.id]

        # Delete the active experiments
        experiment.deleted = True
        experiment.save()
        experiment2.deleted = True
        experiment2.save()

        # experiment_set should now be empty again
        response = self.client.get(f"/api/projects/@current/feature_flags/{feature_flag.id}")
        assert response.status_code == 200
        assert response.json()["experiment_set"] == []

    def test_feature_flag_experiment_set_metadata_includes_running_status(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="metadata-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        running = Experiment.objects.create(
            team=self.team, created_by=self.user, name="Running", feature_flag=flag, start_date=now()
        )
        stopped = Experiment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Stopped",
            feature_flag=flag,
            start_date=now() - timedelta(days=1),
            end_date=now(),
        )
        draft = Experiment.objects.create(team=self.team, created_by=self.user, name="Draft", feature_flag=flag)

        response = self.client.get(f"/api/projects/@current/feature_flags/{flag.id}")
        assert response.status_code == 200
        # Only a running experiment is flagged as such; the frontend uses this to gate flag deletion
        running_by_id = {exp["id"]: exp["is_running"] for exp in response.json()["experiment_set_metadata"]}
        assert running_by_id == {running.id: True, stopped.id: False, draft.id: False}

    def test_bulk_keys_valid_ids(self):
        """Test that valid IDs return correct key mapping"""
        # Create test flags
        flag1 = FeatureFlag.objects.create(key="test-flag-1", name="Test Flag 1", team=self.team, created_by=self.user)
        flag2 = FeatureFlag.objects.create(key="test-flag-2", name="Test Flag 2", team=self.team, created_by=self.user)
        flag3 = FeatureFlag.objects.create(key="test-flag-3", name="Test Flag 3", team=self.team, created_by=self.user)

        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": [flag1.id, flag2.id, flag3.id]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "keys" in data
        assert data["keys"] == {
            str(flag1.id): "test-flag-1",
            str(flag2.id): "test-flag-2",
            str(flag3.id): "test-flag-3",
        }

    def test_bulk_keys_empty_list(self):
        """Test that empty ID list returns empty keys object"""
        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": []},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {"keys": {}}

    def test_bulk_keys_invalid_ids(self):
        """Test that invalid IDs (non-integers) return error"""
        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": ["invalid", "not-a-number"]},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        data = response.json()
        assert "error" in data
        assert "Invalid flag IDs provided" in data["error"]

    def test_bulk_keys_mixed_valid_invalid_ids(self):
        """Test that mixed valid/invalid IDs filter out invalid ones"""
        flag1 = FeatureFlag.objects.create(key="test-flag-1", name="Test Flag 1", team=self.team, created_by=self.user)

        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": [flag1.id, "invalid", 99999]},  # valid ID, invalid string, non-existent ID
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "keys" in data
        assert data["keys"] == {str(flag1.id): "test-flag-1"}
        assert "warning" in data
        assert "Invalid flag IDs ignored: ['invalid']" in data["warning"]

    def test_bulk_keys_nonexistent_ids(self):
        """Test that non-existent flag IDs are filtered out"""
        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": [99999, 88888]},  # Non-existent IDs
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {"keys": {}}

    def test_bulk_keys_team_isolation(self):
        """Test that flags from other teams are not returned"""
        # Create flag in current team
        flag1 = FeatureFlag.objects.create(
            key="current-team-flag",
            name="Current Team Flag",
            team=self.team,
            created_by=self.user,
        )

        # Create another team and flag
        other_user = User.objects.create_user(email="other@test.com", password="password", first_name="Other")
        other_organization, _, other_team = Organization.objects.bootstrap(other_user)
        flag2 = FeatureFlag.objects.create(
            key="other-team-flag",
            name="Other Team Flag",
            team=other_team,
            created_by=other_user,
        )

        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": [flag1.id, flag2.id]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "keys" in data
        # Should only return flag from current team
        assert data["keys"] == {str(flag1.id): "current-team-flag"}

    def test_bulk_keys_deleted_flags(self):
        """Test that deleted flags are not returned"""
        flag1 = FeatureFlag.objects.create(key="active-flag", name="Active Flag", team=self.team, created_by=self.user)
        flag2 = FeatureFlag.objects.create(
            key="deleted-flag",
            name="Deleted Flag",
            team=self.team,
            created_by=self.user,
            deleted=True,
        )

        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": [flag1.id, flag2.id]},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "keys" in data
        # Should only return non-deleted flag
        assert data["keys"] == {str(flag1.id): "active-flag"}

    def test_bulk_keys_no_ids_param(self):
        """Test that missing 'ids' parameter returns empty keys object"""
        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {},  # No 'ids' parameter
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data == {"keys": {}}

    def test_bulk_keys_string_ids(self):
        """Test that string representations of valid IDs work"""
        flag1 = FeatureFlag.objects.create(key="test-flag-1", name="Test Flag 1", team=self.team, created_by=self.user)

        response = self.client.post(
            f"/api/projects/@current/feature_flags/bulk_keys/",
            {"ids": [str(flag1.id)]},  # String ID instead of integer
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "keys" in data
        assert data["keys"] == {str(flag1.id): "test-flag-1"}

    @patch("products.feature_flags.backend.api.feature_flag.report_user_action")
    def test_create_feature_flag_without_usage_dashboard(self, mock_report_user_action):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {"key": "no-usage-dashboard", "_should_create_usage_dashboard": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["key"], "no-usage-dashboard")
        self.assertEqual(response.json()["name"], "")
        instance = FeatureFlag.objects.get(id=response.json()["id"])
        self.assertEqual(instance.key, "no-usage-dashboard")
        self.assertEqual(instance.name, "")
        assert instance.usage_dashboard is None, "Usage dashboard should not be created"

    def test_feature_flag_detail_actions_respect_access_control(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        user2 = self._create_user("test2@posthog.com", level=OrganizationMembership.Level.MEMBER)

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            name="secret flag",
            key="secret-flag",
        )
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")

        self.client.force_login(user2)

        retrieve_response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/")
        self.assertEqual(retrieve_response.status_code, status.HTTP_403_FORBIDDEN)

        activity_response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/activity/")
        self.assertEqual(activity_response.status_code, status.HTTP_403_FORBIDDEN)

        status_response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/status/")
        self.assertEqual(status_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_org_admin_can_list_flag_with_default_none_after_grantee_removed(self) -> None:
        # Regression: a flag with a team-wide "none" default plus a single explicit
        # editor grant becomes invisible to everyone once the grantee is removed
        # from the org (their AccessControl row cascade-deletes). Org admins should
        # still be able to find such orphaned flags in the list endpoint.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        creator = self._create_user("creator@posthog.com", level=OrganizationMembership.Level.MEMBER)
        grantee = self._create_user("grantee@posthog.com", level=OrganizationMembership.Level.MEMBER)
        grantee_membership = grantee.organization_memberships.get(organization=self.organization)

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=creator,
            name="orphaned flag",
            key="orphaned-flag",
        )
        # Team-wide "no access" default for this flag
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")
        # Single explicit editor grant for the grantee
        AccessControl.objects.create(
            resource="feature_flag",
            resource_id=flag.id,
            team=self.team,
            organization_member=grantee_membership,
            access_level="editor",
        )

        # self.user is the org admin via APIBaseTest setup
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Remove the grantee from the org -> cascade deletes their explicit grant
        grantee_membership.delete()

        # Org admin must still see the flag in the list (it's an orphaned flag now)
        list_response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        keys = [f["key"] for f in list_response.json()["results"]]
        self.assertIn("orphaned-flag", keys)

    def test_member_still_blocked_from_listing_default_none_flag(self) -> None:
        # Counterpart to the test above: non-admin members without an explicit
        # grant must still be filtered out by the per-object "none" default.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        other = self._create_user("other@posthog.com", level=OrganizationMembership.Level.MEMBER)

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            name="blocked flag",
            key="blocked-flag",
        )
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")

        self.client.force_login(other)
        list_response = self.client.get(f"/api/projects/{self.team.pk}/feature_flags/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        keys = [f["key"] for f in list_response.json()["results"]]
        self.assertNotIn("blocked-flag", keys)

    @parameterized.expand(
        [
            ("create",),
            ("rename",),
        ]
    )
    def test_reuses_key_held_by_legacy_soft_deleted_flag_with_soft_deleted_experiment(self, mode: str):
        # Legacy tombstone holds the key with a soft-deleted experiment FK
        # blocking hard-delete. Reusing the key should rename the tombstone,
        # not raise the old "delete the experiment" error.
        legacy_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="ghost-key")
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=legacy_flag)
        exp.deleted = True
        exp.save()
        # Bypass API so soft-delete rename doesn't fire — mimics historical data.
        FeatureFlag.objects_including_soft_deleted.filter(pk=legacy_flag.pk).update(deleted=True)

        if mode == "create":
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "Ghost", "key": "ghost-key"},
            )
            assert response.status_code == 201, response.content
            assert response.json()["key"] == "ghost-key"
        else:
            other = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="ghost-key-v2")
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{other.id}/",
                {"key": "ghost-key"},
            )
            assert response.status_code == 200, response.content
            other.refresh_from_db()
            assert other.key == "ghost-key"

        # Tombstone is renamed; experiment FK still resolves.
        legacy_flag = FeatureFlag.objects_including_soft_deleted.get(pk=legacy_flag.pk)
        assert legacy_flag.deleted is True
        assert legacy_flag.key == f"ghost-key:deleted:{legacy_flag.id}"
        exp.refresh_from_db()
        assert exp.feature_flag_id == legacy_flag.id

    @parameterized.expand(
        [
            ("create",),
            ("rename",),
        ]
    )
    def test_reuse_key_with_inconsistent_soft_deleted_flag_referenced_by_active_experiment(self, mode: str):
        # If a tombstone is still referenced by an active experiment (invariant
        # violation), renaming it would silently break the experiment. Error out.
        legacy_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="inconsistent-key")
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=legacy_flag)
        FeatureFlag.objects_including_soft_deleted.filter(pk=legacy_flag.pk).update(deleted=True)

        if mode == "create":
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "Inconsistent", "key": "inconsistent-key"},
            )
        else:
            other = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="inconsistent-key-v2")
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{other.id}/",
                {"key": "inconsistent-key"},
            )

        assert response.status_code == 400
        assert f"active experiment(s) with ID(s): {exp.id}" in response.json()["detail"]
        assert "inconsistent-key" in response.json()["detail"]

        # Tombstone was not mutated.
        legacy_flag.refresh_from_db()
        assert legacy_flag.key == "inconsistent-key"

    @parameterized.expand(
        [
            ("create",),
            ("rename",),
        ]
    )
    def test_reuse_key_with_inconsistent_soft_deleted_flag_referenced_by_eaf(self, mode: str):
        # EarlyAccessFeature.feature_flag uses on_delete=PROTECT (sibling of
        # RESTRICT). A tombstone with an EAF must surface the same defensive
        # error, not a 500.
        legacy_flag = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="eaf-key")
        EarlyAccessFeature.objects.create(
            team=self.team,
            name="EAF",
            description="",
            stage="alpha",
            feature_flag=legacy_flag,
        )
        FeatureFlag.objects_including_soft_deleted.filter(pk=legacy_flag.pk).update(deleted=True)

        if mode == "create":
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/",
                {"name": "EAF Reuse", "key": "eaf-key"},
            )
        else:
            other = FeatureFlag.objects.create(team=self.team, created_by=self.user, key="eaf-key-v2")
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{other.id}/",
                {"key": "eaf-key"},
            )

        assert response.status_code == 400
        assert "early access feature(s)" in response.json()["detail"]
        assert "eaf-key" in response.json()["detail"]

        legacy_flag.refresh_from_db()
        assert legacy_flag.key == "eaf-key"

    def test_cant_create_flag_with_invalid_regex(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "[unclosed",
                                    "operator": "regex",
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "groups[0].properties[0].value: invalid regex pattern")

    def test_cant_create_flag_with_invalid_not_regex(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "group",
                                    "group_type_index": 0,
                                    "value": "(unclosed",
                                    "operator": "not_regex",
                                }
                            ],
                        }
                    ],
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "groups[0].properties[0].value: invalid regex pattern")

    def test_patch_non_filter_field_skips_regex_validation(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="flag-with-lookbehind",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": "(?<!a{2,5})b",
                                "operator": "regex",
                            }
                        ],
                    }
                ]
            },
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}",
            {"active": False},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @parameterized.expand(
        [
            (
                "unchanged_invalid_regex_accepted",
                "(?<!a{2,5})b",
                "(?<!a{2,5})b",
                status.HTTP_200_OK,
            ),
            (
                "valid_to_invalid_regex_rejected",
                "^valid$",
                "[unclosed",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                "different_invalid_regex_rejected",
                "[unclosed",
                "(unbalanced",
                status.HTTP_400_BAD_REQUEST,
            ),
        ]
    )
    def test_patch_flag_regex_validation(self, _name, existing_pattern, new_pattern, expected_status):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="flag-regex-test",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {
                                "key": "email",
                                "type": "person",
                                "value": existing_pattern,
                                "operator": "regex",
                            }
                        ],
                    }
                ]
            },
        )
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}",
            {
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 100,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": new_pattern,
                                    "operator": "regex",
                                }
                            ],
                        }
                    ]
                }
            },
        )
        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.assertEqual(response.json()["detail"], "groups[0].properties[0].value: invalid regex pattern")

    def test_cant_create_flag_with_non_string_regex_value(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": 123,
                                    "operator": "regex",
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid value for operator regex: 123")

    def test_can_create_flag_with_valid_regex(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {
                "name": "Beta feature",
                "key": "beta-x",
                "filters": {
                    "groups": [
                        {
                            "rollout_percentage": 65,
                            "properties": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "^[a-z]+@posthog\\.com$",
                                    "operator": "regex",
                                }
                            ],
                        }
                    ]
                },
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        saved = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{response.json()['id']}").json()
        self.assertEqual(saved["filters"]["groups"][0]["properties"][0]["value"], "^[a-z]+@posthog\\.com$")

    @parameterized.expand(
        [
            ("python_valid_pg_invalid_persons", "person", None, "2.3.9{0-9}{1}"),
            ("python_valid_pg_invalid_groups", "group", 1, "2.3.9{0-9}{1 ef}"),
        ]
    )
    def test_can_create_flag_with_postgres_incompatible_regex(self, _name, prop_type, group_type_index, pattern):
        if prop_type == "group":
            create_group_type_mapping_without_created_at(
                team=self.team,
                project_id=self.team.project_id,
                group_type="xyz",
                group_type_index=group_type_index,
            )
        prop = {"key": "email", "type": prop_type, "value": pattern, "operator": "regex"}
        if group_type_index is not None:
            prop["group_type_index"] = group_type_index
        filters: dict = {"groups": [{"rollout_percentage": 65, "properties": [prop]}]}
        if group_type_index is not None:
            filters["aggregation_group_type_index"] = group_type_index
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            {"name": "Beta feature", "key": f"beta-{prop_type}", "filters": filters},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        saved = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{response.json()['id']}").json()
        self.assertEqual(saved["filters"]["groups"][0]["properties"][0]["value"], pattern)

    def test_bulk_keys_works_with_personal_api_key(self):
        """Once enabled as MCP tool with feature_flag:read scope, PAT requests must succeed."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="pat-scope-test",
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            scopes=["feature_flag:read"],
            secure_value=hash_key_value(personal_api_key),
        )
        self.client.logout()
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_keys/",
            {"ids": [flag.id]},
            format="json",
            headers={"authorization": f"Bearer {personal_api_key}"},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"keys": {str(flag.id): "pat-scope-test"}}

    def test_bulk_update_tags_works_with_personal_api_key(self):
        """Same scope-config bug on bulk_update_tags; same fix in tagged_item.py."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="pat-tag-test",
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            scopes=["feature_flag:write"],
            secure_value=hash_key_value(personal_api_key),
        )
        self.client.logout()
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_update_tags/",
            {"ids": [flag.id], "action": "add", "tags": ["foo"]},
            format="json",
            headers={"authorization": f"Bearer {personal_api_key}"},
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        # Pin the body so a regression that grants the PAT scope but loses the
        # mutation (broken preload_object_access_controls, wrong scope_object,
        # etc.) can't stay green: the endpoint returns 200 with the flag in
        # `skipped` rather than a non-2xx status when ACLs drop it.
        body = response.json()
        assert body["updated"] == [{"id": flag.id, "tags": ["foo"]}]
        assert body["skipped"] == []

    # Lives in the feature-flag test file (instead of test_insight.py) so the
    # full bulk-ops PAT regression story — positive feature-flag cases and the
    # negative cross-resource block — stays adjacent for reviewers of #57885.
    def test_feature_flag_write_pat_cannot_mutate_insight_tags(self):
        """A feature_flag:write PAT must not reach Insight.bulk_update_tags via the shared mixin."""
        insight = Insight.objects.create(team=self.team, name="x", created_by=self.user)
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            scopes=["feature_flag:write"],
            secure_value=hash_key_value(personal_api_key),
        )
        self.client.logout()
        response = self.client.post(
            f"/api/projects/{self.team.id}/insights/bulk_update_tags/",
            {"ids": [insight.id], "action": "add", "tags": ["foo"]},
            format="json",
            headers={"authorization": f"Bearer {personal_api_key}"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def test_member_still_blocked_from_bulk_keys_default_none_flag(self) -> None:
        # bulk_keys must not leak keys for flags the user has been explicitly
        # denied, even when the caller submits the ID directly.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        other = self._create_user("other-bulk-keys@posthog.com", level=OrganizationMembership.Level.MEMBER)

        visible_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            name="visible flag",
            key="visible-flag",
        )
        blocked_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            name="blocked flag",
            key="blocked-flag",
        )
        AccessControl.objects.create(
            resource="feature_flag", resource_id=blocked_flag.id, team=self.team, access_level="none"
        )

        self.client.force_login(other)
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/bulk_keys/",
            {"ids": [visible_flag.id, blocked_flag.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        keys = response.json()["keys"]
        self.assertEqual(keys.get(str(visible_flag.id)), "visible-flag")
        self.assertNotIn(str(blocked_flag.id), keys)

    def test_member_with_explicit_viewer_grant_can_bulk_keys_default_none_flag(self) -> None:
        # Inverse of the test above — exercises the allowed_resource_ids branch
        # of filter_queryset_by_access_level: a flag with a team-wide "none"
        # default plus an explicit viewer grant for this member must round-trip.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        grantee = self._create_user("grantee-bulk-keys@posthog.com", level=OrganizationMembership.Level.MEMBER)
        grantee_membership = grantee.organization_memberships.get(organization=self.organization)

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            name="granted flag",
            key="granted-flag",
        )
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")
        AccessControl.objects.create(
            resource="feature_flag",
            resource_id=flag.id,
            team=self.team,
            organization_member=grantee_membership,
            access_level="viewer",
        )

        self.client.force_login(grantee)
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/bulk_keys/",
            {"ids": [flag.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["keys"].get(str(flag.id)), "granted-flag")

    def test_org_admin_can_bulk_keys_default_none_flag(self) -> None:
        # Exercises the include_all_if_admin=True short-circuit: org admins must
        # be able to resolve keys for flags with a team-wide "none" default,
        # matching the list endpoint's behavior for feature_flag.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        creator = self._create_user("creator-bulk-keys@posthog.com", level=OrganizationMembership.Level.MEMBER)
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=creator,
            name="default-none flag",
            key="default-none-flag",
        )
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/bulk_keys/",
            {"ids": [flag.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["keys"].get(str(flag.id)), "default-none-flag")

    def test_member_blocked_from_bulk_keys_via_explicit_deny_on_individual_flag(self) -> None:
        # Exercises the exclude() branch of filter_queryset_by_access_level
        # (user_access_control.py line 937): the team-wide default is permissive
        # (no resource-level "none" row), but this flag carries an explicit
        # "none" ACL for the caller's membership. bulk_keys must still drop it.
        # The existing IDOR tests all hit the filter() branch (line 931) via a
        # team-wide deny; without this case, a regression that only handled
        # team-wide denies would ship clean.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        other = self._create_user("other-explicit-deny@posthog.com", level=OrganizationMembership.Level.MEMBER)
        other_membership = other.organization_memberships.get(organization=self.organization)

        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            name="explicit deny flag",
            key="explicit-deny-flag",
        )
        AccessControl.objects.create(
            resource="feature_flag",
            resource_id=flag.id,
            team=self.team,
            organization_member=other_membership,
            access_level="none",
        )

        self.client.force_login(other)
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/bulk_keys/",
            {"ids": [flag.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(str(flag.id), response.json()["keys"])

    def test_creator_still_sees_denied_flag_in_bulk_keys(self) -> None:
        # filter_queryset_by_access_level deliberately preserves
        # Q(created_by=self._user) in both branches (user_access_control.py
        # lines 931 and 937), so creators retain visibility of their own flags
        # even with a deny ACL. This mirrors the list endpoint's contract.
        # Pinning it so a future "harden the IDOR fix" patch can't silently
        # strip the creator clause and diverge bulk_keys from list.
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

        creator = self._create_user("creator-self@posthog.com", level=OrganizationMembership.Level.MEMBER)
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=creator,
            name="self-created flag",
            key="self-created-flag",
        )
        AccessControl.objects.create(resource="feature_flag", resource_id=flag.id, team=self.team, access_level="none")

        self.client.force_login(creator)
        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/bulk_keys/",
            {"ids": [flag.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["keys"].get(str(flag.id)), "self-created-flag")


class TestCohortGenerationForFeatureFlag(APIBaseTest, ClickhouseTestMixin):
    """
    Orchestration tests for get_cohort_actors_for_feature_flag with the Rust batch
    evaluation HTTP client mocked. Evaluation correctness lives in the Rust service's
    own test suite (rust/feature-flags/tests/test_batch_flag_evaluation.rs).
    """

    def _create_flag(self, key: str = "some-feature", **kwargs) -> FeatureFlag:
        defaults: dict = {
            "team": self.team,
            "filters": {
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "person"}]}],
                "multivariate": None,
            },
            "name": "some feature",
            "key": key,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return FeatureFlag.objects.create(**defaults)

    def _create_static_cohort(self) -> Cohort:
        return Cohort.objects.create(team=self.team, is_static=True, name="some cohort")

    @staticmethod
    def _page(uuids: list[str], next_cursor: int | None = None, errors_count: int = 0) -> dict:
        return {"matched_person_uuids": uuids, "next_cursor": next_cursor, "errors_count": errors_count}

    @staticmethod
    def _metric(name: str, **labels: str) -> float:
        # Metrics are process-global, so tests assert deltas against a before-value.
        return REGISTRY.get_sample_value(name, labels or None) or 0.0

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_deleted_flag_returns_empty_without_calling_service(self, mock_batch_evaluate):
        self._create_flag(deleted=True)
        cohort = self._create_static_cohort()

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        mock_batch_evaluate.assert_not_called()
        cohort.refresh_from_db()
        # don't even try inserting anything, because invalid flag, so None instead of 0
        self.assertEqual(cohort.count, None)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_inactive_flag_returns_empty_without_calling_service(self, mock_batch_evaluate):
        self._create_flag(active=False)
        cohort = self._create_static_cohort()

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        mock_batch_evaluate.assert_not_called()
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, None)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_group_flag_returns_empty_without_calling_service(self, mock_batch_evaluate):
        self._create_flag(
            filters={
                "groups": [{"properties": [{"key": "key", "value": "value", "type": "group", "group_type_index": 1}]}],
                "multivariate": None,
                "aggregation_group_type_index": 1,
            }
        )
        cohort = self._create_static_cohort()

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        mock_batch_evaluate.assert_not_called()
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, None)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_non_existing_flag_returns_empty_without_calling_service(self, mock_batch_evaluate):
        cohort = self._create_static_cohort()

        get_cohort_actors_for_feature_flag(cohort.pk, "does-not-exist", self.team.pk)

        mock_batch_evaluate.assert_not_called()
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, None)

    @parameterized.expand(
        [
            ("inactive_flag", {"active": False}),
            (
                "group_aggregated_flag",
                {
                    "filters": {
                        "groups": [
                            {"properties": [{"key": "key", "value": "value", "type": "group", "group_type_index": 1}]}
                        ],
                        "multivariate": None,
                        "aggregation_group_type_index": 1,
                    }
                },
            ),
            ("missing_flag", None),
        ]
    )
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_guard_paths_clear_is_calculating(self, _name, flag_kwargs, mock_batch_evaluate):
        # The enqueue site sets is_calculating=True before dispatching, so every guard
        # exit must clear it rather than leave the cohort stuck. Each branch has its own
        # _safe_save_cohort_state call: the missing-flag exit (except FeatureFlag.DoesNotExist)
        # is separate from the combined inactive / group-aggregated branch.
        if flag_kwargs is not None:
            self._create_flag(**flag_kwargs)
        cohort = self._create_static_cohort()
        cohort.is_calculating = True
        cohort.save(update_fields=["is_calculating"])

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        mock_batch_evaluate.assert_not_called()
        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_matched_persons_are_added_to_cohort(self, mock_batch_evaluate):
        self._create_flag()
        p1 = _create_person(team=self.team, distinct_ids=["person1"], properties={"key": "value"}, immediate=True)
        p2 = _create_person(team=self.team, distinct_ids=["person2"], properties={"key": "value"}, immediate=True)
        _create_person(team=self.team, distinct_ids=["person3"], properties={}, immediate=True)
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.return_value = self._page([str(p1.uuid), str(p2.uuid)])

        completed_before = self._metric("cohort_flag_generation_completed_total", outcome="success")
        duration_count_before = self._metric("cohort_flag_generation_duration_seconds_count", outcome="success")

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        self.assertEqual(
            self._metric("cohort_flag_generation_completed_total", outcome="success"), completed_before + 1
        )
        self.assertEqual(
            self._metric("cohort_flag_generation_duration_seconds_count", outcome="success"),
            duration_count_before + 1,
        )
        mock_batch_evaluate.assert_called_once_with(
            team_id=self.team.pk,
            project_id=self.team.project_id,
            flag_key="some-feature",
            expected_version=1,
            cursor=0,
            limit=1_000,
        )
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 2)
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 2, response)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_flag_matching_nobody_finalizes_empty_cohort(self, mock_batch_evaluate):
        self._create_flag()
        cohort = self._create_static_cohort()

        # The final flush is unconditional precisely so a zero-match run still recomputes
        # count to 0 and clears is_calculating, instead of leaving the cohort stuck.
        mock_batch_evaluate.return_value = self._page([])

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        mock_batch_evaluate.assert_called_once()
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 0)
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 0)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_cursor_loop_advances_and_terminates(self, mock_batch_evaluate):
        self._create_flag()
        persons = [
            _create_person(team=self.team, distinct_ids=[f"person{i}"], properties={"key": "value"}, immediate=True)
            for i in range(3)
        ]
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.side_effect = [
            self._page([str(persons[0].uuid)], next_cursor=100),
            self._page([str(persons[1].uuid)], next_cursor=200),
            self._page([str(persons[2].uuid)], next_cursor=None),
        ]

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk, batchsize=2)

        self.assertEqual(mock_batch_evaluate.call_count, 3)
        cursors = [call.kwargs["cursor"] for call in mock_batch_evaluate.call_args_list]
        self.assertEqual(cursors, [0, 100, 200])
        limits = {call.kwargs["limit"] for call in mock_batch_evaluate.call_args_list}
        self.assertEqual(limits, {2})

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 3)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_non_advancing_cursor_fails_instead_of_looping(self, mock_batch_evaluate):
        self._create_flag()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.return_value = self._page([], next_cursor=0)

        with self.assertRaises(RuntimeError):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        self.assertEqual(mock_batch_evaluate.call_count, 1)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.error_code, CohortErrorCode.UNKNOWN)
        self.assertEqual(history.error, get_friendly_error_message(CohortErrorCode.UNKNOWN))

    @patch("posthog.api.cohort.time.sleep")
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_transient_errors_retry_then_succeed(self, mock_batch_evaluate, mock_sleep):
        self._create_flag()
        person = _create_person(team=self.team, distinct_ids=["person1"], properties={"key": "value"}, immediate=True)
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.side_effect = [
            requests.ConnectionError("connection refused"),
            self._page([str(person.uuid)]),
        ]

        retries_before = self._metric("cohort_flag_generation_page_retries_total")

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        self.assertEqual(mock_batch_evaluate.call_count, 2)
        self.assertEqual(self._metric("cohort_flag_generation_page_retries_total"), retries_before + 1)
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 1)
        self.assertEqual(cohort.errors_calculating, 0)

    @patch("posthog.api.cohort.time.sleep")
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_persistent_errors_exhaust_retries_and_propagate(self, mock_batch_evaluate, mock_sleep):
        self._create_flag()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.side_effect = requests.ConnectionError("connection refused")

        completed_before = self._metric("cohort_flag_generation_completed_total", outcome="unknown")

        with self.assertRaises(requests.ConnectionError):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        self.assertEqual(mock_batch_evaluate.call_count, BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS)
        self.assertEqual(
            self._metric("cohort_flag_generation_completed_total", outcome="unknown"), completed_before + 1
        )

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.error_code, CohortErrorCode.UNKNOWN)
        # The user-visible error is the friendly message, never the raw exception
        # (which can contain internal service URLs).
        self.assertEqual(history.error, get_friendly_error_message(CohortErrorCode.UNKNOWN))
        assert history.error is not None
        self.assertNotIn("connection refused", history.error)

    @patch("posthog.api.cohort.time.sleep")
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_version_conflict_is_not_retried_and_surfaces_user_facing_error(self, mock_batch_evaluate, mock_sleep):
        self._create_flag()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.side_effect = FlagVersionConflictError("flag changed during cohort generation")

        with self.assertRaises(FlagVersionConflictError):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        # Permanent error: no retries
        self.assertEqual(mock_batch_evaluate.call_count, 1)
        mock_sleep.assert_not_called()

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.error_code, CohortErrorCode.FLAG_CHANGED)
        self.assertEqual(
            get_friendly_error_message(history.error_code),
            "The feature flag changed while this cohort was being calculated. Please run the calculation again.",
        )

    @patch("posthog.api.cohort.time.sleep")
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_client_errors_are_not_retried(self, mock_batch_evaluate, mock_sleep):
        self._create_flag()
        cohort = self._create_static_cohort()

        response = requests.Response()
        response.status_code = 400
        mock_batch_evaluate.side_effect = requests.HTTPError(response=response)

        with self.assertRaises(requests.HTTPError):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        self.assertEqual(mock_batch_evaluate.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("posthog.api.cohort.time.sleep")
    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_server_errors_are_retried(self, mock_batch_evaluate, mock_sleep):
        self._create_flag()
        cohort = self._create_static_cohort()

        # A request timeout or overload surfaces as a 5xx HTTPError from raise_for_status,
        # which must fall through the 4xx permanent band and retry, unlike the 400 above.
        response = requests.Response()
        response.status_code = 503
        mock_batch_evaluate.side_effect = requests.HTTPError(response=response)

        with self.assertRaises(requests.HTTPError):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        self.assertEqual(mock_batch_evaluate.call_count, BATCH_FLAG_EVALUATION_PAGE_ATTEMPTS)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        self.assertEqual(cohort.errors_calculating, 1)
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.error_code, CohortErrorCode.UNKNOWN)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_rerun_after_failure_is_idempotent(self, mock_batch_evaluate):
        # Re-running after a failure (e.g. the user triggers cohort generation again)
        # re-inserts the same UUIDs; inserts dedupe on (cohort_id, person_id) so the
        # count must not grow.
        self._create_flag()
        person = _create_person(team=self.team, distinct_ids=["person1"], properties={"key": "value"}, immediate=True)
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.return_value = self._page([str(person.uuid)])

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)
        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 1)

        response = self.client.get(f"/api/cohort/{cohort.pk}/persons")
        self.assertEqual(len(response.json()["results"]), 1, response)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_per_person_eval_errors_do_not_fail_the_run(self, mock_batch_evaluate):
        self._create_flag()
        person = _create_person(team=self.team, distinct_ids=["person1"], properties={"key": "value"}, immediate=True)
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.return_value = self._page([str(person.uuid)], errors_count=5)

        get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 1)
        self.assertEqual(cohort.errors_calculating, 0)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_insert_batching_flushes_mid_run(self, mock_batch_evaluate):
        # With batchsize=2 and 2 matches on the first of two pages, the buffer flushes
        # mid-run and the final flush still completes the cohort.
        self._create_flag()
        persons = [
            _create_person(team=self.team, distinct_ids=[f"person{i}"], properties={"key": "value"}, immediate=True)
            for i in range(3)
        ]
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.side_effect = [
            self._page([str(persons[0].uuid), str(persons[1].uuid)], next_cursor=50),
            self._page([str(persons[2].uuid)], next_cursor=None),
        ]

        with patch.object(
            Cohort, "insert_users_list_by_uuid", autospec=True, side_effect=Cohort.insert_users_list_by_uuid
        ) as mock_insert:
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk, batchsize=2)

        # One mid-run flush (buffer hit batchsize) + the final flush
        self.assertEqual(mock_insert.call_count, 2)
        cohort.refresh_from_db()
        self.assertEqual(cohort.count, 3)

    @patch("posthog.api.cohort.batch_evaluate_flag_for_team")
    def test_insert_failure_is_recorded_as_failure_not_success(self, mock_batch_evaluate):
        # A DB/ClickHouse failure while inserting matched persons must surface as a failed
        # generation (the insert runs with raise_on_error=True), not be swallowed and
        # counted as success. DEBUG is forced off so the production swallow path is what
        # would run without raise_on_error.
        self._create_flag()
        person = _create_person(team=self.team, distinct_ids=["person1"], properties={"key": "value"}, immediate=True)
        flush_persons_and_events()
        cohort = self._create_static_cohort()

        mock_batch_evaluate.return_value = self._page([str(person.uuid)])

        success_before = self._metric("cohort_flag_generation_completed_total", outcome="success")
        unknown_before = self._metric("cohort_flag_generation_completed_total", outcome="unknown")

        with (
            self.settings(DEBUG=False),
            patch(
                "products.cohorts.backend.models.util.insert_static_cohort",
                side_effect=Exception("clickhouse insert failed"),
            ),
            self.assertRaises(Exception),
        ):
            get_cohort_actors_for_feature_flag(cohort.pk, "some-feature", self.team.pk)

        # Recorded as a failure, never as success.
        self.assertEqual(self._metric("cohort_flag_generation_completed_total", outcome="success"), success_before)
        self.assertEqual(self._metric("cohort_flag_generation_completed_total", outcome="unknown"), unknown_before + 1)

        cohort.refresh_from_db()
        self.assertFalse(cohort.is_calculating)
        # A single error save (the orchestrator's), not double-counted by the insert helper.
        self.assertEqual(cohort.errors_calculating, 1)
        history = CohortCalculationHistory.objects.get(cohort=cohort)
        self.assertEqual(history.error_code, CohortErrorCode.UNKNOWN)


class TestBlastRadius(ClickhouseTestMixin, APIBaseTest):
    @snapshot_clickhouse_queries
    def test_user_blast_radius(self):
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "group",
                            "type": "person",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 4, "total": 10}.items(), response_json.items())

    def test_user_blast_radius_with_flag_dependency(self):
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        dependency_flag = FeatureFlag.objects.create(
            team=self.team,
            key="dependency-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Flag dependencies can't be evaluated in HogQL, so they are neutral for the estimate
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": str(dependency_flag.pk),
                            "type": "flag",
                            "value": False,
                            "operator": "flag_evaluates_to",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual({"affected": 10, "total": 10}.items(), response.json().items())

    def test_user_blast_radius_with_flag_dependency_and_person_property(self):
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        dependency_flag = FeatureFlag.objects.create(
            team=self.team,
            key="dependency-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # The flag dependency is ignored, but the person property filter still applies
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": str(dependency_flag.pk),
                            "type": "flag",
                            "value": True,
                            "operator": "flag_evaluates_to",
                        },
                        {
                            "key": "group",
                            "type": "person",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                        },
                    ],
                    "rollout_percentage": 100,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual({"affected": 4, "total": 10}.items(), response.json().items())

    def test_user_blast_radius_with_groups_and_flag_dependency(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        dependency_flag = FeatureFlag.objects.create(
            team=self.team,
            key="dependency-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # The flag dependency is neutral for group-scoped blast radius too: it must not raise
        # on the missing group_type_index, and the group property filter still applies
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": str(dependency_flag.pk),
                            "type": "flag",
                            "value": True,
                            "operator": "flag_evaluates_to",
                        },
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual({"affected": 4, "total": 10}.items(), response.json().items())

    def test_user_blast_radius_persons_with_groups_and_flag_dependency(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        dependency_flag = FeatureFlag.objects.create(
            team=self.team,
            key="dependency-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # The persons path runs the same flag-dependency skip as the count path: a group-scoped flag
        # dependency must not raise on the missing group_type_index, and the group filter still applies.
        affected = get_user_blast_radius_persons(
            self.team,
            {
                "properties": [
                    {
                        "key": str(dependency_flag.pk),
                        "type": "flag",
                        "value": True,
                        "operator": "flag_evaluates_to",
                    },
                    {
                        "key": "industry",
                        "type": "group",
                        "value": [0, 1, 2, 3],
                        "operator": "exact",
                        "group_type_index": 0,
                    },
                ],
                "rollout_percentage": 25,
            },
            group_type_index=0,
        )

        self.assertEqual(set(affected), {"org:0", "org:1", "org:2", "org:3"})

    @freeze_time("2024-01-11")
    def test_user_blast_radius_with_relative_date_filters(self):
        for i in range(8):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}", "created_at": f"2023-0{i + 1}-04"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "created_at",
                            "type": "person",
                            "value": "-10m",
                            "operator": "is_date_before",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 3, "total": 8}.items(), response_json.items())

    def test_user_blast_radius_with_zero_users(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "group",
                            "type": "person",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 0, "total": 0}.items(), response_json.items())

    def test_user_blast_radius_with_zero_selected_users(self):
        for i in range(5):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "group",
                            "type": "person",
                            "value": [8],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 25,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 0, "total": 5}.items(), response_json.items())

    def test_user_blast_radius_with_all_selected_users(self):
        for i in range(5):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {"condition": {"properties": [], "rollout_percentage": 100}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 5, "total": 5}.items(), response_json.items())

    def test_user_blast_radius_with_distinct_id_filter(self):
        # Regression: distinct_id is not stored in person.properties — it lives in the
        # person_distinct_id2 table and must be joined via pdi. Filtering by distinct_id
        # in a release condition should match the persons that own that distinct_id.
        for i in range(5):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "distinct_id",
                            "type": "person",
                            "value": ["person1", "person3"],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 2, "total": 5}.items(), response_json.items())

    def test_user_blast_radius_with_distinct_id_filter_multiple_distinct_ids_per_person(self):
        # A single person can own multiple distinct_ids; filtering by any one should still
        # count that person exactly once.
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["alias-a", "alias-b"],
            properties={"group": "0"},
        )
        _create_person(
            team_id=self.team.pk,
            distinct_ids=["other"],
            properties={"group": "1"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "distinct_id",
                            "type": "person",
                            "value": ["alias-a", "alias-b"],
                            "operator": "exact",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 1, "total": 2}.items(), response_json.items())

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_single_cohort(self):
        # Just to shake things up, we're using integers for the group property
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": i},
            )

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": "none", "type": "person"},
                                {
                                    "key": "group",
                                    "value": ["1", "2", "3"],
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort1.pk}],
                    "rollout_percentage": 50,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 3, "total": 10}.items(), response_json.items())

        # test the same with precalculated cohort. Snapshots shouldn't have group property filter
        cohort1.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                {
                    "condition": {
                        "properties": [{"key": "id", "type": "cohort", "value": cohort1.pk}],
                        "rollout_percentage": 50,
                    }
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertLessEqual({"affected": 3, "total": 10}.items(), response_json.items())

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_multiple_precalculated_cohorts(self):
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        cohort1 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"key": "group", "value": "none", "type": "person"},
                                {
                                    "key": "group",
                                    "value": ["1", "2", "3"],
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort1",
        )

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "group",
                                    "value": ["1", "2", "4", "5", "6"],
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )

        # converts to precalculated-cohort due to simplify filters
        cohort1.calculate_people_ch(pending_version=0)
        cohort2.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                {
                    "condition": {
                        "properties": [
                            {"key": "id", "type": "cohort", "value": cohort1.pk},
                            {"key": "id", "type": "cohort", "value": cohort2.pk},
                        ],
                        "rollout_percentage": 50,
                    }
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertLessEqual({"affected": 2, "total": 10}.items(), response_json.items())

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_multiple_static_cohorts(self):
        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"group": f"{i}"},
            )

        cohort1 = Cohort.objects.create(team=self.team, groups=[], is_static=True, last_calculation=now())
        cohort1.insert_users_by_list(["person0", "person1", "person2"])

        cohort2 = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "group",
                                    "value": ["1", "2", "4", "5", "6"],
                                    "type": "person",
                                },
                            ],
                        }
                    ],
                }
            },
            name="cohort2",
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {"key": "id", "type": "cohort", "value": cohort1.pk},
                        {"key": "id", "type": "cohort", "value": cohort2.pk},
                    ],
                    "rollout_percentage": 50,
                }
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 2, "total": 10}.items(), response_json.items())

        cohort1.calculate_people_ch(pending_version=0)
        # converts to precalculated-cohort due to simplify filters
        cohort2.calculate_people_ch(pending_version=0)

        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
                {
                    "condition": {
                        "properties": [
                            {"key": "id", "type": "cohort", "value": cohort1.pk},
                            {"key": "id", "type": "cohort", "value": cohort2.pk},
                        ],
                        "rollout_percentage": 50,
                    }
                },
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_json = response.json()
            self.assertLessEqual({"affected": 2, "total": 10}.items(), response_json.items())

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_groups(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3],
                            "operator": "exact",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 4, "total": 10}.items(), response_json.items())

    def test_user_blast_radius_with_groups_zero_selected(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(5):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [8],
                            "operator": "exact",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 0, "total": 5}.items(), response_json.items())

    def test_user_blast_radius_with_groups_all_selected(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="company",
            group_type_index=1,
        )

        for i in range(5):
            create_group(
                team_id=self.team.pk,
                group_type_index=1,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [],
                    "rollout_percentage": 25,
                },
                "group_type_index": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 5, "total": 5}.items(), response_json.items())

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_groups_multiple_queries(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="company",
            group_type_index=1,
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3, 4],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [2, 3, 4, 5, 6],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertLessEqual({"affected": 3, "total": 10}.items(), response_json.items())

    @snapshot_clickhouse_queries
    def test_user_blast_radius_with_group_key_property(self):
        """Test that $group_key property correctly identifies groups by their key"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        # Create groups with specific keys
        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"tech-{i}"},
            )

        # Create one specific group we'll target
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="special-workspace",
            properties={"industry": "special"},
        )

        # Test filtering by exact group key match
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": "special-workspace",
                            "operator": "exact",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        # Should match exactly 1 group out of 11 total
        self.assertLessEqual({"affected": 1, "total": 11}.items(), response_json.items())

        # Test filtering by group key pattern
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": "org:",
                            "operator": "icontains",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        # Should match 10 groups that have "org:" in their key
        self.assertLessEqual({"affected": 10, "total": 11}.items(), response_json.items())

    def test_user_blast_radius_with_integer_property_values(self):
        """Test that integer property values are correctly normalized to strings for matching"""
        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"age": 25, "score": 100},
        )
        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"age": "25", "score": "100"},
        )
        _create_person(
            distinct_ids=["p3"],
            team_id=self.team.pk,
            properties={"age": 30, "score": 200},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "age",
                            "type": "person",
                            "value": [25],
                            "operator": "exact",
                        },
                    ],
                    "rollout_percentage": 100,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        # Both p1 (int 25) and p2 (string "25") should match
        self.assertEqual(response_json["affected"], 2)
        self.assertEqual(response_json["total"], 3)

    @parameterized.expand(
        [
            # (name, value, operator, expected_affected, expected_total)
            ("regex", "^org-(prod|staging)-\\d+$", "regex", 2, 3),
            ("not_regex", "^org-(prod|staging)-\\d+$", "not_regex", 1, 3),
            ("not_icontains", "ORG", "not_icontains", 1, 3),
        ]
    )
    def test_user_blast_radius_with_group_key_operators(
        self, _name, value, operator, expected_affected, expected_total
    ):
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-prod-001",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-staging-002",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="workspace-test-003",
            properties={},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": value,
                            "operator": operator,
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], expected_affected)
        self.assertEqual(response_json["total"], expected_total)

    def test_user_blast_radius_with_group_key_and_regular_properties(self):
        """Test combining $group_key with regular group properties"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:premium",
            properties={"plan": "enterprise"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org:free",
            properties={"plan": "free"},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="workspace:premium",
            properties={"plan": "enterprise"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": "org:",
                            "operator": "icontains",
                            "group_type_index": 0,
                        },
                        {
                            "key": "plan",
                            "type": "group",
                            "value": "enterprise",
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        # Should match only "org:premium" (has both org: prefix AND enterprise plan)
        self.assertEqual(response_json["affected"], 1)
        self.assertEqual(response_json["total"], 3)

    def test_user_blast_radius_with_dynamic_cohort(self):
        """Test that dynamic cohorts are evaluated correctly"""
        cohort = Cohort.objects.create(
            team=self.team,
            name="Dynamic cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": "@posthog.com",
                            "operator": "icontains",
                        }
                    ],
                }
            },
        )

        _create_person(
            distinct_ids=["p1"],
            team_id=self.team.pk,
            properties={"email": "user@posthog.com"},
        )
        _create_person(
            distinct_ids=["p2"],
            team_id=self.team.pk,
            properties={"email": "user@example.com"},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [{"key": "id", "type": "cohort", "value": cohort.id}],
                    "rollout_percentage": 100,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 1)
        self.assertEqual(response_json["total"], 2)

    def test_user_blast_radius_with_groups_incorrect_group_type(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="company",
            group_type_index=1,
        )

        for i in range(10):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"industry": f"{i}"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [0, 1, 2, 3, 4],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                        {
                            "key": "industry",
                            "type": "group",
                            "value": [2, 3, 4, 5, 6],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 25,
                },
                "group_type_index": 1,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response_json = response.json()
        self.assertLessEqual(
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Invalid group type index for feature flag condition.",
            }.items(),
            response_json.items(),
        )

    def test_user_blast_radius_with_group_key_unsupported_operator(self):
        """Test that unsupported operators on $group_key raise validation errors"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="test-org",
            properties={},
        )

        # Test with unsupported operator (e.g., 'gt' - greater than)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": "5",
                            "operator": "gt",  # Greater than is not supported for $group_key
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not supported", response.json()["detail"].lower())

    def test_user_blast_radius_with_group_key_exact_list_values(self):
        """Test that EXACT operator with list values uses IN logic"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-alpha",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-beta",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-gamma",
            properties={},
        )

        # Test EXACT with list of values (should match any value in the list)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": ["org-alpha", "org-beta"],  # List of values
                            "operator": "exact",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        # Should match org-alpha and org-beta (2 out of 3)
        self.assertEqual(response_json["affected"], 2)
        self.assertEqual(response_json["total"], 3)

    def test_user_blast_radius_with_group_key_is_not_list_values(self):
        """Test that IS_NOT operator with list values uses NOT IN logic"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-alpha",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-beta",
            properties={},
        )
        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-gamma",
            properties={},
        )

        # Test IS_NOT with list of values (should exclude all values in the list)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": [
                                "org-alpha",
                                "org-beta",
                            ],  # List of values to exclude
                            "operator": "is_not",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        # Should only match org-gamma (1 out of 3)
        self.assertEqual(response_json["affected"], 1)
        self.assertEqual(response_json["total"], 3)

    def test_user_blast_radius_with_group_key_icontains_list_values_raises_error(self):
        """Test that ICONTAINS operator with list values raises validation error"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        create_group(
            team_id=self.team.pk,
            group_type_index=0,
            group_key="org-alpha",
            properties={},
        )

        # Test ICONTAINS with list of values (should raise validation error)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": [
                                "alpha",
                                "beta",
                            ],  # List not supported for icontains
                            "operator": "icontains",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("does not support list values", response.json()["detail"].lower())

    def test_user_blast_radius_with_semver_operators(self):
        """Test all semver comparison operators"""
        versions = [
            "0.9.0",
            "1.0.0",
            "1.2.0",
            "1.2.3",
            "1.2.5",
            "1.3.0",
            "2.0.0",
            "2.1.0",
        ]
        for version in versions:
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person_{version}"],
                properties={"app_version": version},
            )

        # Test semver_eq
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_eq",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 1)
        self.assertEqual(response_json["total"], 8)

        # Test semver_gt
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_gt",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 4)  # 1.2.5, 1.3.0, 2.0.0, 2.1.0
        self.assertEqual(response_json["total"], 8)

        # Test semver_gte
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_gte",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 5)  # 1.2.3, 1.2.5, 1.3.0, 2.0.0, 2.1.0
        self.assertEqual(response_json["total"], 8)

        # Test semver_lt
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_lt",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 3)  # 0.9.0, 1.0.0, 1.2.0
        self.assertEqual(response_json["total"], 8)

        # Test semver_lte
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_lte",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 4)  # 0.9.0, 1.0.0, 1.2.0, 1.2.3
        self.assertEqual(response_json["total"], 8)

        # Test semver_tilde (~1.2.3 means >=1.2.3 <1.3.0)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_tilde",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 2)  # 1.2.3, 1.2.5
        self.assertEqual(response_json["total"], 8)

        # Test semver_caret (^1.2.3 means >=1.2.3 <2.0.0)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.3",
                            "operator": "semver_caret",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 3)  # 1.2.3, 1.2.5, 1.3.0
        self.assertEqual(response_json["total"], 8)

        # Test semver_wildcard (1.2.* means >=1.2.0 <1.3.0)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.2.*",
                            "operator": "semver_wildcard",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 3)  # 1.2.0, 1.2.3, 1.2.5
        self.assertEqual(response_json["total"], 8)

        # Test semver_wildcard with major version (1.* means >=1.0.0 <2.0.0)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "1.*",
                            "operator": "semver_wildcard",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 5)  # 1.0.0, 1.2.0, 1.2.3, 1.2.5, 1.3.0
        self.assertEqual(response_json["total"], 8)

    def test_user_blast_radius_with_semver_caret_0x_versions(self):
        """Test semver caret operator handles 0.x.y versions per spec"""
        # Test data with 0.x.y versions to verify caret operator behavior
        versions = [
            "0.0.1",
            "0.0.3",
            "0.0.5",
            "0.1.0",
            "0.2.3",
            "0.2.5",
            "0.3.0",
            "1.0.0",
        ]
        for version in versions:
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person_{version}"],
                properties={"app_version": version},
            )

        # Test ^0.2.3 means >=0.2.3 <0.3.0 (not <1.0.0)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "0.2.3",
                            "operator": "semver_caret",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 2)  # 0.2.3, 0.2.5 (NOT 0.3.0 or 1.0.0)
        self.assertEqual(response_json["total"], 8)

        # Test ^0.0.3 means >=0.0.3 <0.0.4 (not <1.0.0 or <0.1.0)
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "app_version",
                            "type": "person",
                            "value": "0.0.3",
                            "operator": "semver_caret",
                        }
                    ],
                    "rollout_percentage": 100,
                }
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 1)  # Only 0.0.3 (NOT 0.0.5, 0.1.0, etc.)
        self.assertEqual(response_json["total"], 8)

    def test_user_blast_radius_with_semver_operators_on_groups(self):
        """Test semver operators work with group properties"""
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        versions = ["1.0.0", "1.5.0", "2.0.0", "2.5.0", "3.0.0"]
        for version in versions:
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org-{version}",
                properties={"min_version": version},
            )

        # Create persons in organizations
        for i, version in enumerate(versions):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person_{i}"],
                properties={"$group_0": f"org-{version}"},
            )

        # Test semver_gte on group property
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "min_version",
                            "type": "group",
                            "value": "2.0.0",
                            "operator": "semver_gte",
                            "group_type_index": 0,
                        }
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json["affected"], 3)  # 2.0.0, 2.5.0, 3.0.0
        self.assertEqual(response_json["total"], 5)

    def test_user_blast_radius_person_condition_separate_from_group_condition(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(10):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"plan": "pro" if i < 6 else "free"},
            )

        for i in range(8):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"size": "enterprise" if i < 3 else "startup"},
            )

        # Person-aggregated condition: only person properties
        person_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "plan",
                            "type": "person",
                            "value": ["pro"],
                            "operator": "exact",
                        },
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": None,
            },
        )
        self.assertEqual(person_response.status_code, status.HTTP_200_OK)
        self.assertEqual(person_response.json()["affected"], 6)
        self.assertEqual(person_response.json()["total"], 10)

        # Group-aggregated condition: only group properties
        group_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "size",
                            "type": "group",
                            "value": ["enterprise"],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )
        self.assertEqual(group_response.status_code, status.HTTP_200_OK)
        self.assertEqual(group_response.json()["affected"], 3)
        self.assertEqual(group_response.json()["total"], 8)

    def test_user_blast_radius_pure_person_condition_has_no_group_counts(self):
        for i in range(5):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"plan": "pro" if i < 3 else "free"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "plan",
                            "type": "person",
                            "value": ["pro"],
                            "operator": "exact",
                        },
                    ],
                    "rollout_percentage": 100,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertEqual(response_json["affected"], 3)
        self.assertEqual(response_json["total"], 5)

    def test_user_blast_radius_with_group_key_filter(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(6):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"size": "large"},
            )

        # Group-aggregated condition with $group_key filter
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "$group_key",
                            "type": "group",
                            "value": ["org:0", "org:1"],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_json = response.json()
        self.assertEqual(response_json["affected"], 2)
        self.assertEqual(response_json["total"], 6)

    def test_user_blast_radius_cohort_condition_and_group_condition_separate(self):
        create_group_type_mapping_without_created_at(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
        )

        for i in range(8):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"plan": "pro" if i < 5 else "free"},
            )

        for i in range(4):
            create_group(
                team_id=self.team.pk,
                group_type_index=0,
                group_key=f"org:{i}",
                properties={"tier": "enterprise" if i < 2 else "startup"},
            )

        cohort = Cohort.objects.create(
            team=self.team,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": [{"key": "plan", "value": ["pro"], "type": "person", "operator": "exact"}],
                        }
                    ],
                }
            },
            name="Pro users",
        )
        cohort.calculate_people_ch(pending_version=0)

        # Person-aggregated condition with cohort filter
        person_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "id",
                            "type": "cohort",
                            "value": cohort.pk,
                        },
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": None,
            },
        )
        self.assertEqual(person_response.status_code, status.HTTP_200_OK)
        self.assertEqual(person_response.json()["affected"], 5)
        self.assertEqual(person_response.json()["total"], 8)

        # Group-aggregated condition with group property filter
        group_response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "tier",
                            "type": "group",
                            "value": ["enterprise"],
                            "operator": "exact",
                            "group_type_index": 0,
                        },
                    ],
                    "rollout_percentage": 100,
                },
                "group_type_index": 0,
            },
        )
        self.assertEqual(group_response.status_code, status.HTTP_200_OK)
        self.assertEqual(group_response.json()["affected"], 2)
        self.assertEqual(group_response.json()["total"], 4)

    def test_user_blast_radius_no_error_fields_for_successful_queries(self):
        for i in range(3):
            _create_person(
                team_id=self.team.pk,
                distinct_ids=[f"person{i}"],
                properties={"plan": "pro"},
            )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/user_blast_radius",
            {
                "condition": {
                    "properties": [
                        {
                            "key": "plan",
                            "type": "person",
                            "value": ["pro"],
                            "operator": "exact",
                        },
                    ],
                    "rollout_percentage": 100,
                },
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class TestFeatureFlagEvaluationContexts(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

        # Mock FLAG_EVALUATION_TAGS feature flag to be enabled by default
        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")
        self.mock_feature_enabled = self.feature_flag_patcher.start()
        self.mock_feature_enabled.return_value = True

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    @pytest.mark.ee
    def test_create_feature_flag_with_evaluation_contexts(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Flag with evaluation contexts",
                "key": "flag-with-eval-tags",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "tags": ["app", "marketing", "docs"],
                "evaluation_contexts": ["app", "docs"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        flag = FeatureFlag.objects.get(key="flag-with-eval-tags")

        # Check that tags are created
        tagged_items = TaggedItem.objects.filter(feature_flag=flag)
        self.assertEqual(tagged_items.count(), 3)
        tag_names = sorted([item.tag.name for item in tagged_items])
        self.assertEqual(tag_names, ["app", "docs", "marketing"])

        # Check that evaluation contexts are created (using new model)
        from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

        eval_contexts = FeatureFlagEvaluationContext.objects.filter(feature_flag=flag)
        self.assertEqual(eval_contexts.count(), 2)
        eval_context_names = sorted([ctx.evaluation_context.name for ctx in eval_contexts])
        self.assertEqual(eval_context_names, ["app", "docs"])

    @pytest.mark.ee
    def test_update_feature_flag_evaluation_contexts(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            name="Test Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "tags": ["app", "marketing"],
                "evaluation_contexts": ["app"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

        eval_contexts = FeatureFlagEvaluationContext.objects.filter(feature_flag=flag)
        self.assertEqual(eval_contexts.count(), 1)
        first_context = eval_contexts.first()
        assert first_context is not None
        self.assertEqual(first_context.evaluation_context.name, "app")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "tags": ["app", "marketing", "docs"],
                "evaluation_contexts": ["marketing", "docs"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        eval_contexts = FeatureFlagEvaluationContext.objects.filter(feature_flag=flag)
        self.assertEqual(eval_contexts.count(), 2)
        eval_context_names = sorted([ctx.evaluation_context.name for ctx in list(eval_contexts)])
        self.assertEqual(eval_context_names, ["docs", "marketing"])

    @pytest.mark.ee
    def test_remove_all_evaluation_contexts(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            name="Test Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "tags": ["app", "marketing"],
                "evaluation_contexts": ["app", "marketing"],
            },
            format="json",
        )

        from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

        self.assertEqual(FeatureFlagEvaluationContext.objects.filter(feature_flag=flag).count(), 2)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "tags": ["app", "marketing"],
                "evaluation_contexts": [],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Evaluation contexts should be removed
        self.assertEqual(FeatureFlagEvaluationContext.objects.filter(feature_flag=flag).count(), 0)

        # Regular tags should still exist
        tagged_items = TaggedItem.objects.filter(feature_flag=flag)
        self.assertEqual(tagged_items.count(), 2)

    @pytest.mark.ee
    def test_evaluation_contexts_in_minimal_serializer(self):
        from products.feature_flags.backend.api.feature_flag import MinimalFeatureFlagSerializer
        from products.feature_flags.backend.models.evaluation_context import (
            EvaluationContext,
            FeatureFlagEvaluationContext,
        )

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            name="Test Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        app_context = EvaluationContext.objects.create(name="app", team=self.team)
        docs_context = EvaluationContext.objects.create(name="docs", team=self.team)

        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=app_context)
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=docs_context)

        serializer = MinimalFeatureFlagSerializer(flag)
        data = serializer.data

        self.assertIn("evaluation_contexts", data)
        self.assertEqual(sorted(data["evaluation_contexts"]), ["app", "docs"])

    @pytest.mark.ee
    def test_evaluation_contexts_independent_from_tags(self):
        """Evaluation contexts are independent from tags — no subset constraint."""
        # Contexts and tags can be completely different
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Independent contexts",
                "key": "independent-contexts",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "tags": ["app", "docs"],
                "evaluation_contexts": ["production", "staging"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sorted(response.json()["evaluation_contexts"]), ["production", "staging"])

        # Contexts without any tags
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Contexts without tags",
                "key": "contexts-no-tags",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "tags": [],
                "evaluation_contexts": ["production"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["evaluation_contexts"], ["production"])

    @pytest.mark.ee
    def test_evaluation_contexts_hidden_when_feature_flag_disabled(self):
        self.mock_feature_enabled.return_value = False

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Flag with evaluation contexts",
                "key": "flag-with-eval-tags-disabled",
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "tags": ["web", "mobile"],
                "evaluation_contexts": ["web"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        flag = FeatureFlag.objects.get(key="flag-with-eval-tags-disabled")
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["evaluation_contexts"], [])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "name": "Updated flag with disabled feature flag",
                "evaluation_contexts": ["web", "mobile"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        flag.refresh_from_db()
        self.assertEqual(flag.flag_evaluation_contexts.count(), 0)

        self.mock_feature_enabled.return_value = True

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["evaluation_contexts"], [])

    @pytest.mark.ee
    def test_evaluation_contexts_in_cache(self):
        from products.feature_flags.backend.models.evaluation_context import (
            EvaluationContext,
            FeatureFlagEvaluationContext,
        )
        from products.feature_flags.backend.models.feature_flag import set_feature_flags_for_team_in_cache

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="cached-flag",
            name="Cached Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        # Create evaluation context
        ctx = EvaluationContext.objects.create(name="app", team=self.team)
        FeatureFlagEvaluationContext.objects.create(feature_flag=flag, evaluation_context=ctx)

        # Set flags in cache
        set_feature_flags_for_team_in_cache(self.team.project_id)

        # Get flags from cache
        cached_flags = get_feature_flags_for_team_in_cache(self.team.project_id)
        self.assertIsNotNone(cached_flags)
        assert cached_flags is not None
        self.assertEqual(len(cached_flags), 1)

        cached_flag = cached_flags[0]
        self.assertEqual(cached_flag.key, "cached-flag")
        # Evaluation tag names should be exposed via the property when populated from cache
        self.assertIsNotNone(cached_flag.evaluation_tag_names)
        self.assertEqual(cached_flag.evaluation_tag_names, ["app"])

    @parameterized.expand([("with_experiment", True), ("without_experiment", False)])
    @pytest.mark.ee
    def test_has_experiment_survives_cache_round_trip(self, _name: str, has_experiment: bool):
        from products.feature_flags.backend.models.feature_flag import (
            get_feature_flags_for_team_in_cache,
            set_feature_flags_for_team_in_cache,
        )

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="round-trip-flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )
        if has_experiment:
            Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)

        set_feature_flags_for_team_in_cache(self.team.project_id)
        cached_flags = get_feature_flags_for_team_in_cache(self.team.project_id)

        assert cached_flags is not None
        cached_flag = next(f for f in cached_flags if f.key == "round-trip-flag")
        # The cached value is read back without a per-flag experiment query.
        self.assertEqual(cached_flag._has_experiment, has_experiment)

    @pytest.mark.ee
    def test_evaluation_contexts_cache_invalidation(self):
        from products.feature_flags.backend.models.feature_flag import (
            get_feature_flags_for_team_in_cache,
            set_feature_flags_for_team_in_cache,
        )

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="cache-invalidation-test",
            name="Cache Invalidation Test",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        set_feature_flags_for_team_in_cache(self.team.project_id)

        cached_flags = get_feature_flags_for_team_in_cache(self.team.project_id)
        assert cached_flags is not None
        cached_flag = next((f for f in cached_flags if f.key == "cache-invalidation-test"), None)
        assert cached_flag is not None
        self.assertEqual(cached_flag.evaluation_tag_names, [])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "tags": ["app", "docs"],
                "evaluation_contexts": ["app"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Cache should be automatically invalidated and refreshed
        cached_flags = get_feature_flags_for_team_in_cache(self.team.project_id)
        assert cached_flags is not None
        cached_flag = next((f for f in cached_flags if f.key == "cache-invalidation-test"), None)
        assert cached_flag is not None
        self.assertEqual(cached_flag.evaluation_tag_names, ["app"])

    @pytest.mark.ee
    def test_cache_read_back_ignores_unknown_non_model_key(self):
        from posthog.caching.flags_redis_cache import write_flags_to_cache

        from products.feature_flags.backend.models.feature_flag import FIVE_DAYS, serialize_feature_flags

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="unknown-key-flag",
            name="Unknown Key Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        [serialized] = serialize_feature_flags([flag])
        # A future SDK-only serializer field that is not a model field must not break read-back.
        serialized["some_future_sdk_field"] = {"anything": True}
        write_flags_to_cache(
            f"team_feature_flags_{self.team.project_id}",
            json.dumps([serialized]),
            FIVE_DAYS,
        )

        cached_flags = get_feature_flags_for_team_in_cache(self.team.project_id)
        assert cached_flags is not None
        self.assertEqual(len(cached_flags), 1)
        self.assertEqual(cached_flags[0].key, "unknown-key-flag")

    @parameterized.expand(
        [
            # (name, evaluation_contexts value, evaluation_tags value, expected)
            ("current_key", ["app", "docs"], None, ["app", "docs"]),
            ("legacy_key", None, ["app", "docs"], ["app", "docs"]),
            # When both keys are present, the current `evaluation_contexts` key wins.
            ("both_keys_current_wins", ["app", "docs"], ["legacy"], ["app", "docs"]),
        ]
    )
    @pytest.mark.ee
    def test_cache_read_back_accepts_evaluation_context_keys(
        self,
        _name: str,
        contexts_value: Optional[list[str]],
        tags_value: Optional[list[str]],
        expected: list[str],
    ):
        from posthog.caching.flags_redis_cache import write_flags_to_cache

        from products.feature_flags.backend.models.feature_flag import FIVE_DAYS, serialize_feature_flags

        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"eval-context-key-{_name}",
            name="Eval Context Key Flag",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        [serialized] = serialize_feature_flags([flag])
        # Exercise the current `evaluation_contexts` key, the legacy `evaluation_tags`
        # key, and entries that carry both (where the current key must take precedence).
        serialized.pop("evaluation_contexts", None)
        if contexts_value is not None:
            serialized["evaluation_contexts"] = contexts_value
        if tags_value is not None:
            serialized["evaluation_tags"] = tags_value
        write_flags_to_cache(
            f"team_feature_flags_{self.team.project_id}",
            json.dumps([serialized]),
            FIVE_DAYS,
        )

        cached_flags = get_feature_flags_for_team_in_cache(self.team.project_id)
        assert cached_flags is not None
        cached_flag = next(f for f in cached_flags if f.key == flag.key)
        self.assertEqual(cached_flag.evaluation_tag_names, expected)

    def _get_eval_context_activity_entries(self, flag_id: int, activity: str = "updated") -> list:
        from posthog.models.activity_logging.activity_log import ActivityLog

        def _has_eval_context_change(entry: ActivityLog) -> bool:
            detail = entry.detail
            if detail is None:
                return False
            changes = detail.get("changes") or []
            return any(c.get("field") == "evaluation_contexts" for c in changes)

        return [
            entry
            for entry in ActivityLog.objects.filter(
                team_id=self.team.id,
                scope="FeatureFlag",
                item_id=str(flag_id),
                activity=activity,
            ).order_by("-created_at")
            if _has_eval_context_change(entry)
        ]

    @staticmethod
    def _get_eval_context_change(entry) -> dict:
        assert entry.detail is not None
        changes = entry.detail["changes"]
        return next(c for c in changes if c["field"] == "evaluation_contexts")

    @parameterized.expand(
        [
            ("add_contexts", [], ["production", "staging"], [], ["production", "staging"]),
            (
                "update_contexts",
                ["production", "staging"],
                ["production", "docs"],
                ["production", "staging"],
                ["docs", "production"],
            ),
            ("remove_all_contexts", ["production", "staging"], [], ["production", "staging"], []),
        ]
    )
    def test_evaluation_context_change_is_logged(
        self,
        _name: str,
        initial: list[str],
        updated: list[str],
        expected_before: list[str],
        expected_after: list[str],
    ):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"activity-test-{_name}",
            name="Activity Test",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        if initial:
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
                {"evaluation_contexts": initial},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"evaluation_contexts": updated},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        entries = self._get_eval_context_activity_entries(flag.id)
        self.assertGreaterEqual(len(entries), 1)

        latest_change = self._get_eval_context_change(entries[0])
        self.assertEqual(latest_change["before"], expected_before)
        self.assertEqual(latest_change["after"], expected_after)

    @pytest.mark.ee
    def test_no_activity_log_when_evaluation_contexts_unchanged(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="no-change-test",
            name="No Change Test",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
            created_by=self.user,
        )

        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"evaluation_contexts": ["production"]},
            format="json",
        )

        # Send same evaluation contexts again
        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"evaluation_contexts": ["production"]},
            format="json",
        )

        # Only 1 from the initial set, none from the no-op update
        entries = self._get_eval_context_activity_entries(flag.id)
        self.assertEqual(len(entries), 1)


class TestFeatureFlagStatus(APIBaseTest, ClickhouseTestMixin):
    def setUp(self):
        cache.clear()

        # delete all keys in redis
        r = redis.get_client()
        for key in r.scan_iter("*"):
            r.delete(key)
        return super().setUp()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def assert_expected_response(
        self,
        feature_flag_id: int,
        expected_status: FeatureFlagStatus,
        expected_reason: Optional[str] = None,
    ):
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/{feature_flag_id}/status",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        response_data = response.json()
        self.assertEqual(response_data.get("status"), expected_status)
        if expected_reason is not None:
            self.assertEqual(response_data.get("reason"), expected_reason)

    def test_flag_status_reasons(self):
        FeatureFlag.objects.all().delete()

        # Request status for non-existent flag returns 404
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/1/status")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Request status for flag that has been soft deleted
        deleted_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Deleted feature flag",
            key="deleted-feature-flag",
            team=self.team,
            deleted=True,
            active=True,
        )
        self.assert_expected_response(deleted_flag.id, FeatureFlagStatus.DELETED, "Flag has been deleted")

        # Request status for flag that is disabled, but recently called
        disabled_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Disabled feature flag",
            key="disabled-feature-flag",
            team=self.team,
            active=False,
            last_called_at=datetime.now(UTC) - timedelta(days=1),  # Recently called
        )

        self.assert_expected_response(disabled_flag.id, FeatureFlagStatus.ACTIVE)

        feature_enrollment_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="feature enrollment flag",
            key="feature-enrollment-flag",
            team=self.team,
            active=True,
            filters={"feature_enrollment": True},
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(feature_enrollment_flag.id, FeatureFlagStatus.ACTIVE)

        # Request status for flag with holdout at <100% exclusion
        holdout_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="50 percent holdout flag",
            key="50-percent-holdout-flag",
            team=self.team,
            active=True,
            filters={"holdout": {"id": 1, "exclusion_percentage": 50}},
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(holdout_flag.id, FeatureFlagStatus.ACTIVE)

        # Request status for flag with holdout at 100% exclusion
        fully_excluded_holdout_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="100 percent holdout flag",
            key="100-percent-holdout-flag",
            team=self.team,
            active=True,
            filters={"holdout": {"id": 2, "exclusion_percentage": 100}},
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(
            fully_excluded_holdout_flag.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for multivariate flag with no variants set to 100%
        multivariate_flag_no_rolled_out_variants = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with no variants set to 100%",
            key="multivariate-no-rolled-out-variants-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "var1key", "name": "test", "rollout_percentage": 50},
                        {"key": "var2key", "name": "control", "rollout_percentage": 50},
                    ],
                }
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(multivariate_flag_no_rolled_out_variants.id, FeatureFlagStatus.ACTIVE)

        # Request status for multivariate flag with variant set to 100% and no usage data
        # This tests config-based staleness detection
        multivariate_flag_rolled_out_variant = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with variant set to 100%",
            key="multivariate-rolled-out-variant-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "test", "rollout_percentage": 100},
                        {"key": "control", "rollout_percentage": 0},
                    ],
                },
                "groups": [{"variant": None, "properties": [], "rollout_percentage": 100}],
            },
            last_called_at=None,  # No usage data - falls back to config-based detection
        )
        self.assert_expected_response(
            multivariate_flag_rolled_out_variant.id,
            FeatureFlagStatus.STALE,
            'This flag will always use the variant "test"',
        )

        # Request status for multivariate flag with a variant set to 100% but no release condition set to 100%
        multivariate_flag_rolled_out_variant_no_rolled_out_release = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with variant set to 100%, no release condition set to 100%",
            key="multivariate-rolled-out-variant-no-release-rolled-out-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "var1key", "name": "test", "rollout_percentage": 100},
                        {"key": "var2key", "name": "control", "rollout_percentage": 0},
                    ],
                },
                "groups": [
                    {"variant": None, "properties": [], "rollout_percentage": 20},
                    {"variant": None, "properties": [], "rollout_percentage": 30},
                ],
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(
            multivariate_flag_rolled_out_variant_no_rolled_out_release.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for multivariate flag with a variant set to 100% but no release condition set to 100%
        multivariate_flag_rolled_out_release_condition_half_variant = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with release condition set to 100%, but variants still 50%",
            key="multivariate-rolled-out-release-half-variant-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "var1key", "name": "test", "rollout_percentage": 50},
                        {"key": "var2key", "name": "control", "rollout_percentage": 50},
                    ],
                },
                "groups": [
                    {"variant": None, "properties": [], "rollout_percentage": 100},
                ],
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(
            multivariate_flag_rolled_out_release_condition_half_variant.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for multivariate flag with variants set to 100% and a filtered release condition
        multivariate_flag_rolled_out_variant_rolled_out_filtered_release = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with variant and release condition set to 100%",
            key="multivariate-rolled-out-variant-and-release-condition-with-properties-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "var1key", "name": "test", "rollout_percentage": 100},
                        {"key": "var2key", "name": "control", "rollout_percentage": 0},
                    ],
                },
                "groups": [
                    {
                        "variant": None,
                        "properties": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["Smith"],
                                "operator": "contains",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ],
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(
            multivariate_flag_rolled_out_variant_rolled_out_filtered_release.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for multivariate flag with no variants set to 100%, but a filtered and fully rolled out release condition has variant override
        multivariate_flag_filtered_rolled_out_release_with_override = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with release condition set to 100% and override",
            key="multivariate-rolled-out-filtered-release-condition-and-override-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "var1key", "name": "test", "rollout_percentage": 60},
                        {"key": "var2key", "name": "control", "rollout_percentage": 40},
                    ],
                },
                "groups": [
                    {
                        "variant": "var1key",
                        "properties": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["Smith"],
                                "operator": "contains",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ],
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(
            multivariate_flag_filtered_rolled_out_release_with_override.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for multivariate flag with no variants set to 100%, but fully rolled out release condition has variant override
        # This tests config-based staleness detection
        multivariate_flag_rolled_out_release_with_override = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Multivariate flag with release condition set to 100% and override",
            key="multivariate-rolled-out-release-condition-and-override-flag",
            team=self.team,
            active=True,
            filters={
                "multivariate": {
                    "variants": [
                        {"key": "test", "rollout_percentage": 60},
                        {"key": "control", "rollout_percentage": 40},
                    ],
                },
                "groups": [
                    {
                        "variant": "test",
                        "properties": [],
                        "rollout_percentage": 100,
                    }
                ],
            },
            last_called_at=None,  # No usage data - falls back to config-based detection
        )
        self.assert_expected_response(
            multivariate_flag_rolled_out_release_with_override.id,
            FeatureFlagStatus.STALE,
            'This flag will always use the variant "test"',
        )

        # Request status for boolean flag with empty filters
        # This tests config-based staleness detection
        boolean_flag_empty_filters = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Boolean flag with empty filters",
            key="boolean-empty-filters-flag",
            team=self.team,
            active=True,
            filters={},
            last_called_at=None,  # No usage data - falls back to config-based detection
        )
        self.assert_expected_response(
            boolean_flag_empty_filters.id,
            FeatureFlagStatus.STALE,
            'This boolean flag will always evaluate to "true"',
        )

        # Request status for boolean flag with no fully rolled out release conditions
        boolean_flag_no_rolled_out_release_conditions = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Boolean flag with no release condition set to 100%",
            key="boolean-no-rolled-out-release-conditions-flag",
            team=self.team,
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 99,
                    },
                    {
                        "properties": [],
                        "rollout_percentage": 99,
                    },
                    {
                        "properties": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["Smith"],
                                "operator": "contains",
                            }
                        ],
                        "rollout_percentage": 100,
                    },
                ],
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )

        self.assert_expected_response(
            boolean_flag_no_rolled_out_release_conditions.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for boolean flag with a fully rolled out release condition
        # This tests config-based staleness detection
        boolean_flag_rolled_out_release_condition = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Boolean flag with a release condition set to 100%",
            key="boolean-rolled-out-release-condition-flag",
            team=self.team,
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["Smith"],
                                "operator": "contains",
                            }
                        ],
                        "rollout_percentage": 50,
                    },
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    },
                ],
            },
            last_called_at=None,  # No usage data - falls back to config-based detection
        )
        self.assert_expected_response(
            boolean_flag_rolled_out_release_condition.id,
            FeatureFlagStatus.STALE,
            'This boolean flag will always evaluate to "true"',
        )

        # Request status for boolean flag with a fully rolled out release condition
        boolean_flag_rolled_out_release_condition_created_twenty_nine_days_ago = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=29),
            name="Boolean flag with a release condition set to 100%, created 29 days ago",
            key="boolean-rolled-out-release-condition-29-days-ago-flag",
            team=self.team,
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [],
                        "rollout_percentage": 100,
                    },
                ],
            },
        )
        self.assert_expected_response(
            boolean_flag_rolled_out_release_condition_created_twenty_nine_days_ago.id,
            FeatureFlagStatus.ACTIVE,
        )

        # Request status for a boolean flag with no rolled out release conditions and has
        # been called recently
        boolean_flag_no_rolled_out_release_condition_recently_evaluated = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Boolean flag with a release condition set to 100%",
            key="boolean-recently-evaluated-flag",
            team=self.team,
            active=True,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["Smith"],
                                "operator": "contains",
                            }
                        ],
                        "rollout_percentage": 50,
                    },
                ],
            },
            last_called_at=datetime.now(UTC) - timedelta(days=1),  # Recently called
        )

        self.assert_expected_response(
            boolean_flag_no_rolled_out_release_condition_recently_evaluated.id,
            FeatureFlagStatus.ACTIVE,
        )

    def test_flag_status_old_flag_no_usage_data_not_fully_rolled_out_is_active(self):
        """Old flag without usage data and not fully rolled out should be ACTIVE (can't determine staleness)"""
        old_never_called_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=31),
            name="Never called flag",
            key="never-called-flag",
            team=self.team,
            active=True,
            last_called_at=None,
            # Use 50% rollout so it's not fully rolled out
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        # Without usage data (last_called_at) and not fully rolled out, we can't determine if it's stale
        self.assert_expected_response(
            old_never_called_flag.id,
            FeatureFlagStatus.ACTIVE,
        )

    def test_flag_status_stale_by_usage_not_recently_called(self):
        """Flag that hasn't been called in 30+ days should be STALE (usage-based detection)"""
        stale_usage_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=60),
            name="Not recently called flag",
            key="not-recently-called-flag",
            team=self.team,
            active=True,
            last_called_at=datetime.now(UTC) - timedelta(days=35),
            # Use 50% rollout - not fully rolled out but still STALE because not called
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        self.assert_expected_response(
            stale_usage_flag.id,
            FeatureFlagStatus.STALE,
        )

    def test_flag_status_new_flag_without_calls_not_stale(self):
        """New flag (< 30 days) without usage data should be ACTIVE (grace period)"""
        new_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=5),
            name="New flag",
            key="new-flag",
            team=self.team,
            active=True,
            last_called_at=None,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        self.assert_expected_response(new_flag.id, FeatureFlagStatus.ACTIVE)

    def test_flag_status_cross_team_returns_404(self):
        other_team = Team.objects.create(organization=Organization.objects.create(name="other org"))
        other_flag = FeatureFlag.objects.create(
            name="Other team flag",
            key="other-team-flag",
            team=other_team,
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )
        response = self.client.get(
            f"/api/projects/{self.team.id}/feature_flags/{other_flag.id}/status",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_flag_status_recently_called_at_100_rollout_is_active(self):
        """Flag that was recently called at 100% should be ACTIVE (usage data takes precedence)"""
        recently_called_flag = FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=60),
            name="Recently called flag",
            key="recently-called-flag",
            team=self.team,
            active=True,
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
            last_called_at=datetime.now(UTC) - timedelta(days=1),
        )
        # Usage data shows flag is being called, so it's ACTIVE even at 100% rollout
        self.assert_expected_response(
            recently_called_flag.id,
            FeatureFlagStatus.ACTIVE,
        )

    # (name, filters, expected_rollout) — exercises the rollout summary end-to-end through the serializer.
    @parameterized.expand(
        [
            (
                "full_rollout",
                {"groups": [{"rollout_percentage": 100, "properties": []}]},
                {
                    "effectively_full_rollout": True,
                    "has_targeting_conditions": False,
                    "max_rollout_percentage": 100,
                    "is_multivariate": False,
                },
            ),
            (
                "targeted",
                {"groups": [{"rollout_percentage": 50, "properties": [{"key": "email", "value": "x"}]}]},
                {
                    "effectively_full_rollout": False,
                    "has_targeting_conditions": True,
                    "max_rollout_percentage": 50,
                    "is_multivariate": False,
                },
            ),
            # Multivariate flag guards the is_multivariate field through the serializer path.
            (
                "multivariate",
                {
                    "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                    "groups": [{"rollout_percentage": 100, "properties": []}],
                },
                {
                    "effectively_full_rollout": True,
                    "has_targeting_conditions": False,
                    "max_rollout_percentage": 100,
                    "is_multivariate": True,
                },
            ),
        ]
    )
    def test_flag_status_includes_rollout_summary(self, name, filters, expected_rollout):
        """The status response exposes a rollout summary so callers can determine full rollout / GA."""
        flag = FeatureFlag.objects.create(
            name=f"{name} flag",
            key=f"{name}-flag",
            team=self.team,
            active=True,
            filters=filters,
            last_called_at=datetime.now(UTC),
        )
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/status")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["rollout"], expected_rollout)

    def test_get_flags_with_stale_filter_usage_and_config_based(self):
        """Test filtering by STALE status with both usage and config-based detection"""
        FeatureFlag.objects.all().delete()

        # Create a stale flag (usage-based: old + not called in 30+ days)
        FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=60),
            team=self.team,
            created_by=self.user,
            key="stale_by_usage_flag",
            active=True,
            last_called_at=datetime.now(UTC) - timedelta(days=35),
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Create a stale flag (config-based: old + 100% rollout + no usage data)
        FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=60),
            team=self.team,
            created_by=self.user,
            key="stale_by_config_flag",
            active=True,
            last_called_at=None,
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )

        # Create an active flag (recently called)
        FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=60),
            team=self.team,
            created_by=self.user,
            key="active_flag",
            active=True,
            last_called_at=datetime.now(UTC) - timedelta(hours=1),
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Create an active flag (no usage data + not fully rolled out = can't determine staleness)
        FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=60),
            team=self.team,
            created_by=self.user,
            key="no_data_partial_rollout_flag",
            active=True,
            last_called_at=None,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Create a new flag that hasn't been called (should be ACTIVE, grace period)
        FeatureFlag.objects.create(
            created_at=datetime.now(UTC) - timedelta(days=5),
            team=self.team,
            created_by=self.user,
            key="new_uncalled_flag",
            active=True,
            last_called_at=None,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Test filtering by STALE status
        response = self.client.get("/api/projects/@current/feature_flags?active=STALE")
        results = response.json()["results"]

        assert len(results) == 2
        result_keys = {r["key"] for r in results}
        assert result_keys == {"stale_by_usage_flag", "stale_by_config_flag"}
        for result in results:
            assert result["status"] == "STALE"


class TestFeatureFlagMatchingIds(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Clean up any existing flags to ensure test isolation
        FeatureFlag.objects.filter(team=self.team).delete()

    def test_matching_ids_returns_all_flags(self):
        # Create several flags
        flags = []
        for i in range(5):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
            )
            flags.append(flag)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert set(data["ids"]) == {f.id for f in flags}

    def test_matching_ids_respects_search_filter(self):
        # Create flags with different keys
        flag1 = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test_feature_a",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        flag2 = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test_feature_b",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="other_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/?search=test_feature")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert set(data["ids"]) == {flag1.id, flag2.id}

    def test_matching_ids_respects_active_filter(self):
        active_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="active_flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="inactive_flag",
            active=False,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/?active=true")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["ids"] == [active_flag.id]

    def test_matching_ids_excludes_archived_by_default(self):
        visible_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="visible_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        archived_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="archived_flag",
            archived=True,
            active=False,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Default: archived flag is absent from the "select all matching" set.
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/")
        assert response.status_code == 200
        ids = response.json()["ids"]
        assert visible_flag.id in ids
        assert archived_flag.id not in ids

        # ?archived=true returns only archived flags.
        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/?archived=true")
        assert response.status_code == 200
        assert response.json()["ids"] == [archived_flag.id]

    def test_matching_ids_excludes_deleted_flags(self):
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="active_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="deleted_flag",
            deleted=True,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["ids"] == [flag.id]

    def test_matching_ids_cross_project_isolation(self):
        # Create a flag in the current team
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="my_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Create another team and a flag there
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        FeatureFlag.objects.create(
            team=other_team,
            created_by=self.user,
            key="other_team_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["ids"] == [flag.id]

    def test_matching_ids_respects_type_filter(self):
        boolean_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="boolean_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="multivariate_flag",
            filters={
                "groups": [{"rollout_percentage": 50, "properties": []}],
                "multivariate": {
                    "variants": [
                        {"key": "a", "rollout_percentage": 50},
                        {"key": "b", "rollout_percentage": 50},
                    ]
                },
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/matching_ids/?type=boolean")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["ids"] == [boolean_flag.id]


class TestFeatureFlagBulkDelete(APIBaseTest):
    """Tests for the bulk_delete endpoint that accepts filter criteria or explicit IDs."""

    def setUp(self):
        super().setUp()
        # Clean up any existing flags to ensure test isolation
        FeatureFlag.objects.filter(team=self.team).delete()

    def test_bulk_delete_by_filter_with_search(self):
        """Test deleting flags matching a search term."""
        flag1 = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test_feature_a",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        flag2 = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test_feature_b",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        other_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="other_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"filters": {"search": "test_feature"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 2
        assert {d["id"] for d in data["deleted"]} == {flag1.id, flag2.id}
        assert len(data["errors"]) == 0

        # Verify flags are deleted
        flag1.refresh_from_db()
        flag2.refresh_from_db()
        other_flag.refresh_from_db()
        assert flag1.deleted is True
        assert flag2.deleted is True
        assert other_flag.deleted is False

    def test_bulk_delete_by_filter_with_active_status(self):
        """Test deleting only inactive flags."""
        active_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="active_flag",
            active=True,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        inactive_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="inactive_flag",
            active=False,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"filters": {"active": "false"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 1
        assert data["deleted"][0]["id"] == inactive_flag.id

        # Verify only inactive flag is deleted
        active_flag.refresh_from_db()
        inactive_flag.refresh_from_db()
        assert active_flag.deleted is False
        assert inactive_flag.deleted is True

    def test_bulk_delete_by_filter_excludes_archived_by_default(self):
        """An archived flag must not be deleted by a filter-based bulk delete, even when it
        matches the filter (archived flags are inactive, so an active=false filter matches them)."""
        archived_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="archived_inactive_flag",
            archived=True,
            active=False,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        inactive_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="plain_inactive_flag",
            active=False,
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"filters": {"active": "false"}},
        )

        assert response.status_code == 200
        archived_flag.refresh_from_db()
        inactive_flag.refresh_from_db()
        assert archived_flag.deleted is False
        assert inactive_flag.deleted is True

    def test_bulk_delete_by_ids_no_limit(self):
        """Test that ID-based deletion has no 100 limit (unlike the old endpoint)."""
        # Create 150 flags
        flags = []
        for i in range(150):
            flag = FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
            )
            flags.append(flag)

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [f.id for f in flags]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 150
        assert len(data["errors"]) == 0

    def test_bulk_delete_validates_running_experiments(self):
        """Test that flags linked to running experiments are rejected."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="experiment_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        Experiment.objects.create(
            team=self.team,
            name="Test Experiment",
            feature_flag=flag,
            created_by=self.user,
            start_date=now(),
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [flag.id]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 0
        assert len(data["errors"]) == 1
        # The error names the blocking experiment, matching the single-delete path's formatting.
        assert (
            'Cannot delete a feature flag linked to running experiment(s): "Test Experiment"'
            in (data["errors"][0]["reason"])
        )

        # Verify flag is NOT deleted
        flag.refresh_from_db()
        assert flag.deleted is False

    def test_bulk_delete_allows_flag_linked_to_stopped_experiment(self):
        """Flags linked to stopped/draft experiments can be deleted while preserving experiment history."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="stopped_experiment_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        Experiment.objects.create(
            team=self.team,
            name="Stopped Experiment",
            feature_flag=flag,
            created_by=self.user,
            start_date=now(),
            end_date=now(),
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [flag.id]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 1
        assert len(data["errors"]) == 0

        flag.refresh_from_db()
        assert flag.deleted is True
        # Key is freed up for reuse
        assert flag.key == f"stopped_experiment_flag:deleted:{flag.id}"

    def test_bulk_delete_requires_filters_or_ids(self):
        """Test validation error when neither filters nor ids provided."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {},
        )

        assert response.status_code == 400
        assert "Must provide either filters or ids" in response.json()["error"]

    def test_bulk_delete_rejects_both_filters_and_ids(self):
        """Test validation error when both filters and ids provided."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="test_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"filters": {"search": "test"}, "ids": [flag.id]},
        )

        assert response.status_code == 400
        assert "either filters or ids, not both" in response.json()["error"]

    def test_bulk_delete_cross_project_isolation(self):
        """Test that flags from other teams are not deleted."""
        # Create a flag in the current team
        my_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="my_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Create another team and a flag there
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_flag = FeatureFlag.objects.create(
            team=other_team,
            created_by=self.user,
            key="other_team_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Try to delete the other team's flag from our team's endpoint
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [my_flag.id, other_flag.id]},
        )

        assert response.status_code == 200
        data = response.json()
        # Only our flag should be deleted
        assert len(data["deleted"]) == 1
        assert data["deleted"][0]["id"] == my_flag.id

        # The other team's flag should be reported as not found
        assert len(data["errors"]) == 1
        assert data["errors"][0]["id"] == other_flag.id
        assert data["errors"][0]["reason"] == "Flag not found"

        # Verify the other team's flag is NOT deleted
        other_flag.refresh_from_db()
        assert other_flag.deleted is False

    def test_bulk_delete_by_filter_with_type(self):
        """Test deleting only boolean flags."""
        boolean_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="boolean_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        multivariate_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="multivariate_flag",
            filters={
                "groups": [{"rollout_percentage": 50, "properties": []}],
                "multivariate": {
                    "variants": [
                        {"key": "a", "rollout_percentage": 50},
                        {"key": "b", "rollout_percentage": 50},
                    ]
                },
            },
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"filters": {"type": "boolean"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 1
        assert data["deleted"][0]["id"] == boolean_flag.id

        # Verify only boolean flag is deleted
        boolean_flag.refresh_from_db()
        multivariate_flag.refresh_from_db()
        assert boolean_flag.deleted is True
        assert multivariate_flag.deleted is False

    def test_bulk_delete_includes_rollout_state(self):
        """Test that rollout_state and active_variant are included in delete responses."""
        # 100% boolean flag
        fully_rolled_out = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="fully_rolled_out",
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )
        # 0% rollout flag
        zero_rollout = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="zero_rollout",
            filters={"groups": [{"rollout_percentage": 0, "properties": []}]},
        )
        # Partial rollout flag
        partial = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="partial_rollout",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        # Multivariate flag with 100% rollout and active variant
        multivariate = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="multivariate_full",
            filters={
                "groups": [{"rollout_percentage": 100, "properties": [], "variant": "winner"}],
                "multivariate": {
                    "variants": [
                        {"key": "winner", "rollout_percentage": 100},
                        {"key": "loser", "rollout_percentage": 0},
                    ]
                },
            },
        )
        # Empty-variants block routes through the boolean branch: a 100% group is fully rolled out.
        empty_variants = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="empty_variants",
            filters={
                "groups": [{"rollout_percentage": 100, "properties": []}],
                "multivariate": {"variants": []},
            },
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {
                "ids": [
                    fully_rolled_out.id,
                    zero_rollout.id,
                    partial.id,
                    multivariate.id,
                    empty_variants.id,
                ]
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 5

        by_key = {d["key"]: d for d in data["deleted"]}

        assert by_key["fully_rolled_out"]["rollout_state"] == "fully_rolled_out"
        assert by_key["fully_rolled_out"]["active_variant"] is None

        assert by_key["zero_rollout"]["rollout_state"] == "not_rolled_out"
        assert by_key["zero_rollout"]["active_variant"] is None

        assert by_key["partial_rollout"]["rollout_state"] == "partial"
        assert by_key["partial_rollout"]["active_variant"] is None

        assert by_key["multivariate_full"]["rollout_state"] == "fully_rolled_out"
        assert by_key["multivariate_full"]["active_variant"] == "winner"

        assert by_key["empty_variants"]["rollout_state"] == "fully_rolled_out"
        assert by_key["empty_variants"]["active_variant"] is None

    def test_bulk_delete_with_dependent_flags(self):
        """Test that flags with dependents cannot be deleted."""
        # Create a flag that other flags depend on
        base_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="base_flag",
            filters={"groups": [{"rollout_percentage": 100, "properties": []}]},
        )
        # Create a flag that depends on the base flag
        FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="dependent_flag",
            filters={
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [{"key": str(base_flag.id), "type": "flag", "value": "true"}],
                    }
                ]
            },
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [base_flag.id]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 0
        assert len(data["errors"]) == 1
        assert "other flags depend on it" in data["errors"][0]["reason"]

        # Verify flag is not deleted
        base_flag.refresh_from_db()
        assert base_flag.deleted is False

    def test_bulk_delete_renames_key_with_soft_deleted_experiment(self):
        """Test that deleting a flag with a soft-deleted experiment renames the key."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="flag_with_deleted_exp",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag)
        exp.deleted = True
        exp.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [flag.id]},
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["deleted"]) == 1

        # Verify flag key is renamed
        flag.refresh_from_db()
        assert flag.deleted is True
        assert flag.key == f"flag_with_deleted_exp:deleted:{flag.id}"

    def test_bulk_delete_rejects_unknown_filter_keys(self):
        """Test that unknown filter keys are rejected to prevent accidental mass deletion."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"filters": {"invalid_key": "value", "another_bad_key": "test"}},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Unknown filter keys" in data["error"]
        assert "another_bad_key" in data["error"]
        assert "invalid_key" in data["error"]

    def test_bulk_delete_creates_activity_logs_for_all_deleted_flags(self):
        """Test that activity logs are created for each deleted flag."""
        from posthog.models.activity_logging.activity_log import ActivityLog

        flags = [
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
            )
            for i in range(5)
        ]
        flag_ids = {f.id for f in flags}

        # Clear any existing activity logs
        ActivityLog.objects.filter(team_id=self.team.id, scope="FeatureFlag").delete()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [f.id for f in flags]},
        )

        assert response.status_code == 200
        assert len(response.json()["deleted"]) == 5

        # Verify activity logs were created for each flag
        activity_logs = ActivityLog.objects.filter(team_id=self.team.id, scope="FeatureFlag", activity="deleted")
        assert activity_logs.count() == 5

        logged_item_ids = {int(log.item_id) for log in activity_logs if log.item_id is not None}
        assert logged_item_ids == flag_ids

        # Verify each log has the correct structure
        for log in activity_logs:
            assert log.user == self.user
            assert log.detail is not None
            assert log.detail.get("name") is not None

    def test_bulk_delete_sets_last_modified_by(self):
        """Test that last_modified_by is set to the requesting user for all deleted flags."""
        flags = [
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
                last_modified_by=None,
            )
            for i in range(3)
        ]

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [f.id for f in flags]},
        )

        assert response.status_code == 200
        assert len(response.json()["deleted"]) == 3

        # Verify last_modified_by is set on all flags
        for flag in flags:
            flag.refresh_from_db()
            assert flag.deleted is True
            assert flag.last_modified_by == self.user

    def test_bulk_delete_invalidates_cache_efficiently(self):
        """Test that cache invalidation happens once, not per flag."""
        flags = [
            FeatureFlag.objects.create(
                team=self.team,
                created_by=self.user,
                key=f"flag_{i}",
                filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
            )
            for i in range(10)
        ]

        # Mock on_commit to execute callbacks immediately (Django test transactions don't commit)
        # Patch at source module since the import happens inside the function
        with patch(
            "products.feature_flags.backend.api.feature_flag.transaction.on_commit", side_effect=lambda fn: fn()
        ):
            with patch(
                "products.feature_flags.backend.models.feature_flag.set_feature_flags_for_team_in_cache"
            ) as mock_cache:
                response = self.client.post(
                    f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
                    {"ids": [f.id for f in flags]},
                )

                assert response.status_code == 200
                assert len(response.json()["deleted"]) == 10

                # Cache should be invalidated only once, not 10 times
                assert mock_cache.call_count == 1

    def test_bulk_delete_handles_mixed_key_rename_scenarios(self):
        """Test bulk delete correctly handles mix of flags needing key rename and not."""
        # Flag without deleted experiment (no rename needed)
        normal_flag = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="normal_flag",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )

        # Flag with deleted experiment (rename needed)
        flag_with_deleted_exp = FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key="flag_with_deleted_exp",
            filters={"groups": [{"rollout_percentage": 50, "properties": []}]},
        )
        exp = Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag_with_deleted_exp)
        exp.deleted = True
        exp.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/bulk_delete/",
            {"ids": [normal_flag.id, flag_with_deleted_exp.id]},
        )

        assert response.status_code == 200
        assert len(response.json()["deleted"]) == 2

        # Verify normal flag keeps its key
        normal_flag.refresh_from_db()
        assert normal_flag.deleted is True
        assert normal_flag.key == "normal_flag"

        # Verify flag with deleted experiment has renamed key
        flag_with_deleted_exp.refresh_from_db()
        assert flag_with_deleted_exp.deleted is True
        assert flag_with_deleted_exp.key == f"flag_with_deleted_exp:deleted:{flag_with_deleted_exp.id}"


class TestFeatureFlagLimits(APIBaseTest):
    """Tests for feature flag creation and update limits."""

    def _create_flag(self, key: str, filters: Optional[dict] = None) -> FeatureFlag:
        """Helper to create a flag directly in the database."""
        if filters is None:
            filters = {"groups": [{"rollout_percentage": 100, "properties": []}]}
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=key,
            filters=filters,
        )

    def test_cannot_create_flag_when_team_exceeds_count_limit(self):
        # Create flags up to the limit
        self._create_flag("flag-1")
        self._create_flag("flag-2")
        self._create_flag("flag-3")

        # Attempting to create a new flag should fail
        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=3):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "key": "flag-4",
                    "filters": {"groups": [{"rollout_percentage": 100, "properties": []}]},
                },
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 3 feature flags allowed per team" in response.json()["detail"]

    def test_cannot_create_flag_without_filters_when_team_exceeds_count_limit(self):
        self._create_flag("flag-1")
        self._create_flag("flag-2")
        self._create_flag("flag-3")

        # Omitting filters should still enforce the count limit
        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=3):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {"key": "flag-4"},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 3 feature flags allowed per team" in response.json()["detail"]

    def test_can_update_existing_flag_when_team_at_count_limit(self):
        # Create flags up to the limit
        flag1 = self._create_flag("flag-1")
        self._create_flag("flag-2")

        # Updating an existing flag should succeed even at the limit
        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=2):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag1.id}",
                {"name": "Updated description"},
            )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Updated description"

    def test_deleted_flags_do_not_count_toward_limit(self):
        # Create two flags
        flag1 = self._create_flag("flag-1")
        self._create_flag("flag-2")

        # Soft-delete one
        flag1.deleted = True
        flag1.save()

        # Now we should be able to create a new flag
        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=2):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "key": "flag-3",
                    "filters": {"groups": [{"rollout_percentage": 100, "properties": []}]},
                },
            )

        assert response.status_code == status.HTTP_201_CREATED

    def test_per_flag_filter_size_limit_on_create(self):
        # Create a filter with many properties that exceeds 1KB
        properties = [
            {"key": f"prop_{i}", "type": "person", "value": f"value_{i}", "operator": "exact"} for i in range(50)
        ]
        with self.settings(MAX_FEATURE_FLAG_FILTER_SIZE_BYTES=1024):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "key": "large-flag",
                    "filters": {
                        "groups": [{"rollout_percentage": 100, "properties": properties}],
                    },
                },
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "exceed maximum size" in str(response.json())

    def test_per_flag_filter_size_limit_on_update(self):
        flag = self._create_flag("small-flag")

        properties = [
            {"key": f"prop_{i}", "type": "person", "value": f"value_{i}", "operator": "exact"} for i in range(50)
        ]
        with self.settings(MAX_FEATURE_FLAG_FILTER_SIZE_BYTES=1024):
            response = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{flag.id}",
                {
                    "filters": {
                        "groups": [{"rollout_percentage": 100, "properties": properties}],
                    }
                },
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "exceed maximum size" in str(response.json())

    def test_other_team_flags_do_not_count_toward_limit(self):
        other_team = Team.objects.create(
            organization=self.organization,
            api_token="token_other_team",
            name="Other Team",
        )
        # Create 2 flags for the other team directly in DB
        FeatureFlag.objects.create(team=other_team, created_by=self.user, key="other-1", filters={"groups": []})
        FeatureFlag.objects.create(team=other_team, created_by=self.user, key="other-2", filters={"groups": []})

        # Create 2 flags for our team
        self._create_flag("flag-1")
        self._create_flag("flag-2")

        # Should be able to create a 3rd flag for our team (limit is 3, we have 2)
        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=3):
            response = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags",
                {
                    "key": "flag-3",
                    "filters": {"groups": [{"rollout_percentage": 100, "properties": []}]},
                },
            )

        assert response.status_code == status.HTTP_201_CREATED

    def test_survey_creation_blocked_when_at_flag_limit(self):
        """Survey creation should fail when team is at the flag limit."""
        self._create_flag("flag-1")
        self._create_flag("flag-2")

        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=2):
            response = self.client.post(
                f"/api/projects/{self.team.id}/surveys",
                {
                    "name": "Test Survey",
                    "type": "popover",
                    "questions": [{"type": "open", "question": "Test?"}],
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 2 feature flags allowed per team" in str(response.json())

    def test_web_experiment_creation_blocked_when_at_flag_limit(self):
        """Web experiment creation should fail when team is at the flag limit."""
        self._create_flag("flag-1")
        self._create_flag("flag-2")

        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=2):
            response = self.client.post(
                f"/api/projects/{self.team.id}/web_experiments",
                {
                    "name": "Test Web Experiment",
                    "variants": {
                        "control": {"transforms": [], "rollout_percentage": 50},
                        "test": {"transforms": [], "rollout_percentage": 50},
                    },
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 2 feature flags allowed per team" in str(response.json())

    def test_product_tour_creation_blocked_when_at_flag_limit(self):
        """Product tour creation with auto_launch should fail when team is at the flag limit."""
        self._create_flag("flag-1")
        self._create_flag("flag-2")

        with self.settings(MAX_FEATURE_FLAGS_PER_TEAM=2):
            response = self.client.post(
                f"/api/projects/{self.team.id}/product_tours",
                {
                    "name": "Test Product Tour",
                    "auto_launch": True,
                    "content": {"steps": []},
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Maximum of 2 feature flags allowed per team" in str(response.json())


class TestFeatureFlagVersions(APIBaseTest):
    def _create_flag_via_api(self, key="test-flag", **kwargs):
        data = {
            "name": "Test Flag",
            "key": key,
            "filters": {"groups": [{"rollout_percentage": 100}]},
            **kwargs,
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags",
            data,
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()

    def _update_flag_via_api(self, flag_id, **kwargs):
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}",
            kwargs,
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def test_get_version_1_after_update(self):
        flag = self._create_flag_via_api(name="V1 Name")
        flag_id = flag["id"]

        self._update_flag_via_api(flag_id, name="V2 Name", version=flag["version"])

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/1/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["version"] == 1
        assert data["name"] == "V1 Name"
        assert data["is_historical"] is True
        assert data["id"] == flag_id

    def test_get_current_version(self):
        flag = self._create_flag_via_api(name="V1 Name")
        flag_id = flag["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/1/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["version"] == 1
        assert data["is_historical"] is False

    def test_version_not_found_returns_404(self):
        flag = self._create_flag_via_api()
        flag_id = flag["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/999/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_version_zero_returns_404(self):
        flag = self._create_flag_via_api()
        flag_id = flag["id"]

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/0/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_reconstruct_filters_change(self):
        v1_filters = {"groups": [{"rollout_percentage": 50}]}
        v2_filters = {
            "groups": [
                {
                    "rollout_percentage": 100,
                    "properties": [{"key": "email", "value": "test@example.com", "type": "person"}],
                }
            ]
        }

        flag = self._create_flag_via_api(filters=v1_filters)
        flag_id = flag["id"]

        self._update_flag_via_api(flag_id, filters=v2_filters, version=flag["version"])

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/1/")
        assert response.status_code == status.HTTP_200_OK

        data = response.json()
        assert data["filters"]["groups"][0]["rollout_percentage"] == 50

    def test_multiple_versions(self):
        flag = self._create_flag_via_api(name="V1")
        flag_id = flag["id"]

        updated = self._update_flag_via_api(flag_id, name="V2", version=flag["version"])
        self._update_flag_via_api(flag_id, name="V3", version=updated["version"])

        v1 = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/1/").json()
        v2 = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/2/").json()
        v3 = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/3/").json()

        assert v1["name"] == "V1"
        assert v1["is_historical"] is True
        assert v2["name"] == "V2"
        assert v2["is_historical"] is True
        assert v3["name"] == "V3"
        assert v3["is_historical"] is False

    def test_incomplete_history_returns_422(self):
        flag = self._create_flag_via_api()
        flag_id = flag["id"]

        FeatureFlag.objects.filter(id=flag_id).update(version=5)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/2/")
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "incomplete" in response.json()["detail"].lower()

    @parameterized.expand(
        [
            ("remote_configuration", {"is_remote_configuration": True}),
            ("encrypted_payloads", {"has_encrypted_payloads": True}),
        ]
    )
    def test_unsupported_flag_returns_400(self, _name, update_kwargs):
        flag = self._create_flag_via_api()
        flag_id = flag["id"]

        FeatureFlag.objects.filter(id=flag_id).update(**update_kwargs)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/versions/1/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "not available" in response.json()["detail"].lower()


class TestFeatureFlagTestEvaluation(APIBaseTest, ClickhouseTestMixin):
    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @patch("products.feature_flags.backend.api.feature_flag.get_person_and_distinct_ids_for_identifier")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_happy_path(self, mock_get_person, mock_get_flags):
        """Test successful evaluation of a feature flag."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [{"key": "email", "type": "person", "value": "test@example.com"}]}]},
        )
        person = create_person(team=self.team, distinct_ids=["test-user"], properties={"email": "test@example.com"})

        # Mock person lookup
        mock_get_person.return_value = (person, ["test-user"])

        # Mock successful flag evaluation response
        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": True,
                    "variant": None,
                    "reason": {"code": "condition_match", "condition_index": 0},
                    "metadata": {"payload": None},
                    "conditions": [
                        {
                            "index": 0,
                            "matched": True,
                            "explanation": "Condition matched",
                            "rollout_percentage": 100.0,
                            "rollout_excluded": False,
                            "variant": None,
                            "properties": [],
                        }
                    ],
                }
            }
        }

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["flag_key"], "test-flag")
        self.assertEqual(data["result"], True)
        self.assertEqual(data["reason"], "condition_match")
        self.assertEqual(data["condition_index"], 0)
        self.assertIsInstance(data["person_properties"], dict)
        # Caller-provided distinct_id resolves to the person → it must drive bucketing.
        self.assertEqual(data["evaluation_distinct_id"], "test-user")
        self.assertEqual(mock_get_flags.call_args.kwargs["distinct_id"], "test-user")

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @patch("products.feature_flags.backend.api.feature_flag.get_person_and_distinct_ids_for_identifier")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_with_person_id_uses_smallest_distinct_id(self, mock_get_person, mock_get_flags):
        """When the caller passes person_id (no distinct_id), bucketing must
        pick the lexicographically smallest distinct_id so two calls with the
        same person_id are deterministic — proto_person_to_model / the ORM
        don't guarantee a stable order. The response must NOT echo the chosen
        distinct_id back, otherwise feature_flag:read tokens could enumerate
        distinct_ids for any person UUID."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")
        person = create_person(team=self.team, distinct_ids=["zzz", "aaa", "mmm"])

        # Hand the resolver back distinct_ids in deliberately non-sorted order
        # to prove the sort happens in feature_flag.py, not upstream.
        mock_get_person.return_value = (person, ["zzz", "aaa", "mmm"])

        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": False,
                    "variant": None,
                    "reason": {"code": "no_condition_match"},
                    "metadata": {},
                    "conditions": [],
                }
            }
        }

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"person_id": str(person.uuid)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Bucketing still uses the resolved smallest distinct_id...
        self.assertEqual(mock_get_flags.call_args.kwargs["distinct_id"], "aaa")
        # ...but the response must NOT leak it back to the caller.
        self.assertIsNone(response.json()["evaluation_distinct_id"])

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_with_timestamp(self, mock_get_flags):
        """Historical evaluation must drive the Rust call with reconstructed
        person properties + override definitions, not the live flag's data."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [{"key": "email", "type": "person", "value": "x"}]}]},
            bucketing_identifier="device_id",
            evaluation_runtime="server",
            ensure_experience_continuity=True,
        )

        create_person(team=self.team, distinct_ids=["test-user"])

        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": False,
                    "variant": None,
                    "reason": {"code": "no_condition_match"},
                    "metadata": {},
                    "conditions": [],
                }
            }
        }

        with patch(
            "products.feature_flags.backend.api.feature_flag.build_person_properties_at_time"
        ) as mock_build_props:
            mock_build_props.return_value = {"email": "historical@example.com"}

            # Use a recent timestamp that's after flag creation
            from datetime import datetime

            recent_timestamp = datetime.now(UTC).isoformat()

            response = self.client.post(
                f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
                {"distinct_id": "test-user", "timestamp": recent_timestamp},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_build_props.assert_called_once()

        # Build was given the requested timestamp and the resolved distinct_ids,
        # so the historical props lookup actually targeted the right window/person.
        _, build_kwargs = mock_build_props.call_args
        self.assertEqual(build_kwargs["distinct_ids"], ["test-user"])
        self.assertTrue(build_kwargs["include_set_once"])
        self.assertEqual(build_kwargs["timestamp"].isoformat(), recent_timestamp)

        # The whole point of the timestamp branch: the Rust call must use
        # the reconstructed person_properties, not the live person row, and
        # must include the historical override definition keyed by flag key.
        _, get_flags_kwargs = mock_get_flags.call_args
        self.assertTrue(get_flags_kwargs["only_use_override_person_properties"])
        self.assertEqual(get_flags_kwargs["person_properties"], {"email": "historical@example.com"})
        self.assertIn("test-flag", get_flags_kwargs["override_flags_definitions"])
        self.assertEqual(get_flags_kwargs["override_flags_definitions"]["test-flag"]["id"], flag.id)
        self.assertEqual(get_flags_kwargs["override_flags_definitions"]["test-flag"]["team_id"], self.team.pk)
        self.assertEqual(get_flags_kwargs["override_flags_definitions"]["test-flag"]["key"], "test-flag")
        self.assertEqual(
            get_flags_kwargs["override_flags_definitions"]["test-flag"]["bucketing_identifier"], "device_id"
        )
        self.assertEqual(get_flags_kwargs["override_flags_definitions"]["test-flag"]["evaluation_runtime"], "server")
        self.assertEqual(
            get_flags_kwargs["override_flags_definitions"]["test-flag"]["ensure_experience_continuity"], True
        )

        # Filtered person_properties in the response only carry keys referenced
        # by the (reconstructed) flag's conditions.
        self.assertEqual(response.json()["person_properties"], {"email": "historical@example.com"})

    def test_test_evaluation_distinct_id_person_id_conflict(self):
        """Test validation error when both distinct_id and person_id are provided."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user", "person_id": "123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot provide both distinct_id and person_id", response.json()["detail"])

    def test_test_evaluation_person_not_found(self):
        """Test 404 when person doesn't exist."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "nonexistent-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()["detail"], "Person not found for distinct_id: nonexistent-user")

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="")
    def test_test_evaluation_missing_internal_token_error(self, mock_get_flags):
        """Test 500 when INTERNAL_REQUEST_TOKEN is not set."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")
        create_person(team=self.team, distinct_ids=["test-user"])

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()["error"], "Internal request token not configured")

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_historical_missing_conditions_502(self, mock_get_flags):
        """Test 502 when historical evaluation returns no conditions (misconfigured token)."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")
        create_person(team=self.team, distinct_ids=["test-user"])

        # Mock service to return flag dict without 'conditions' key - indicates token issue
        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": False,
                    "variant": None,
                    "reason": {"code": "no_condition_match"},
                    "metadata": {},
                    # Missing 'conditions' key indicates token misconfiguration
                }
            }
        }

        with patch("products.feature_flags.backend.api.feature_flag.build_person_properties_at_time", return_value={}):
            # Use a recent timestamp that's after flag creation
            from datetime import datetime

            recent_timestamp = datetime.now(UTC).isoformat()

            response = self.client.post(
                f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
                {"distinct_id": "test-user", "timestamp": recent_timestamp},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.json()["error"], "Historical evaluation unavailable. Check service configuration.")

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_current_missing_conditions_200(self, mock_get_flags):
        """Test 200 when current evaluation returns no conditions (no 502 for current evaluation)."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")
        create_person(team=self.team, distinct_ids=["test-user"])

        # Mock service to return flag dict without 'conditions' key
        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": False,
                    "variant": None,
                    "reason": {"code": "no_condition_match"},
                    "metadata": {},
                    # Missing 'conditions' key - should not cause 502 for current evaluation
                }
            }
        }

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user"},
            # No timestamp = current evaluation
            format="json",
        )

        # The key test: current evaluation should not return 502 even with missing conditions
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify the response is still valid
        self.assertIn("result", response.json())

    @patch("products.feature_flags.backend.api.feature_flag.build_person_properties_at_time")
    def test_test_evaluation_build_properties_failure(self, mock_build_props):
        """Test 500 when build_person_properties_at_time raises exception."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")
        create_person(team=self.team, distinct_ids=["test-user"])

        # Mock exception during property building
        mock_build_props.side_effect = Exception("Database error")

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user", "timestamp": "2023-01-01T00:00:00Z"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.json()["error"], "Failed to build person properties at specified timestamp.")

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_filters_person_properties(self, mock_get_flags):
        """Test that person_properties are filtered to only flag-referenced keys."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [{"key": "email", "type": "person", "value": "test@example.com"}]}]},
        )
        create_person(
            team=self.team,
            distinct_ids=["test-user"],
            properties={"email": "test@example.com", "name": "Test User", "age": 30},
        )

        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": True,
                    "variant": None,
                    "reason": {"code": "condition_match"},
                    "metadata": {},
                    "conditions": [
                        {
                            "index": 0,
                            "matched": True,
                            "explanation": "Condition matched",
                            "rollout_percentage": 100.0,
                            "rollout_excluded": False,
                            "variant": None,
                            "properties": [],
                        }
                    ],
                }
            }
        }

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Should only include 'email' since that's referenced in the flag, not 'name' or 'age'
        self.assertEqual(data["person_properties"], {"email": "test@example.com"})

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_filters_feature_enrollment_property(self, mock_get_flags):
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="enroll-flag",
            filters={"feature_enrollment": True, "groups": [{"properties": []}]},
        )
        enrollment_key = f"$feature_enrollment/{flag.key}"
        create_person(
            team=self.team,
            distinct_ids=["test-user"],
            properties={enrollment_key: True, "email": "x@y.com"},
        )

        mock_get_flags.return_value = {
            "flags": {
                "enroll-flag": {
                    "enabled": True,
                    "variant": None,
                    "reason": {"code": "super_condition_value"},
                    "metadata": {},
                    "conditions": [],
                }
            }
        }

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # enrollment key is kept; unrelated 'email' is filtered out
        self.assertEqual(data["person_properties"], {enrollment_key: True})

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_unexpected_response_type(self, mock_get_flags):
        """Test 502 when flag service returns unexpected response format."""
        flag = FeatureFlag.objects.create(team=self.team, key="test-flag")
        create_person(team=self.team, distinct_ids=["test-user"])

        # Mock unexpected response format (not a dict)
        mock_get_flags.return_value = {"flags": {"test-flag": "unexpected_string"}}

        response = self.client.post(
            f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
            {"distinct_id": "test-user"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.json()["error"], "Unexpected response format from flag evaluation service")

    def test_test_evaluation_missing_distinct_id(self):
        """Test validation error when distinct_id is missing."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Flag",
            key="test-flag",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/test_evaluation/",
            data={"flag_key": "test-flag"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_test_evaluation_invalid_timestamp(self):
        """Test validation error with invalid timestamp format."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Flag",
            key="test-flag",
            created_by=self.user,
        )

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/test_evaluation/",
            data={"distinct_id": "user123", "flag_key": "test-flag", "timestamp": "invalid"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_build_properties_value_error_no_leak(self, mock_get_flags):
        """Test that ValueError from build_person_properties_at_time doesn't leak sensitive information."""
        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": False,
                    "variant": None,
                    "reason": {"code": "no_condition_match"},
                    "metadata": {},
                    "conditions": [],
                }
            }
        }

        flag = FeatureFlag.objects.create(
            team=self.team,
            key="test-flag",
            filters={"groups": [{"properties": [{"key": "email", "type": "person", "value": "x"}]}]},
            bucketing_identifier="device_id",
            evaluation_runtime="server",
            ensure_experience_continuity=True,
        )

        create_person(team=self.team, distinct_ids=["test-user"])

        with patch(
            "products.feature_flags.backend.api.feature_flag.build_person_properties_at_time"
        ) as mock_build_props:
            # Mock build_person_properties_at_time to raise ValueError with sensitive information
            mock_build_props.side_effect = ValueError("naive datetime: /secret/path/user123")

            # Use a recent timestamp that's after flag creation
            recent_timestamp = datetime.now(UTC).isoformat()

            response = self.client.post(
                f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
                {"distinct_id": "test-user", "timestamp": recent_timestamp},
                format="json",
            )

        # Should return 400 with generic message
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Invalid timestamp format.")

        # Ensure the sensitive information doesn't leak into the response
        response_content = response.content.decode()
        self.assertNotIn("secret", response_content.lower())
        self.assertNotIn("/secret/path/user123", response_content)
        self.assertNotIn("naive datetime", response_content)

        # Verify the mock was called
        mock_build_props.assert_called_once()

    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    @override_settings(INTERNAL_REQUEST_TOKEN="test-token")
    def test_test_evaluation_reconstruct_flag_value_error_no_leak(self, mock_get_flags):
        """Test that ValueError from reconstruct_flag_at_timestamp doesn't leak sensitive information."""
        flag = FeatureFlag.objects.create(
            team=self.team,
            name="Test Flag",
            key="test-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        create_person(team=self.team, distinct_ids=["test-user"])
        mock_get_flags.return_value = {
            "flags": {
                "test-flag": {
                    "enabled": False,
                    "variant": None,
                    "reason": {"code": "no_condition_match"},
                    "metadata": {},
                    "conditions": [],
                }
            }
        }

        with patch("products.feature_flags.backend.api.feature_flag.reconstruct_flag_at_timestamp") as mock_reconstruct:
            # Mock reconstruct_flag_at_timestamp to raise ValueError with sensitive information
            mock_reconstruct.side_effect = ValueError("timestamp must be timezone-aware: /secret/config/token")

            # Use a recent timestamp that's after flag creation
            recent_timestamp = datetime.now(UTC).isoformat()

            response = self.client.post(
                f"/api/projects/{self.team.pk}/feature_flags/{flag.id}/test_evaluation/",
                {"distinct_id": "test-user", "timestamp": recent_timestamp},
                format="json",
            )

        # Should return 400 with generic message
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data["error"], "Invalid timestamp.")

        # Ensure the sensitive information doesn't leak into the response
        response_content = response.content.decode()
        self.assertNotIn("secret", response_content.lower())
        self.assertNotIn("/secret/config/token", response_content)
        self.assertNotIn("timezone-aware", response_content)

        # Verify the mock was called
        mock_reconstruct.assert_called_once()


class TestFeatureFlagEvaluationReasons(APIBaseTest, ClickhouseTestMixin):
    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    def test_evaluation_reasons_passes_runtime_all(self, mock_get_flags):
        """The Person → Feature flags tab must bypass Rust's header-based
        runtime detection — otherwise flags whose evaluation_runtime is
        "client" or "server" disappear from the tab."""
        mock_get_flags.return_value = {"flags": {}}

        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags/evaluation_reasons/",
            {"distinct_id": "user-1"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(mock_get_flags.call_args.kwargs["evaluation_runtime"], "all")

    @parameterized.expand(
        [
            ("all",),
            ("client",),
            ("server",),
        ]
    )
    @patch("products.feature_flags.backend.api.feature_flag.get_flags_from_service")
    def test_evaluation_reasons_surfaces_flag_for_runtime(self, runtime, mock_get_flags):
        """Each stored runtime must round-trip through evaluation_reasons with
        its evaluation.reason intact — this is the shape
        relatedFeatureFlagsLogic.ts depends on."""
        flag = FeatureFlag.objects.create(team=self.team, key=f"flag-{runtime}", evaluation_runtime=runtime)
        mock_get_flags.return_value = {
            "flags": {
                flag.key: {
                    "enabled": True,
                    "variant": None,
                    "reason": {"code": "condition_match", "condition_index": 0},
                },
            }
        }

        response = self.client.get(
            f"/api/projects/{self.team.pk}/feature_flags/evaluation_reasons/",
            {"distinct_id": "user-1"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn(flag.key, data)
        self.assertEqual(data[flag.key]["evaluation"]["reason"], "condition_match")
