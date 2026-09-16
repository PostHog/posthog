from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.tasks.health_checks import evaluate_health_check_for_team
from posthog.temporal.health_checks.processing import _process_batch_detection
from posthog.temporal.health_checks.registry import HEALTH_CHECKS, ensure_registry_loaded

from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.flag_status import ROLLOUT_FULLY_ROLLED_OUT, ROLLOUT_NOT_ROLLED_OUT, ROLLOUT_PARTIAL
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.temporal.health_checks.stale_flags import (
    EVIDENCE_EFFECTIVELY_FULL_ROLLOUT,
    EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA,
    EVIDENCE_NOT_CALLED_RECENTLY,
    StaleFeatureFlagsCheck,
)
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

FULL_ROLLOUT_FILTERS = {"groups": [{"properties": [], "rollout_percentage": 100}]}


def stale_by_config() -> dict[str, Any]:
    return {"created_at": timezone.now() - timedelta(days=60), "filters": FULL_ROLLOUT_FILTERS}


def stale_by_usage() -> dict[str, Any]:
    return {
        "last_called_at": timezone.now() - timedelta(days=45),
        "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
    }


def constant_and_called() -> dict[str, Any]:
    return {**stale_by_config(), "last_called_at": timezone.now()}


class TestStaleFlagsDetect(BaseTest):
    def _create_flag(self, key: str, **kwargs: Any) -> FeatureFlag:
        kwargs.setdefault("active", True)
        return FeatureFlag.objects.create(team=self.team, key=key, created_by=self.user, **kwargs)

    def _detect(self, team_ids: list[int] | None = None) -> dict[int, list]:
        return StaleFeatureFlagsCheck().detect(team_ids or [self.team.id])

    def _create_dependent_flag(self, key: str, dependency: FeatureFlag, **kwargs: Any) -> FeatureFlag:
        return self._create_flag(
            key,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "type": "flag",
                                "key": str(dependency.id),
                                "operator": "flag_evaluates_to",
                                "value": True,
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
            **kwargs,
        )

    def _link(self, link: str, flag: FeatureFlag) -> None:
        if link == "survey_targeting":
            Survey.objects.create(team=self.team, name="s", type="popover", targeting_flag=flag)
        elif link == "survey_linked":
            Survey.objects.create(team=self.team, name="s", type="popover", linked_flag=flag)
        elif link == "product_tour":
            ProductTour.objects.create(team=self.team, name="t", content={"steps": []}, internal_targeting_flag=flag)
        elif link == "child_environment_product_tour":
            # A tour row keeps the environment it was created on, while the flag belongs to the
            # project root team, so the tour's team id is never a candidate team id.
            child_environment = Team.objects.create(
                organization=self.organization, project=self.project, parent_team=self.team, name="child env"
            )
            ProductTour.objects.create(
                team=child_environment, name="t", content={"steps": []}, internal_targeting_flag=flag
            )
        elif link == "archived_product_tour":
            ProductTour.all_objects.create(
                team=self.team, name="t", content={"steps": []}, internal_targeting_flag=flag, archived=True
            )
        elif link == "experiment":
            Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag)
        elif link == "deleted_experiment":
            Experiment.objects.create(team=self.team, created_by=self.user, feature_flag=flag, deleted=True)
        elif link == "early_access_feature":
            EarlyAccessFeature.objects.create(team=self.team, name="f", stage="beta", feature_flag=flag)
        elif link == "dependent_flag":
            self._create_dependent_flag("dependent-on-candidate", flag)
        elif link == "disabled_dependent_flag":
            self._create_dependent_flag("disabled-dependent", flag, active=False)
        elif link == "replay_link":
            # Queryset update instead of save so no Team receivers run in the fixture.
            Team.objects.filter(pk=self.team.pk).update(session_recording_linked_flag={"id": flag.id, "key": flag.key})
        else:
            raise ValueError(link)

    @parameterized.expand(
        [
            ("recently_evaluated", {"last_called_at": timezone.now() - timedelta(days=5)}, None, False),
            ("stale_by_usage", stale_by_usage(), None, True),
            ("stale_by_config", stale_by_config(), None, True),
            ("young_without_usage", {"filters": FULL_ROLLOUT_FILTERS}, None, False),
            ("disabled", {**stale_by_usage(), "active": False}, None, False),
            # The archived_flag_must_be_disabled DB constraint forces active=False here.
            ("archived", {**stale_by_usage(), "archived": True, "active": False}, None, False),
            ("soft_deleted", {**stale_by_usage(), "deleted": True}, None, False),
            ("remote_config", {**stale_by_config(), "is_remote_configuration": True}, None, False),
            # The column is nullable; a NULL row is not remote config and must stay reportable.
            ("remote_config_null_still_reported", {**stale_by_config(), "is_remote_configuration": None}, None, True),
            ("survey_targeting_flag", stale_by_config(), "survey_targeting", False),
            ("survey_user_linked_flag", stale_by_config(), "survey_linked", True),
            ("product_tour_internal_flag", stale_by_config(), "product_tour", False),
            ("archived_product_tour_still_blocks", stale_by_config(), "archived_product_tour", False),
            ("child_environment_product_tour_blocks", stale_by_config(), "child_environment_product_tour", False),
            ("experiment_linked", stale_by_config(), "experiment", False),
            ("deleted_experiment_does_not_block", stale_by_config(), "deleted_experiment", True),
            ("early_access_feature_flag", stale_by_config(), "early_access_feature", False),
            ("depended_on_by_active_flag", stale_by_usage(), "dependent_flag", False),
            # Local-evaluation semantics: a disabled dependent still protects its dependency.
            ("disabled_dependent_still_blocks", stale_by_usage(), "disabled_dependent_flag", False),
            ("replay_linked", stale_by_config(), "replay_link", False),
            # The cases below read filter_effectively_full_rollout_flags, which classifies rollout
            # completeness and not staleness. No flag becomes STALE to either side because of it,
            # so test_stale_filter_agrees_with_status_checker in
            # products/feature_flags/backend/test/test_flag_status.py still holds.
            # Fully rolled out and still called every day: outside both filter_stale_flags branches.
            ("constant_and_still_called", constant_and_called(), None, True),
            # The exclusions run over both candidate sources, not just the stale one.
            ("constant_and_still_called_blocked_by_experiment", constant_and_called(), "experiment", False),
            # Legacy shape: an absent properties key is no targeting, which is what
            # is_group_fully_rolled_out reads and what the SQL prefilter has to let through.
            (
                "constant_with_properties_key_absent",
                {**constant_and_called(), "filters": {"groups": [{"rollout_percentage": 100}]}},
                None,
                True,
            ),
            # Never called and legacy-shaped. Both candidate queries match it, so the overlap
            # exclusion is what stops it being reported twice under one hash key.
            (
                "legacy_shape_never_called",
                {**stale_by_config(), "filters": {"groups": [{"rollout_percentage": 100}]}},
                None,
                True,
            ),
            # Legacy shape: `properties` stored as JSON null is no targeting, which neither the
            # `IS NULL` arm nor the literal `[]` arm of the prefilter matches on its own.
            (
                "constant_with_null_properties",
                {**constant_and_called(), "filters": {"groups": [{"rollout_percentage": 100, "properties": None}]}},
                None,
                True,
            ),
            (
                "constant_but_targeted",
                {
                    **constant_and_called(),
                    "filters": {
                        "groups": [{"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 100}]
                    },
                },
                None,
                False,
            ),
            # The model default is fully rolled out to the checker, so only the SQL keeps every
            # unconfigured flag out of the report.
            ("constant_with_no_release_conditions", {**constant_and_called(), "filters": {"groups": []}}, None, False),
            (
                "constant_but_younger_than_threshold",
                {**constant_and_called(), "created_at": timezone.now()},
                None,
                False,
            ),
            (
                "multivariate_winner_still_called",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                None,
                True,
            ),
            # The SQL prefilter matches this on its 100% release condition; only the checker
            # confirmation keeps a flag that still splits traffic between variants out.
            (
                "multivariate_without_winner_still_called",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 50},
                                {"key": "test", "rollout_percentage": 50},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                None,
                False,
            ),
            # A holdout is resolved before the release conditions, so part of the population never
            # reaches the 100% group the prefilter matched. The checker never reads the key.
            (
                "constant_and_called_behind_holdout",
                {
                    **constant_and_called(),
                    "filters": {**FULL_ROLLOUT_FILTERS, "holdout": {"id": 1, "exclusion_percentage": 10}},
                },
                None,
                False,
            ),
            # Group aggregation, device-id bucketing and feature enrollment decide the result from
            # evaluation context the configuration does not carry, so the blanket condition does not
            # reach everyone.
            (
                "constant_but_group_aggregated",
                {**constant_and_called(), "filters": {**FULL_ROLLOUT_FILTERS, "aggregation_group_type_index": 0}},
                None,
                False,
            ),
            (
                "constant_but_condition_group_aggregated",
                {
                    **constant_and_called(),
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100, "aggregation_group_type_index": 0}]
                    },
                },
                None,
                False,
            ),
            # An explicit null index means person aggregation, so it must not be read as a group.
            (
                "constant_with_null_aggregation_index",
                {
                    **constant_and_called(),
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100, "aggregation_group_type_index": None}]
                    },
                },
                None,
                True,
            ),
            (
                "constant_but_device_id_bucketed",
                {**constant_and_called(), "bucketing_identifier": "device_id"},
                None,
                False,
            ),
            (
                "constant_but_feature_enrollment",
                {**constant_and_called(), "filters": {**FULL_ROLLOUT_FILTERS, "feature_enrollment": True}},
                None,
                False,
            ),
            # The matcher ignores an override naming a variant the flag does not configure, so the
            # distribution decides and a split one is not constant.
            (
                "constant_but_unknown_variant_override",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "a", "rollout_percentage": 50},
                                {"key": "b", "rollout_percentage": 50},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100, "variant": "ghost"}],
                    },
                },
                None,
                False,
            ),
            # A legacy scalar `groups` makes jsonb_array_elements raise, which aborts the statement
            # for every team in the batch rather than skipping the row.
            (
                "legacy_scalar_groups_does_not_abort_the_batch",
                {**constant_and_called(), "filters": {"groups": "all"}},
                None,
                False,
            ),
            # A targeted condition declared before the blanket one decides the result for the users
            # it matches, so the cohort it pins to "test" never receives the named winner.
            (
                "constant_but_targeted_variant_override_first",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 100},
                                {"key": "test", "rollout_percentage": 0},
                            ]
                        },
                        "groups": [
                            {
                                "properties": [{"key": "email", "value": "x"}],
                                "rollout_percentage": 100,
                                "variant": "test",
                            },
                            {"properties": [], "rollout_percentage": 100},
                        ],
                    },
                },
                None,
                False,
            ),
            # Variants take cumulative slices in order, so the 40 still owns the low hashes and the
            # flag serves two variants despite the 100.
            (
                "constant_but_variants_overallocated",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 40},
                                {"key": "test", "rollout_percentage": 100},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                None,
                False,
            ),
            # The same pair the other way round is constant: nothing takes a hash before the 100.
            (
                "constant_when_the_hundred_comes_first",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 100},
                                {"key": "test", "rollout_percentage": 40},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                None,
                True,
            ),
            # `early_exit` returns false on a failed rollout check instead of falling through to the
            # blanket group, so the configuration can serve two results.
            (
                "constant_and_called_with_early_exit",
                {
                    **constant_and_called(),
                    "filters": {
                        "groups": [
                            {"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 50},
                            {"properties": [], "rollout_percentage": 100},
                        ],
                        "early_exit": True,
                    },
                },
                None,
                False,
            ),
        ]
    )
    def test_detect_inclusion_and_exclusion(
        self, key: str, flag_kwargs: dict[str, Any], link: str | None, expected_included: bool
    ) -> None:
        flag = self._create_flag(key, **flag_kwargs)
        if link is not None:
            self._link(link, flag)

        results = self._detect()

        included = any(result.payload["flag_id"] == flag.id for result in results.get(self.team.id, []))
        assert included is expected_included

    # (name, flag_kwargs, expected payload subset)
    @parameterized.expand(
        [
            (
                "full_rollout_without_usage_data",
                stale_by_config(),
                {
                    "evidence_class": EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA,
                    "rollout_state": ROLLOUT_FULLY_ROLLED_OUT,
                    "days_since_evidence": 60,
                    "has_targeting_conditions": False,
                    "max_rollout_percentage": 100,
                    "winning_variant": None,
                },
            ),
            (
                "not_rolled_out_by_usage",
                {
                    "last_called_at": timezone.now() - timedelta(days=45),
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 0}]},
                },
                {
                    "evidence_class": EVIDENCE_NOT_CALLED_RECENTLY,
                    "rollout_state": ROLLOUT_NOT_ROLLED_OUT,
                    "days_since_evidence": 45,
                },
            ),
            (
                "partial_by_usage",
                stale_by_usage(),
                {"evidence_class": EVIDENCE_NOT_CALLED_RECENTLY, "rollout_state": ROLLOUT_PARTIAL},
            ),
            (
                "targeted_full_rollout_is_partial",
                {
                    "last_called_at": timezone.now() - timedelta(days=45),
                    "filters": {
                        "groups": [
                            {"properties": [{"key": "email", "value": "x"}], "rollout_percentage": 100},
                        ]
                    },
                },
                {"rollout_state": ROLLOUT_PARTIAL, "has_targeting_conditions": True, "max_rollout_percentage": 100},
            ),
            (
                "effectively_full_rollout_while_called",
                constant_and_called(),
                {
                    "evidence_class": EVIDENCE_EFFECTIVELY_FULL_ROLLOUT,
                    "rollout_state": ROLLOUT_FULLY_ROLLED_OUT,
                    # The evidence is the configuration, so the date is the flag's age, not its
                    # last call.
                    "days_since_evidence": 60,
                    "has_targeting_conditions": False,
                    "max_rollout_percentage": 100,
                    "winning_variant": None,
                },
            ),
            (
                "multivariate_winning_variant",
                {
                    "created_at": timezone.now() - timedelta(days=60),
                    "filters": {
                        "multivariate": {"variants": [{"key": "control", "rollout_percentage": 100}]},
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                {
                    "evidence_class": EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA,
                    "rollout_state": ROLLOUT_FULLY_ROLLED_OUT,
                    "winning_variant": "control",
                },
            ),
        ]
    )
    def test_payload_evidence_and_rollout(
        self, key: str, flag_kwargs: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        flag = self._create_flag(key, name="Flag under test", **flag_kwargs)

        results = self._detect()

        # One result per flag, not the first of several: a flag both candidate sources return
        # would otherwise report twice under whichever evidence class happened to come first.
        (result,) = [r for r in results[self.team.id] if r.payload["flag_id"] == flag.id]
        assert result.severity == HealthIssue.Severity.INFO
        assert result.hash_keys == ["flag_id"]
        assert result.payload["flag_key"] == key
        assert result.payload["flag_name"] == "Flag under test"
        assert result.payload["flag_version"] == flag.version
        for field, value in expected.items():
            assert result.payload[field] == value, field

    def test_payload_truncates_flag_name(self) -> None:
        flag = self._create_flag("long-name", name="x" * 600, **stale_by_usage())

        results = self._detect()

        result = next(r for r in results[self.team.id] if r.payload["flag_id"] == flag.id)
        assert result.payload["flag_name"] == "x" * 500

    def test_manual_refresh_task_honors_dry_run(self) -> None:
        self._create_flag("manual-refresh", **stale_by_usage())

        evaluate_health_check_for_team(kind="stale_feature_flags", team_id=self.team.id)

        assert not HealthIssue.objects.filter(team=self.team, kind="stale_feature_flags").exists()

    def test_batches_multiple_teams(self) -> None:
        team_two = Team.objects.create(organization=self.organization, name="two")
        healthy_team = Team.objects.create(organization=self.organization, name="healthy")
        self._create_flag("first", **stale_by_usage())
        self._create_flag("second", **stale_by_config())
        FeatureFlag.objects.create(team=team_two, key="third", created_by=self.user, active=True, **stale_by_usage())
        # A blocker on the second team proves the exclusion lookups cover the whole batch,
        # not just the first team.
        blocked = FeatureFlag.objects.create(
            team=team_two, key="blocked", created_by=self.user, active=True, **stale_by_usage()
        )
        Team.objects.filter(pk=team_two.pk).update(session_recording_linked_flag={"id": blocked.id, "key": blocked.key})

        results = self._detect([self.team.id, team_two.id, healthy_team.id])

        assert set(results) == {self.team.id, team_two.id}
        assert len(results[self.team.id]) == 2
        assert len(results[team_two.id]) == 1
        assert results[team_two.id][0].payload["flag_id"] != blocked.id

    def test_query_count_does_not_grow_with_candidates_or_teams(self) -> None:
        self._create_flag("baseline", **stale_by_usage())
        check = StaleFeatureFlagsCheck()

        with CaptureQueriesContext(connection) as before:
            check.detect([self.team.id])

        FeatureFlag.objects.bulk_create(
            FeatureFlag(
                team=self.team,
                key=f"bulk-stale-{index}",
                active=True,
                created_at=timezone.now() - timedelta(days=60),
                filters=FULL_ROLLOUT_FILTERS,
                created_by=self.user,
            )
            for index in range(20)
        )
        other_team = Team.objects.create(organization=self.organization, name="other")
        FeatureFlag.objects.create(
            team=other_team, key="other-stale", created_by=self.user, active=True, **stale_by_usage()
        )

        with CaptureQueriesContext(connection) as after:
            results = check.detect([self.team.id, other_team.id])

        assert len(results[self.team.id]) == 21
        assert len(results[other_team.id]) == 1
        assert len(after) == len(before)

    @patch("posthog.temporal.health_checks.processing.emit_health_check_alert")
    def test_issue_lifecycle(self, _mock_alert) -> None:
        flag_a = self._create_flag("lifecycle-a", **stale_by_usage())
        flag_b = self._create_flag("lifecycle-b", **stale_by_usage())
        check = StaleFeatureFlagsCheck()

        def run() -> None:
            _process_batch_detection([self.team.id], check.kind, check.detect, dry_run=False)

        def active_issues():
            return HealthIssue.objects.filter(team=self.team, kind=check.kind, status=HealthIssue.Status.ACTIVE)

        run()
        assert active_issues().count() == 2
        issue_a = active_issues().get(payload__flag_id=flag_a.id)

        # Volatile evidence moves but the issue identity holds, so the row updates in place.
        flag_a.last_called_at = timezone.now() - timedelta(days=60)
        flag_a.save()
        run()
        assert active_issues().count() == 2
        refreshed_a = active_issues().get(payload__flag_id=flag_a.id)
        assert refreshed_a.id == issue_a.id
        assert refreshed_a.payload["days_since_evidence"] == 60

        # Flag A gets evaluated again; only its issue resolves.
        flag_a.last_called_at = timezone.now()
        flag_a.save()
        run()
        issue_a.refresh_from_db()
        assert issue_a.status == HealthIssue.Status.RESOLVED
        assert active_issues().get().payload["flag_id"] == flag_b.id

        # Flag A requalifies later; a fresh active issue appears beside the resolved history row.
        flag_a.last_called_at = timezone.now() - timedelta(days=40)
        flag_a.save()
        run()
        assert active_issues().count() == 2
        issue_a.refresh_from_db()
        assert issue_a.status == HealthIssue.Status.RESOLVED
        assert active_issues().get(payload__flag_id=flag_a.id).id != issue_a.id


class TestStaleFlagsContract(SimpleTestCase):
    def _issue(self, payload: dict[str, Any]) -> HealthIssue:
        return HealthIssue(
            team_id=1,
            kind="stale_feature_flags",
            severity=HealthIssue.Severity.INFO,
            payload=payload,
            unique_hash="h",
        )

    def test_registered_with_dry_run_and_feature_flags_ownership(self) -> None:
        ensure_registry_loaded()
        registration = HEALTH_CHECKS["stale_feature_flags"]
        assert registration.dry_run is True
        assert registration.owner == JobOwners.TEAM_FEATURE_FLAGS
        assert registration.product == Product.FEATURE_FLAGS
        # The weekly cadence and 1% sampling are operational guards like dry_run: the full-batch
        # query cost is unmeasured, so widening either must be a deliberate change.
        assert registration.schedule == "0 6 * * 1"
        assert registration.rollout_percentage == 0.01
        assert registration.remediation is not None
        # Payloads carry flag keys and names, so the Health API must gate them on flag access.
        assert registration.access_controlled_resource == "feature_flag"

    def test_remediation_orders_code_removal_before_archive(self) -> None:
        remediation = StaleFeatureFlagsCheck.remediation
        assert remediation is not None
        for text, code_removal in (
            (remediation.human, "remove the code checks"),
            (remediation.agent, "remove code checks"),
        ):
            assert text.index(code_removal) < text.index("deploy") < text.index("archive")
        assert "Never archive, disable, or delete" in remediation.agent

    def test_render_alert_for_usage_evidence(self) -> None:
        content = StaleFeatureFlagsCheck.render_alert(
            self._issue(
                {
                    "flag_id": 42,
                    "flag_key": "checkout-v2",
                    "evidence_class": EVIDENCE_NOT_CALLED_RECENTLY,
                    "days_since_evidence": 45,
                    "rollout_state": ROLLOUT_FULLY_ROLLED_OUT,
                }
            )
        )
        assert content.title == "Feature flag 'checkout-v2' may be ready for cleanup"
        assert "PostHog has not received a call for this flag in 45 days" in content.summary
        assert "fully rolled out" in content.summary
        assert "Review code references" in content.summary
        assert content.link == "/feature_flags/42"

    def test_render_alert_truncates_flag_key(self) -> None:
        content = StaleFeatureFlagsCheck.render_alert(
            self._issue(
                {
                    "flag_id": 1,
                    "flag_key": "k" * 400,
                    "evidence_class": EVIDENCE_NOT_CALLED_RECENTLY,
                }
            )
        )
        assert content.title == f"Feature flag '{'k' * 200}' may be ready for cleanup"
        assert "PostHog has not received a call for this flag recently" in content.summary
        assert "The flag is" not in content.summary

    def test_render_alert_for_config_evidence(self) -> None:
        content = StaleFeatureFlagsCheck.render_alert(
            self._issue(
                {
                    "flag_id": 7,
                    "flag_key": "legacy-toggle",
                    "evidence_class": EVIDENCE_FULLY_ROLLED_OUT_WITHOUT_USAGE_DATA,
                    "rollout_state": ROLLOUT_NOT_ROLLED_OUT,
                }
            )
        )
        assert "no usage data" in content.summary
        assert "serves a fixed result" in content.summary
        assert content.link == "/feature_flags/7"

    def test_render_alert_for_effectively_full_rollout_evidence(self) -> None:
        content = StaleFeatureFlagsCheck.render_alert(
            self._issue(
                {
                    "flag_id": 11,
                    "flag_key": "ga-toggle",
                    "evidence_class": EVIDENCE_EFFECTIVELY_FULL_ROLLOUT,
                    "days_since_evidence": 200,
                    "rollout_state": ROLLOUT_FULLY_ROLLED_OUT,
                }
            )
        )
        assert "PostHog still receives calls for this flag" in content.summary
        assert "fully rolled out" in content.summary
        # days_since_evidence is the flag's age on this class, so it must not be narrated as a
        # gap since the last call.
        assert "200" not in content.summary
        assert content.link == "/feature_flags/11"

    def test_render_signal_returns_none(self) -> None:
        issue = self._issue({"flag_id": 42, "flag_key": "checkout-v2"})
        assert StaleFeatureFlagsCheck.render_signal(issue) is None
