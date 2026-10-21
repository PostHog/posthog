from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import ExperimentHealthFindingActionKind
from products.experiments.backend.health.checks.zero_exposures import (
    CALLS_NOT_COUNTED,
    CUSTOM_EXPOSURE_NOT_MATCHED,
    FLAG_NOT_CALLED,
    zero_exposures,
)
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureTotals,
    FlagState,
    FlagVariant,
    load_health_context,
)
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.experiments.backend.models.experiment import Experiment
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


class TestZeroExposures(TestCase):
    @parameterized.expand(
        [
            ("flag_not_called", {"flag_called_since_launch": False}, FLAG_NOT_CALLED, ()),
            (
                "flag_called",
                {"flag_called_since_launch": True},
                CALLS_NOT_COUNTED,
                (Action.OPEN_FEATURE_FLAG, Action.EDIT_EXPOSURE_CRITERIA),
            ),
            ("calls_unknown", {"flag_called_since_launch": None}, None, (Action.EDIT_EXPOSURE_CRITERIA,)),
            (
                "custom_event_whatever_the_flag_calls",
                {"exposure_events": CUSTOM_EVENT, "flag_called_since_launch": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
            (
                "action",
                {"exposure_events": ACTION, "flag_called_since_launch": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
            (
                "unreadable_criteria",
                {"exposure_events": None, "flag_called_since_launch": False},
                None,
                (Action.EDIT_EXPOSURE_CRITERIA,),
            ),
            (
                "deleted_flag",
                {"flag": replace(FLAG, deleted=True), "flag_called_since_launch": False},
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

        assert finding is not None
        self.assertEqual((finding.subcode, finding.actions), (subcode, actions))


class TestFlagCalledSinceLaunch(BaseTest):
    @parameterized.expand(
        [
            ("never_called", LAUNCHED_AT, None, False, FlagEvaluationsMode.EVENTS, False),
            (
                "called_after_launch",
                LAUNCHED_AT,
                datetime(2026, 10, 2, tzinfo=UTC),
                False,
                FlagEvaluationsMode.EVENTS,
                True,
            ),
            (
                "called_before_launch_only",
                LAUNCHED_AT,
                datetime(2026, 9, 1, tzinfo=UTC),
                False,
                FlagEvaluationsMode.EVENTS,
                False,
            ),
            (
                "called_before_launch_with_calls_kept_out_of_events",
                LAUNCHED_AT,
                datetime(2026, 9, 1, tzinfo=UTC),
                False,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                None,
            ),
            ("deleted_flag", LAUNCHED_AT, None, True, FlagEvaluationsMode.EVENTS, None),
            ("draft", None, None, False, FlagEvaluationsMode.EVENTS, None),
        ]
    )
    def test_reads_the_calls_since_launch(
        self,
        _name: str,
        start_date: datetime | None,
        last_called_at: datetime | None,
        flag_deleted: bool,
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
            deleted=flag_deleted,
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
        experiment = Experiment.objects.create(team=self.team, name="exp", feature_flag=flag, start_date=start_date)

        with override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE="events"):
            ctx = load_health_context(experiment)

        self.assertEqual(ctx.flag_called_since_launch, expected)
