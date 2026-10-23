from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import ExperimentHealthFinding, ExperimentHealthFindingActionKind
from products.experiments.backend.health.checks.zero_exposures import (
    CALLS_NOT_COUNTED,
    CUSTOM_EXPOSURE_NOT_MATCHED,
    EXPERIMENT_PAUSED,
    FLAG_NOT_CALLED,
    zero_exposures,
)
from products.experiments.backend.health.context import ExposureEvents, ExposureTotals, FlagState, load_health_context
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.edits import FlagVariant
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

Action = ExperimentHealthFindingActionKind

FLAG = FlagState(
    active=True,
    deleted=False,
    release_groups=(),
    variants=(FlagVariant(key="control", rollout_percentage=50), FlagVariant(key="test", rollout_percentage=50)),
    reachable_conditions=(),
)
NO_EXPOSURES = ExposureTotals(
    total_exposures={"control": 0, "test": 0},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    hours_since_launch=48,
    counts_groups=False,
)
FLAG_CALLS = ExposureEvents(
    custom_event=None, required_flag_key="checkout-test", variant_property="$feature_flag_response", flag_key_filters=()
)
CUSTOM_EVENT = ExposureEvents(
    custom_event="checkout_viewed",
    required_flag_key=None,
    variant_property="$feature/checkout-test",
    flag_key_filters=(),
)
ACTION = replace(CUSTOM_EVENT, custom_event=None)

LAUNCHED_AT = datetime(2026, 10, 1, tzinfo=UTC)
ENDED_AT = datetime(2026, 10, 10, tzinfo=UTC)


class TestZeroExposures(TestCase):
    @parameterized.expand(
        [
            ("flag_not_called", {"flag_called_during_run": False}, FLAG_NOT_CALLED, ()),
            (
                "flag_called",
                {"flag_called_during_run": True},
                CALLS_NOT_COUNTED,
                (Action.OPEN_FEATURE_FLAG, Action.EDIT_EXPOSURE_CRITERIA),
            ),
            ("calls_unknown", {"flag_called_during_run": None}, None, (Action.EDIT_EXPOSURE_CRITERIA,)),
            ("paused", {"is_paused": True, "flag_called_during_run": True}, EXPERIMENT_PAUSED, ()),
            (
                "custom_event_whatever_the_flag_calls",
                {"exposure_events": CUSTOM_EVENT, "flag_called_during_run": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
            (
                "action",
                {"exposure_events": ACTION, "flag_called_during_run": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
            (
                "unreadable_criteria",
                {"exposure_events": None, "flag_called_during_run": False},
                None,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
            (
                "deleted_flag",
                {"flag": replace(FLAG, deleted=True), "flag_called_during_run": False},
                None,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
        ]
    )
    def test_names_the_cause(
        self, _name: str, changes: dict[str, Any], subcode: str | None, actions: tuple[Action, ...]
    ) -> None:
        ctx = replace(
            RUNNING_CONTEXT, **{"flag": FLAG, "exposures": NO_EXPOSURES, "exposure_events": FLAG_CALLS, **changes}
        )

        finding = zero_exposures(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual((finding.subcode, finding.actions), (subcode, actions))

    @parameterized.expand(
        [
            ("users", False, None, "No users exposed, although the feature flag is called", False, False),
            ("groups", True, None, "No groups exposed, although the feature flag is called", True, False),
            ("activation", False, "signed_up", "No users exposed, although the feature flag is called", False, True),
        ]
    )
    def test_names_what_a_call_needs_to_count(
        self,
        _name: str,
        counts_groups: bool,
        activation: str | None,
        title: str,
        names_the_group: bool,
        names_the_activation: bool,
    ) -> None:
        ctx = replace(
            RUNNING_CONTEXT,
            flag=FLAG,
            exposures=replace(NO_EXPOSURES, counts_groups=counts_groups),
            exposure_events=replace(FLAG_CALLS, activation=activation),
            flag_called_during_run=True,
        )

        finding = zero_exposures(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (
                finding.title,
                "A call counts only when it carries the group" in finding.detail,
                'With the activation "signed_up" set' in finding.detail,
            ),
            (title, names_the_group, names_the_activation),
        )


class TestExposureActivation(BaseTest):
    @parameterized.expand(
        [
            (
                "event",
                {"kind": "ExperimentEventExposureConfig", "event": "signed_up", "properties": []},
                None,
                "signed_up",
            ),
            ("action", {"kind": "ActionsNode", "id": 7, "name": "Signed up"}, None, "Signed up"),
            (
                "ignored_next_to_a_custom_exposure_event",
                {"kind": "ExperimentEventExposureConfig", "event": "signed_up", "properties": []},
                {"kind": "ExperimentEventExposureConfig", "event": "checkout_viewed", "properties": []},
                None,
            ),
        ]
    )
    def test_reads_the_activation_the_exposure_query_applies(
        self, _name: str, activation: dict[str, Any], exposure: dict[str, Any] | None, expected: str | None
    ) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="checkout-test", created_by=self.user)
        criteria: dict[str, Any] = {"activation_config": activation}
        if exposure is not None:
            criteria["exposure_config"] = exposure
        experiment = Experiment.objects.create(
            team=self.team, name="exp", feature_flag=flag, start_date=LAUNCHED_AT, exposure_criteria=criteria
        )

        events = load_health_context(experiment).exposure_events

        assert events is not None
        self.assertEqual(events.activation, expected)


class TestFlagCalledDuringRun(BaseTest):
    @parameterized.expand(
        [
            ("never_called", LAUNCHED_AT, None, None, FlagEvaluationsMode.EVENTS, False),
            (
                "called_after_launch",
                LAUNCHED_AT,
                None,
                datetime(2026, 10, 2, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                True,
            ),
            (
                "called_before_launch_only",
                LAUNCHED_AT,
                None,
                datetime(2026, 9, 1, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                False,
            ),
            (
                "called_before_launch_with_calls_kept_out_of_events",
                LAUNCHED_AT,
                None,
                datetime(2026, 9, 1, tzinfo=UTC),
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                None,
            ),
            (
                "ended_called_during_the_run",
                LAUNCHED_AT,
                ENDED_AT,
                datetime(2026, 10, 5, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                True,
            ),
            (
                "ended_called_after_the_end",
                LAUNCHED_AT,
                ENDED_AT,
                datetime(2026, 10, 15, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                None,
            ),
            ("draft", None, None, None, FlagEvaluationsMode.EVENTS, None),
        ]
    )
    def test_reads_the_calls_during_the_run(
        self,
        _name: str,
        start_date: datetime | None,
        end_date: datetime | None,
        last_called_at: datetime | None,
        mode: FlagEvaluationsMode,
        expected: bool | None,
    ) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-test",
            created_by=self.user,
            last_called_at=last_called_at,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )
        experiment = Experiment.objects.create(
            team=self.team, name="exp", feature_flag=flag, start_date=start_date, end_date=end_date
        )

        with override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE="events"):
            ctx = load_health_context(experiment)

        self.assertEqual(ctx.flag_called_during_run, expected)
