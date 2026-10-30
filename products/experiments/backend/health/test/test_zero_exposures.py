from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest import TestCase

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.zero_exposures import (
    CALLS_NOT_COUNTED,
    CUSTOM_EXPOSURE_NOT_MATCHED,
    EXPERIMENT_PAUSED,
    FLAG_NOT_CALLED,
    zero_exposures,
)
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureTotals,
    FlagState,
    HealthContext,
    load_health_context,
)
from products.experiments.backend.health.test.factories import ENDED, RUNNING_CONTEXT
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.edits import FlagVariant
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

Action = ExperimentHealthFindingActionKind
WARNING = ExperimentHealthFindingSeverity.WARNING
INFO = ExperimentHealthFindingSeverity.INFO

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
    sample_ratio_expected={},
    daily_exposures={},
    hours_since_launch=48,
    counts_groups=False,
)
TEST_ACCOUNTS_ONLY = replace(NO_EXPOSURES, exposed_without_test_account_filter=12)
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
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class TestZeroExposures(TestCase):
    @parameterized.expand(
        [
            ("flag_not_called", {"flag_called_during_run": False}, FLAG_NOT_CALLED, (), WARNING),
            (
                "flag_called",
                {"flag_called_during_run": True},
                CALLS_NOT_COUNTED,
                (Action.OPEN_FEATURE_FLAG, Action.EDIT_EXPOSURE_CRITERIA),
                WARNING,
            ),
            (
                "flag_called_by_test_accounts_only",
                {"flag_called_during_run": True, "exposures": TEST_ACCOUNTS_ONLY},
                CALLS_NOT_COUNTED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
            ("calls_unknown", {"flag_called_during_run": None}, None, (Action.EDIT_EXPOSURE_CRITERIA,), WARNING),
            ("paused", {"is_paused": True, "flag_called_during_run": True}, EXPERIMENT_PAUSED, (), INFO),
            (
                "custom_event_whatever_the_flag_calls",
                {"exposure_events": CUSTOM_EVENT, "flag_called_during_run": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
            (
                "action",
                {"exposure_events": ACTION, "flag_called_during_run": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
            (
                "unreadable_criteria",
                {"exposure_events": None, "flag_called_during_run": False},
                None,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
            (
                "deleted_flag",
                {"flag": replace(FLAG, deleted=True), "flag_called_during_run": False},
                None,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
            ("ended_flag_not_called", {**ENDED, "flag_called_during_run": False}, FLAG_NOT_CALLED, (), INFO),
            (
                "ended_flag_called",
                {**ENDED, "flag_called_during_run": True},
                CALLS_NOT_COUNTED,
                (Action.OPEN_FEATURE_FLAG, Action.EDIT_EXPOSURE_CRITERIA),
                WARNING,
            ),
            (
                "ended_flag_called_by_test_accounts_only",
                {**ENDED, "flag_called_during_run": True, "exposures": TEST_ACCOUNTS_ONLY},
                CALLS_NOT_COUNTED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
            (
                "ended_calls_unknown",
                {**ENDED, "flag_called_during_run": None},
                None,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                INFO,
            ),
            (
                "ended_custom_event",
                {**ENDED, "exposure_events": CUSTOM_EVENT, "flag_called_during_run": False},
                CUSTOM_EXPOSURE_NOT_MATCHED,
                (Action.EDIT_EXPOSURE_CRITERIA,),
                WARNING,
            ),
        ]
    )
    def test_names_the_cause(
        self,
        _name: str,
        changes: dict[str, Any],
        subcode: str | None,
        actions: tuple[Action, ...],
        severity: ExperimentHealthFindingSeverity,
    ) -> None:
        ctx = replace(
            RUNNING_CONTEXT, **{"flag": FLAG, "exposures": NO_EXPOSURES, "exposure_events": FLAG_CALLS, **changes}
        )

        finding = zero_exposures(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual((finding.subcode, finding.actions, finding.severity), (subcode, actions, severity))
        self.assertEqual(finding.detail.startswith("No users were exposed while the experiment ran"), ctx.has_ended)

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

    @parameterized.expand(
        [
            (
                "running",
                RUNNING_CONTEXT,
                1200,
                "test_account_filter",
                {"exposed_without_test_account_filter": 1200},
                "No users exposed: the test account filter removes all of them",
                "The exposure criteria filter out test accounts, and the project's test account filters match all 1,200 "
                'users that got a variant of the feature flag "checkout-test" during the experiment, so nobody is '
                'counted as exposed. Turn off "Filter out internal and test users" in the exposure criteria, or change '
                "the project's test account filters so that they don't match your users.",
            ),
            (
                "ended_one_user",
                replace(RUNNING_CONTEXT, **ENDED),
                1,
                "test_account_filter",
                {"exposed_without_test_account_filter": 1},
                "No users exposed: the test account filter removed all of them",
                "No users were exposed while the experiment ran, because the exposure criteria filter out test "
                "accounts, and the project's test account filters matched the only user that got a variant of the "
                'feature flag "checkout-test". Turn off "Filter out internal and test users" in the exposure criteria '
                "to count them.",
            ),
            (
                "nobody_without_the_filter",
                RUNNING_CONTEXT,
                0,
                None,
                {"exposed_without_test_account_filter": 0},
                "No users exposed, although the feature flag is called",
                'PostHog has recorded calls of the feature flag "checkout-test" during the experiment, but none of them '
                "counts as an exposure. A call counts when the flag returns one of the experiment's variants and the "
                "user passes the exposure criteria. Check that the flag's release conditions include your users, and "
                "that the exposure criteria, such as the test account filter, don't leave them out.",
            ),
        ]
    )
    def test_counts_the_users_that_the_test_account_filter_removes(
        self,
        _name: str,
        base: HealthContext,
        exposed: int,
        reason: str | None,
        evidence: dict[str, int | str],
        title: str,
        detail: str,
    ) -> None:
        ctx = replace(
            base,
            flag=FLAG,
            exposures=replace(NO_EXPOSURES, exposed_without_test_account_filter=exposed),
            exposure_events=FLAG_CALLS,
            flag_called_during_run=True,
        )

        finding = zero_exposures(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.subcode, finding.reason, finding.title, finding.detail, finding.evidence),
            (CALLS_NOT_COUNTED, reason, title, detail, {"hours_since_launch": 48, **evidence}),
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
            ("never_called", LAUNCHED_AT, None, None, FlagEvaluationsMode.EVENTS, False, None),
            (
                "called_after_launch",
                LAUNCHED_AT,
                None,
                datetime(2026, 10, 2, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                True,
                None,
            ),
            (
                "called_before_launch_only",
                LAUNCHED_AT,
                None,
                datetime(2026, 9, 1, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                False,
                None,
            ),
            (
                "called_before_launch_with_calls_kept_out_of_events",
                LAUNCHED_AT,
                None,
                datetime(2026, 9, 1, tzinfo=UTC),
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                None,
                None,
            ),
            (
                "ended_called_during_the_run",
                LAUNCHED_AT,
                ENDED_AT,
                datetime(2026, 10, 5, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                True,
                False,
            ),
            (
                "ended_called_after_the_end",
                LAUNCHED_AT,
                ENDED_AT,
                datetime(2026, 10, 15, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                None,
                True,
            ),
            ("ended_never_called", LAUNCHED_AT, ENDED_AT, None, FlagEvaluationsMode.EVENTS, False, False),
            (
                "ended_called_during_the_run_with_calls_kept_out_of_events",
                LAUNCHED_AT,
                ENDED_AT,
                datetime(2026, 10, 5, tzinfo=UTC),
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                True,
                None,
            ),
            (
                "ended_inside_the_quiet_period",
                LAUNCHED_AT,
                NOW - timedelta(days=3, minutes=59),
                datetime(2026, 10, 5, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                True,
                None,
            ),
            (
                "ended_past_the_quiet_period",
                LAUNCHED_AT,
                NOW - timedelta(days=3, minutes=61),
                datetime(2026, 10, 5, tzinfo=UTC),
                FlagEvaluationsMode.EVENTS,
                True,
                False,
            ),
            ("draft", None, None, None, FlagEvaluationsMode.EVENTS, None, None),
        ]
    )
    def test_reads_the_calls_during_and_after_the_run(
        self,
        _name: str,
        start_date: datetime | None,
        end_date: datetime | None,
        last_called_at: datetime | None,
        mode: FlagEvaluationsMode,
        during_run: bool | None,
        after_end: bool | None,
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

        with override_settings(FEATURE_FLAG_LAST_CALLED_AT_SYNC_SOURCE="events"), time_machine.travel(NOW, tick=False):
            ctx = load_health_context(experiment)

        self.assertEqual((ctx.flag_called_during_run, ctx.flag_called_after_end), (during_run, after_end))
