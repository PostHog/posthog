from dataclasses import replace
from typing import Any

from posthog.test.base import BaseTest
from unittest import TestCase

from django.utils import timezone

from parameterized import parameterized

from posthog.schema import PropertyOperator

from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.team.team import Team

from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models import PropertyDefinition
from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.exposure_filters import (
    COHORT_FORCES_VARIANT,
    COHORT_IN_RELEASE_CONDITIONS,
    exposure_filters,
)
from products.experiments.backend.health.context import (
    ExposureCohort,
    ExposureEvents,
    ExposurePropertyFilter,
    ExposurePropertyType,
    FlagState,
    HealthContext,
    ReachableCondition,
    load_health_context,
)
from products.experiments.backend.health.skips import NOT_ON_ARCHIVED, CheckSkip, not_applicable, not_checked
from products.experiments.backend.health.test.factories import ENDED, RUNNING_CONTEXT
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.models.feature_flag import FeatureFlag

Code = ExperimentHealthFindingCode
Severity = ExperimentHealthFindingSeverity
DYNAMIC = ExposureCohort(id=7, name="Paying users", is_static=False)
STATIC = ExposureCohort(id=8, name="QA team", is_static=True)
NO_FILTERS = not_applicable("The exposure criteria have no cohort filter and no negated event property filter")


def _filters(
    *property_filters: tuple[ExposurePropertyType, str, PropertyOperator],
    cohorts: tuple[ExposureCohort, ...] = (),
    cohort_ids: tuple[int, ...] | None = None,
    flag_cohort_ids: frozenset[int] = frozenset(),
    forced_variant: str | None = None,
    **changes: Any,
) -> HealthContext:
    events = ExposureEvents(
        custom_event=None,
        required_flag_key="checkout-test",
        variant_property="$feature_flag_response",
        flag_key_filters=(),
        property_filters=tuple(
            ExposurePropertyFilter(
                type=property_type, key=key, operator=operator, values=("x",), event="$feature_flag_called"
            )
            for property_type, key, operator in property_filters
        ),
        cohort_ids=tuple(cohort.id for cohort in cohorts) if cohort_ids is None else cohort_ids,
    )
    condition = ReachableCondition(
        number=1, pinned_variant=forced_variant, variant_property=None, cohort_ids=flag_cohort_ids
    )
    flag = FlagState(active=True, deleted=False, release_groups=(), variants=(), reachable_conditions=(condition,))
    return replace(RUNNING_CONTEXT, exposure_events=events, exposure_cohorts=cohorts, flag=flag, **changes)


def _filter(property_type: str, key: str) -> dict[str, Any]:
    return {"type": property_type, "key": key, "operator": "exact", "value": "x"}


def _config(event: str, *properties: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "ExperimentEventExposureConfig", "event": event, "properties": list(properties)}


EXCLUDED_URL: tuple[ExposurePropertyType, str, PropertyOperator] = (
    "event",
    "$current_url",
    PropertyOperator.NOT_ICONTAINS,
)
COHORT_WARNING = (Code.EXPOSURE_FILTER_ON_DYNAMIC_COHORT, None, Severity.WARNING)


class TestExposureFilters(TestCase):
    @parameterized.expand(
        [
            ("dynamic_cohort", _filters(cohorts=(DYNAMIC,)), COHORT_WARNING),
            (
                "dynamic_cohort_in_the_release_conditions",
                _filters(cohorts=(DYNAMIC,), flag_cohort_ids=frozenset({7})),
                (Code.EXPOSURE_FILTER_ON_DYNAMIC_COHORT, COHORT_IN_RELEASE_CONDITIONS, Severity.WARNING),
            ),
            (
                "dynamic_cohort_given_one_variant_in_the_release_conditions",
                _filters(cohorts=(DYNAMIC,), flag_cohort_ids=frozenset({7}), forced_variant="test"),
                (Code.EXPOSURE_FILTER_ON_DYNAMIC_COHORT, COHORT_FORCES_VARIANT, Severity.WARNING),
            ),
            ("dynamic_cohort_after_the_end", _filters(cohorts=(DYNAMIC,), **ENDED), COHORT_WARNING),
            (
                "dynamic_cohort_before_an_event_exclusion",
                _filters(EXCLUDED_URL, cohorts=(STATIC, DYNAMIC)),
                COHORT_WARNING,
            ),
            ("static_cohort", _filters(cohorts=(STATIC,)), None),
            (
                "deleted_cohort",
                _filters(cohorts=(STATIC,), cohort_ids=(8, 9)),
                not_checked("Couldn't check because a cohort in the exposure criteria is deleted or missing"),
            ),
            ("event_exclusion", _filters(EXCLUDED_URL), (Code.EXPOSURE_FILTER_EXCLUDES_EVENTS, None, Severity.INFO)),
            ("event_filter_that_selects", _filters(("event", "$current_url", PropertyOperator.ICONTAINS)), NO_FILTERS),
            ("person_exclusion", _filters(("person", "email", PropertyOperator.NOT_ICONTAINS)), NO_FILTERS),
            ("flag_key_exclusion", _filters(("event", "$feature_flag", PropertyOperator.IS_NOT)), NO_FILTERS),
            ("archived", _filters(cohorts=(DYNAMIC,), archived=True), not_applicable(NOT_ON_ARCHIVED)),
        ]
    )
    def test_exposure_filters(
        self, _name: str, ctx: HealthContext, expected: tuple[Code, str | None, Severity] | CheckSkip | None
    ) -> None:
        outcome = exposure_filters(ctx)

        actual = (
            (outcome.code, outcome.subcode, outcome.severity)
            if isinstance(outcome, ExperimentHealthFinding)
            else outcome
        )
        self.assertEqual(actual, expected)


class TestExposureFilterInputs(BaseTest):
    def test_reads_the_properties_and_cohorts_as_the_exposure_query_does(self) -> None:
        sibling = Team.objects.create(organization=self.organization, project=self.project, name="Sibling")
        PropertyDefinition.objects.create(team=sibling, project=self.project, name="$current_url")
        PropertyDefinition.objects.create(
            team=self.team, project=self.project, name="email", type=PropertyDefinition.Type.PERSON
        )
        with self.captureOnCommitCallbacks(execute=True):
            log_activity(
                organization_id=self.organization.id,
                team_id=sibling.id,
                user=self.user,
                was_impersonated=False,
                item_id="deleted_prop",
                scope="PropertyDefinition",
                activity="deleted",
                detail=Detail(name="deleted_prop", changes=None),
            )
        dynamic = Cohort.objects.create(team=sibling, name="Paying users")
        static = Cohort.objects.create(team=self.team, name="QA team", is_static=True)
        deleted = Cohort.objects.create(team=self.team, name="Old", deleted=True)
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="checkout-test",
            created_by=self.user,
            filters={
                "groups": [
                    {"properties": [{"type": "cohort", "key": "id", "value": dynamic.pk}], "rollout_percentage": 100}
                ]
            },
        )
        filters = [
            {"type": "event", "key": key, "operator": "exact", "value": "x"}
            for key in ("$current_url", "$curent_url", "deleted_prop", "$virt_is_bot", "email")
        ]
        experiment = Experiment.objects.create(
            team=self.team,
            name="Checkout",
            feature_flag=flag,
            start_date=timezone.now(),
            exposure_criteria={
                "exposure_config": {
                    "kind": "ExperimentEventExposureConfig",
                    "event": "$feature_flag_called",
                    "properties": [
                        *filters,
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@"},
                        {"type": "person", "key": "plan", "operator": "exact", "value": "pro"},
                        *({"type": "cohort", "key": "id", "value": c.pk} for c in (dynamic, static, deleted)),
                    ],
                }
            },
        )

        ctx = load_health_context(experiment)

        self.assertEqual(
            dict(ctx.exposure_properties_received),
            {
                ("event", "$current_url"): True,
                ("event", "$curent_url"): False,
                ("event", "email"): False,
                ("person", "email"): True,
                ("person", "plan"): False,
            },
        )
        self.assertEqual(
            ctx.exposure_cohorts,
            (
                ExposureCohort(id=dynamic.pk, name="Paying users", is_static=False),
                ExposureCohort(id=static.pk, name="QA team", is_static=True),
            ),
        )
        assert ctx.flag is not None
        self.assertEqual([c.cohort_ids for c in ctx.flag.reachable_conditions], [frozenset({dynamic.pk})])

    @parameterized.expand(
        [
            (
                "activation_next_to_the_default_exposure",
                {
                    "exposure_config": _config("$feature_flag_called", _filter("person", "plan")),
                    "activation_config": _config("checkout_viewed", _filter("event", "step")),
                },
                [("person", "plan", "$feature_flag_called"), ("event", "step", "checkout_viewed")],
            ),
            (
                "activation_stored_next_to_a_custom_exposure",
                {
                    "exposure_config": _config("signup", _filter("person", "plan")),
                    "activation_config": _config("checkout_viewed", _filter("event", "step")),
                },
                [("person", "plan", "signup")],
            ),
            (
                "action",
                {"exposure_config": {"kind": "ActionsNode", "id": 1, "properties": [_filter("event", "step")]}},
                [("event", "step", None)],
            ),
        ]
    )
    def test_reads_the_filters_the_exposure_query_applies(
        self, _name: str, criteria: dict[str, Any], expected: list[tuple[str, str, str | None]]
    ) -> None:
        flag = FeatureFlag.objects.create(team=self.team, key="checkout-test", created_by=self.user)
        experiment = Experiment.objects.create(
            team=self.team, name="Checkout", feature_flag=flag, exposure_criteria=criteria
        )

        ctx = load_health_context(experiment)

        assert ctx.exposure_events is not None
        self.assertEqual([(f.type, f.key, f.event) for f in ctx.exposure_events.property_filters], expected)
        self.assertEqual(ctx.exposure_properties_received, {})
