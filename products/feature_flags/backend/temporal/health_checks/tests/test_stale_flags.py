from datetime import timedelta
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from posthoganalytics.client import Client
from structlog.testing import capture_logs

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
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
    LIVE_GATE_FLAG,
    StaleFeatureFlagsCheck,
    _live_gate_answer,
)
from products.feature_flags.backend.test.replay_gate_fixtures import trigger_groups
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

FULL_ROLLOUT_FILTERS = {"groups": [{"properties": [], "rollout_percentage": 100}]}
LIVE_GATE_TARGET = "products.feature_flags.backend.temporal.health_checks.stale_flags.get_feature_flag_or_none"
LOADED_DEFINITIONS = [{"key": LIVE_GATE_FLAG, "active": True}]


def stale_by_config() -> dict[str, Any]:
    return {"created_at": timezone.now() - timedelta(days=60), "filters": FULL_ROLLOUT_FILTERS}


def stale_by_usage() -> dict[str, Any]:
    return {
        "last_called_at": timezone.now() - timedelta(days=45),
        "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
    }


def constant_and_called() -> dict[str, Any]:
    return {**stale_by_config(), "last_called_at": timezone.now()}


def _sdk_holding_the_gate() -> Any:
    """Stand the SDK back up, because `settings.TEST` disables it and the gate reads it.

    Only the tests that reach `eligible_team_ids` need this. Detection tests call `detect`
    directly and never meet the gate.
    """
    return patch.multiple(
        "posthoganalytics",
        disabled=False,
        feature_flag_definitions=lambda: LOADED_DEFINITIONS,
    )


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
        elif link == "replay_trigger_group":
            Team.objects.filter(pk=self.team.pk).update(
                session_recording_trigger_groups=trigger_groups({"flag": flag.key})
            )
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
            # The same two conditions the other way round. The matcher stops at the blanket one, so
            # the override below it is unreachable and the flag really does serve one variant.
            (
                "constant_when_the_blanket_condition_comes_first",
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
                            {"properties": [], "rollout_percentage": 100},
                            {
                                "properties": [{"key": "email", "value": "x"}],
                                "rollout_percentage": 100,
                                "variant": "test",
                            },
                        ],
                    },
                },
                None,
                True,
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
            # A variant at zero takes no hashes, so the winner owns the whole space from wherever it
            # is declared. This is the shape a shipped experiment leaves behind.
            (
                "constant_when_the_winner_is_not_the_first_variant",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 0},
                                {"key": "test", "rollout_percentage": 100},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                None,
                True,
            ),
            # The two escape hatches with no case of their own. Both short-circuit ahead of the
            # release conditions, the same way the holdout above does.
            (
                "constant_and_called_behind_super_groups",
                {
                    **constant_and_called(),
                    "filters": {
                        **FULL_ROLLOUT_FILTERS,
                        "super_groups": [{"properties": [], "rollout_percentage": 100}],
                    },
                },
                None,
                False,
            ),
            (
                "constant_and_called_behind_holdout_groups",
                {
                    **constant_and_called(),
                    "filters": {
                        **FULL_ROLLOUT_FILTERS,
                        "holdout_groups": [{"properties": [], "rollout_percentage": 10}],
                    },
                },
                None,
                False,
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
            # A trigger group gates recording just as the linked-flag column does, so the flag it
            # names is not a cleanup candidate either.
            ("replay_trigger_group_linked", stale_by_config(), "replay_trigger_group", False),
        ]
    )
    def test_detect_inclusion_and_exclusion(
        self, key: str, flag_kwargs: dict[str, Any], link: str | None, expected_included: bool
    ) -> None:
        flag = self._create_flag(key, **flag_kwargs)
        if link is not None:
            self._link(link, flag)

        results = self._detect()

        matching = [result for result in results.get(self.team.id, []) if result.payload["flag_id"] == flag.id]
        assert len(matching) == (1 if expected_included else 0)

    def test_a_gate_stored_in_another_project_still_protects_the_flag(self) -> None:
        # Flag ids are globally unique, so a team can store a flag another project owns. Matching
        # ids per project would report that flag as a cleanup candidate. The delete guard is
        # project-scoped too, so nothing else would stop the delete that follows, and the stored
        # reference would be left unrepairable.
        flag = self._create_flag("gated-from-another-project", **stale_by_config())
        other_project_team = Team.objects.create(organization=self.organization)
        # The scan covers the projects that own candidate flags, so the other project needs one
        # of its own before the gate it stores is read at all.
        their_flag = FeatureFlag.objects.create(
            team=other_project_team, key="their-own-flag", created_by=self.user, active=True, **stale_by_config()
        )
        Team.objects.filter(pk=other_project_team.pk).update(
            session_recording_linked_flag={"id": flag.id, "key": flag.key}
        )

        results = self._detect([self.team.id, other_project_team.id])

        assert not any(result.payload["flag_id"] == flag.id for result in results.get(self.team.id, []))
        # Nothing gates `their_flag`: a linked flag contributes its id to `flag_ids` and never its
        # key to `flag_keys`. It stays reported, so an exclusion that swallowed the whole batch
        # would fail here.
        assert any(result.payload["flag_id"] == their_flag.id for result in results.get(other_project_team.id, []))

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
            # The matcher ignores the override and serves the distribution, so the payload must
            # name `control` and not the key the condition carries.
            (
                "multivariate_override_names_an_absent_variant",
                {
                    **constant_and_called(),
                    "filters": {
                        "multivariate": {
                            "variants": [
                                {"key": "control", "rollout_percentage": 100},
                                {"key": "test", "rollout_percentage": 0},
                            ]
                        },
                        "groups": [{"properties": [], "rollout_percentage": 100, "variant": "ghost"}],
                    },
                },
                {
                    "evidence_class": EVIDENCE_EFFECTIVELY_FULL_ROLLOUT,
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

    def test_the_gate_keeps_only_the_teams_the_flag_enables(self) -> None:
        other = Team.objects.create(organization=self.organization, name="other")

        with (
            _sdk_holding_the_gate(),
            patch(
                LIVE_GATE_TARGET, side_effect=lambda _k, distinct_id, **_kw: distinct_id == f"team-{self.team.id}"
            ) as flag_read,
        ):
            eligible = StaleFeatureFlagsCheck.eligible_team_ids([self.team.id, other.id])

        assert eligible == [self.team.id]
        # Team ids repeat across regions and EU evaluates a mirror of this flag, so the read has
        # to carry the region or a project-id condition matches two different customers.
        assert flag_read.call_args_list[0] == call(
            LIVE_GATE_FLAG,
            f"team-{self.team.id}",
            groups={"project": f"DEV:{self.team.id}"},
            group_properties={"project": {"id": str(self.team.id), "region": "DEV"}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )

    @parameterized.expand(
        [
            ("deliberately_disabled", False),
            ("flag_absent", None),
            ("a_variant_is_not_a_posture", "control"),
        ]
    )
    def test_the_gate_drops_a_team_on_any_answer_but_true(self, _name: str, answer: Any) -> None:
        with _sdk_holding_the_gate(), patch(LIVE_GATE_TARGET, return_value=answer):
            assert StaleFeatureFlagsCheck.eligible_team_ids([self.team.id]) == []

    @parameterized.expand(
        [
            ("sdk_off_by_configuration", {"disabled": True}, LOADED_DEFINITIONS),
            ("no_definitions_loaded", {"disabled": False}, None),
            ("empty_definition_set", {"disabled": False}, []),
        ]
    )
    def test_the_gate_reads_no_flag_when_the_sdk_cannot_answer(
        self, _name: str, sdk: dict[str, Any], definitions: Any
    ) -> None:
        with (
            patch("posthoganalytics.disabled", sdk["disabled"]),
            patch("posthoganalytics.feature_flag_definitions", return_value=definitions),
            patch(LIVE_GATE_TARGET) as flag_read,
            capture_logs() as logs,
        ):
            assert StaleFeatureFlagsCheck.eligible_team_ids([self.team.id]) == []

        flag_read.assert_not_called()
        # A batch skipped here never reaches the framework's logging, so this warning is the only
        # trace of a worker that lost its definitions.
        assert [log["event"] for log in logs if log["log_level"] == "warning"] == [
            "stale_feature_flags_live_gate_unreadable"
        ]

    @patch("posthog.temporal.health_checks.processing.emit_health_check_alert")
    def test_a_team_the_gate_drops_keeps_its_open_issues(self, _mock_alert) -> None:
        enabled = Team.objects.create(organization=self.organization, name="enabled")
        FeatureFlag.objects.create(team=enabled, key="stale", created_by=self.user, active=True, **stale_by_usage())
        # The dropped team holds no stale flag, so an ungated run would read it as healthy and
        # resolve this row. Sharing the batch with an enabled team is the production shape: the
        # narrowed list has to reach detection and the healthy-team subtraction, not the early
        # return an empty batch takes.
        HealthIssue.objects.create(
            team=self.team,
            kind="stale_feature_flags",
            severity=HealthIssue.Severity.INFO,
            payload={},
            unique_hash="already-open",
            status=HealthIssue.Status.ACTIVE,
        )

        with (
            _sdk_holding_the_gate(),
            patch(LIVE_GATE_TARGET, side_effect=lambda _k, distinct_id, **_kw: distinct_id == f"team-{enabled.id}"),
        ):
            _process_batch_detection([enabled.id, self.team.id], "stale_feature_flags", StaleFeatureFlagsCheck().detect)

        assert HealthIssue.objects.get(unique_hash="already-open").status == HealthIssue.Status.ACTIVE
        assert HealthIssue.objects.filter(team=enabled, status=HealthIssue.Status.ACTIVE).count() == 1

    def test_the_gate_runs_no_query_when_no_team_is_enabled(self) -> None:
        self._create_flag("enabled-but-gated", **stale_by_usage())

        with (
            _sdk_holding_the_gate(),
            patch(LIVE_GATE_TARGET, return_value=False),
            CaptureQueriesContext(connection) as queries,
        ):
            result = _process_batch_detection([self.team.id], "stale_feature_flags", StaleFeatureFlagsCheck().detect)

        assert result.issues_upserted == 0
        assert queries.captured_queries == []

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

    def test_other_config_formats_are_skipped_without_failing_the_batch(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        unsupported = FeatureFlag.objects.create(
            team=other_team,
            key="v2-flag",
            created_by=self.user,
            active=True,
            created_at=timezone.now() - timedelta(days=60),
            filters={"version": 2, **FULL_ROLLOUT_FILTERS},
        )
        not_an_object = FeatureFlag.objects.create(
            team=other_team,
            key="list-filters",
            created_by=self.user,
            active=True,
            **{**stale_by_usage(), "filters": ["version"]},
        )
        called = FeatureFlag.objects.create(
            team=other_team,
            key="v2-called",
            created_by=self.user,
            active=True,
            **{**constant_and_called(), "filters": {"version": 2, **FULL_ROLLOUT_FILTERS}},
        )
        self._create_flag("v1-stale", **stale_by_usage())

        with capture_logs() as logs:
            results = self._detect([self.team.id, other_team.id])

        assert set(results) == {self.team.id}
        assert [result.payload["flag_key"] for result in results[self.team.id]] == ["v1-stale"]
        skips = [log for log in logs if log["event"] == "stale_feature_flags_skipped_unsupported_config"]
        assert sorted((log["flag_id"], log["team_id"]) for log in skips) == sorted(
            [(unsupported.id, other_team.id), (not_an_object.id, other_team.id), (called.id, other_team.id)]
        )

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

        def run(gate_answer: bool = True) -> None:
            with _sdk_holding_the_gate(), patch(LIVE_GATE_TARGET, return_value=gate_answer):
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

        # Flag A stops being stale, but the gate is off, so its issue stays open.
        flag_a.last_called_at = timezone.now()
        flag_a.save()
        run(gate_answer=False)
        assert active_issues().count() == 2


class TestStaleFlagsContract(SimpleTestCase):
    def _issue(self, payload: dict[str, Any]) -> HealthIssue:
        return HealthIssue(
            team_id=1,
            kind="stale_feature_flags",
            severity=HealthIssue.Severity.INFO,
            payload=payload,
            unique_hash="h",
        )

    def test_registered_dry_until_the_gate_reaches_every_worker(self) -> None:
        ensure_registry_loaded()
        registration = HEALTH_CHECKS["stale_feature_flags"]
        assert registration.owner == JobOwners.TEAM_FEATURE_FLAGS
        assert registration.product == Product.FEATURE_FLAGS
        # Web writes these into the schedule before the worker redeploys, so a worker without
        # `eligible_team_ids` must still find a dry registration. The follow-up drops both and
        # leaves the flag as the only gate.
        assert registration.dry_run is True
        assert registration.rollout_percentage == 0.01
        assert registration.schedule == "0 6 * * 1"
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


class TestLiveGateAgainstRealLocalEvaluation(SimpleTestCase):
    """The gate against a real SDK client, because every other test patches the read.

    `settings.TEST` disables the global client, so the patched tests assert the arguments the
    gate sends but never resolve them against a definition. These load one into a standalone
    client and evaluate it, which is what catches a condition shape that silently matches nobody.
    """

    def _client_holding(self, flags: list[dict[str, Any]]) -> Client:
        client = Client(
            project_api_key="test-key",
            personal_api_key="test-personal-key",
            host="http://localhost:8000",
            poll_interval=99999,
            send=False,
            enable_exception_autocapture=False,
        )
        client.feature_flags = flags
        client.group_type_mapping = {"0": "project"}
        return client

    def _gate_flag(self, *, region: str, team_id: int) -> dict[str, Any]:
        return {
            "id": 1,
            "key": LIVE_GATE_FLAG,
            "active": True,
            "filters": {
                "aggregation_group_type_index": 0,
                "groups": [
                    {
                        "rollout_percentage": 100,
                        "properties": [
                            {"group_type_index": 0, "key": "id", "value": str(team_id), "operator": "exact"},
                            {"group_type_index": 0, "key": "region", "value": region, "operator": "exact"},
                        ],
                    }
                ],
            },
        }

    def _answer_for(self, client: Client, team_id: int) -> Any:
        # `get_feature_flag_or_none` resolves the module function at call time, so the
        # standalone client stands in for the global one and the gate sends what production sends.
        with patch("posthoganalytics.get_feature_flag", client.get_feature_flag):
            return _live_gate_answer(team_id)

    def test_a_project_and_region_condition_matches_only_that_project(self) -> None:
        client = self._client_holding([self._gate_flag(region="DEV", team_id=2)])

        assert self._answer_for(client, 2) is True
        assert self._answer_for(client, 3) is False

    def test_a_condition_on_another_region_matches_nobody(self) -> None:
        # The property the gate sends is what keeps US project N and EU project N apart.
        client = self._client_holding([self._gate_flag(region="EU", team_id=2)])

        assert self._answer_for(client, 2) is False

    def test_a_gate_aggregated_on_another_group_type_answers_false_for_every_team(self) -> None:
        # The trap: the gate sends only the `project` group, so a flag aggregated on anything
        # else answers False rather than None. Under this design that drops the team, which is
        # safe, but it means such a flag enables nobody and looks like a flag nobody matched.
        flag = self._gate_flag(region="DEV", team_id=2)
        flag["filters"]["aggregation_group_type_index"] = 1
        client = self._client_holding([flag])
        client.group_type_mapping = {"0": "project", "1": "organization"}

        assert self._answer_for(client, 2) is False

    def test_an_absent_gate_answers_none(self) -> None:
        client = self._client_holding([{"id": 9, "key": "some-other-flag", "active": True, "filters": {}}])

        with capture_logs() as logs:
            assert self._answer_for(client, 2) is None

        # `get_feature_flag_or_none` also answers None after an exception, so the log is what
        # separates a missing flag from a read that failed.
        assert [log for log in logs if log["event"] == "get_feature_flag_failed"] == []
