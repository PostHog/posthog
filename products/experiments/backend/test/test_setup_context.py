import dataclasses
from dataclasses import asdict
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.core.cache import cache
from django.db.models import QuerySet
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.exceptions import ClickHouseQueryTimeOut

from products.actions.backend.models.action import Action
from products.experiments.backend import setup_context as setup_context_module
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
)
from products.experiments.backend.models.experiment import (
    EXPOSURE_FROZEN_GROUP_KEY,
    Experiment,
    ExperimentMetricResult,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)
from products.experiments.backend.presentation import serializers as experiment_serializers
from products.experiments.backend.presentation.serializers import RunningTimeBaselineStatsSerializer
from products.experiments.backend.running_time_calculator import BaselineStats, calculate_baseline_value
from products.experiments.backend.setup_context import (
    SDK_PROFILE_MAX_LIBS,
    SERVER_LIBS,
    SetupContextInputs,
    build_setup_context,
    classify_lib,
    get_candidate_metric,
    get_previous_experiments,
    get_sdk_profile,
    get_shared_metrics,
    get_target_surface,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


def _mean_metric(uuid: str, event: str = "purchase") -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "uuid": uuid,
        "source": {"kind": "EventsNode", "event": event},
    }


def _funnel_metric(uuid: str, event: str = "purchase") -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "funnel",
        "uuid": uuid,
        "series": [{"kind": "EventsNode", "event": event}],
    }


def _retention_metric(uuid: str, start_event: str = "signup", completion_event: str = "purchase") -> dict[str, Any]:
    return {
        "kind": "ExperimentMetric",
        "metric_type": "retention",
        "uuid": uuid,
        "start_event": {"kind": "EventsNode", "event": start_event},
        "completion_event": {"kind": "EventsNode", "event": completion_event},
    }


def _stored_result(
    baseline_samples: int, variant_samples: list[int], significant: bool, *, baseline_sum: float = 1
) -> dict[str, Any]:
    return {
        "baseline": {"key": "control", "number_of_samples": baseline_samples, "sum": baseline_sum, "sum_squares": 1},
        "variant_results": [
            {"key": f"test-{index}", "number_of_samples": samples, "significant": significant}
            for index, samples in enumerate(variant_samples)
        ],
        "hogql": "SELECT 1",
    }


class TestSetupContextInputs(SimpleTestCase):
    @parameterized.expand(
        [
            ("url_filter_without_pageview", {"target_event": "$screen", "target_url_contains": "pricing"}),
            ("metric_event_equals_target_event", {"target_event": "$pageview", "metric_event": "$pageview"}),
            ("limit_above_the_maximum", {"shared_metrics_limit": 26}),
            ("target_properties_without_target_event", {"target_properties": ({"key": "a", "type": "event"},)}),
            ("metric_properties_without_metric_event", {"metric_properties": ({"key": "a", "type": "event"},)}),
            (
                "more_property_filters_than_the_maximum",
                {
                    "target_event": "$pageview",
                    "target_properties": tuple({"key": f"p-{index}", "type": "event"} for index in range(11)),
                },
            ),
        ]
    )
    def test_rejects_inputs_that_cannot_produce_an_answer(self, _name: str, kwargs: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            SetupContextInputs(**kwargs)


class TestClassifyLib(SimpleTestCase):
    @parameterized.expand(
        [
            ("web", "web"),
            ("posthog-node", "server"),
            ("posthog-python", "server"),
            ("posthog-rails", "server"),
            ("posthog-ios", "mobile"),
            ("posthog-unity", "mobile"),
            ("posthog-something-new", "other"),
            (None, "other"),
        ]
    )
    def test_classifies_lib(self, lib: str | None, expected: str) -> None:
        assert classify_lib(lib) == expected

    def test_server_libs_cover_the_sdks_the_overlap_signal_needs(self) -> None:
        # Most of SERVER_LIBS is borrowed from an activation heuristic that loses nothing by
        # dropping a lib. Here a dropped lib stops evaluated_on_server_and_web from firing for
        # every project on that SDK, and nothing else notices.
        assert {
            "posthog-node",
            "posthog-python",
            "posthog-php",
            "posthog-ruby",
            "posthog-go",
            "posthog-java",
            "posthog-dotnet",
            "posthog-elixir",
            "posthog-rs",
        } <= SERVER_LIBS


class TestResponseCoversEveryFact(SimpleTestCase):
    """The response serializer is built by hand beside the dataclasses it renders.

    A dataclass field the serializer forgets is dropped silently. A serializer field the dataclass
    doesn't have raises while rendering, and that happens outside the per-section guard, so it
    fails the whole endpoint rather than one section.
    """

    PAIRS = [
        ("ExperimentSetupContext", "ExperimentSetupContextResponseSerializer"),
        ("TeamDefaults", "ExperimentSetupTeamDefaultsSerializer"),
        ("SdkLibProfile", "ExperimentSetupSdkLibSerializer"),
        ("LibActivity", "ExperimentSetupLibActivitySerializer"),
        ("SdkProfile", "ExperimentSetupSdkProfileSerializer"),
        ("LibReach", "ExperimentSetupLibReachSerializer"),
        ("TargetSurface", "ExperimentSetupTargetSurfaceSerializer"),
        ("FunnelBaselineStats", "ExperimentSetupFunnelBaselineSerializer"),
        ("MeanCountBaselineStats", "ExperimentSetupMeanCountBaselineSerializer"),
        ("CandidateMetric", "ExperimentSetupCandidateMetricSerializer"),
        ("ExperimentOutcome", "ExperimentSetupOutcomeSerializer"),
        ("PreviousExperiment", "ExperimentSetupPreviousExperimentSerializer"),
        ("PreviousExperimentsSummary", "ExperimentSetupPreviousExperimentsSummarySerializer"),
        ("PreviousExperiments", "ExperimentSetupPreviousExperimentsSerializer"),
        ("SharedMetricUsage", "ExperimentSetupSharedMetricSerializer"),
        ("SharedMetrics", "ExperimentSetupSharedMetricsSerializer"),
    ]
    # Inputs and internal helpers, which the response never carries.
    UNRENDERED = {
        "SetupContextInputs",
        "SetupContextSection",
        "TimeWindow",
        "CustomExposure",
        "OutcomeMetric",
    }

    @parameterized.expand(PAIRS)
    def test_serializer_renders_exactly_the_dataclass_fields(self, dataclass_name: str, serializer_name: str) -> None:
        dataclass_type = getattr(setup_context_module, dataclass_name)
        serializer = getattr(experiment_serializers, serializer_name)()

        assert {field.name for field in dataclasses.fields(dataclass_type)} == set(serializer.fields)

    def test_every_dataclass_in_the_response_is_covered(self) -> None:
        declared = {
            name
            for name, value in vars(setup_context_module).items()
            if dataclasses.is_dataclass(value) and getattr(value, "__module__", None) == setup_context_module.__name__
        }

        assert declared - self.UNRENDERED == {dataclass_name for dataclass_name, _ in self.PAIRS}


class TestSdkProfile(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _seed(self, events: list[str]) -> None:
        # Ingestion copies each multivariate flag call into $experiment_exposure, so a team on the
        # new event carries every row twice.
        web_callers: list[tuple[str, bool, dict[str, Any]]] = [
            ("anon-1", False, {"$device_id": "device-1"}),
            ("anon-2", False, {"$device_id": "device-2"}),
            ("user-1", True, {}),
        ]
        for distinct_id, identified, extra in web_callers:
            for event in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timezone.now() - timedelta(days=1),
                    properties={
                        "$lib": "web",
                        "$feature_flag": "checkout-flag",
                        "$feature_flag_response": "test",
                        "$is_identified": identified,
                        **extra,
                    },
                )
        # Mobile SDKs report $is_identified on nearly every call but never send $device_id, which
        # is the reverse of what a lib-name guard assumes about anything that isn't web.
        for distinct_id, identified in [("ios-anon", False), ("ios-user", True)]:
            for event in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timezone.now() - timedelta(days=1),
                    properties={
                        "$lib": "posthog-ios",
                        "$feature_flag": "checkout-flag",
                        "$feature_flag_response": "test",
                        "$is_identified": identified,
                    },
                )
        for distinct_id, locally_evaluated in [("server-user-1", True), ("server-user-2", False)]:
            for event in events:
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=distinct_id,
                    timestamp=timezone.now() - timedelta(days=1),
                    properties={
                        "$lib": "posthog-node",
                        "$feature_flag": "pricing-flag",
                        "$feature_flag_response": "control",
                        "locally_evaluated": locally_evaluated,
                    },
                )
        # A boolean flag is never copied into $experiment_exposure, so the fallback must skip it too.
        _create_event(
            team=self.team,
            event=DEFAULT_EXPOSURE_EVENT,
            distinct_id="boolean-user",
            timestamp=timezone.now() - timedelta(days=1),
            properties={"$lib": "web", "$feature_flag": "some-toggle", "$feature_flag_response": "true"},
        )

    @parameterized.expand(
        [
            ("fallback_to_flag_called", [DEFAULT_EXPOSURE_EVENT], DEFAULT_EXPOSURE_EVENT),
            (
                "exposure_event_only_counted_once",
                [DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT],
                EXPERIMENT_EXPOSURE_EVENT,
            ),
        ]
    )
    def test_profiles_flag_calls_by_lib(self, _name: str, seeded_events: list[str], expected_source: str) -> None:
        self._seed(seeded_events)

        profile = get_sdk_profile(self.team)

        assert profile.source_event == expected_source
        assert profile.flags_seen == 2
        by_lib = {lib.lib: lib for lib in profile.libs}
        assert set(by_lib) == {"web", "posthog-node", "posthog-ios"}

        web = by_lib["web"]
        assert (web.category, web.calls, web.distinct_ids) == ("web", 3, 3)
        assert web.anonymous_share == 2 / 3
        assert web.device_id_share == 2 / 3
        assert web.locally_evaluated_share is None

        node = by_lib["posthog-node"]
        assert (node.category, node.calls) == ("server", 2)
        assert node.locally_evaluated_share == 0.5
        assert node.anonymous_share is None
        assert node.device_id_share == 0.0

        ios = by_lib["posthog-ios"]
        assert (ios.category, ios.calls) == ("mobile", 2)
        assert ios.anonymous_share == 0.5
        assert ios.device_id_share == 0.0
        assert ios.locally_evaluated_share is None

        assert (profile.libs_on_any_event, profile.libs_on_any_event_truncated) == (None, False)

    def test_a_project_without_flag_calls_reports_the_libs_it_sends_from(self) -> None:
        # A project creating its first experiment has sent no multivariate flag call, so the flag
        # profile is empty and this fallback is all the caller has about the platform.
        _create_event(
            team=self.team,
            event="$screen",
            distinct_id="mobile-user",
            timestamp=timezone.now() - timedelta(hours=2),
            properties={"$lib": "posthog-ios"},
        )

        profile = get_sdk_profile(self.team)

        assert profile.libs == []
        assert profile.libs_on_any_event is not None
        assert [(lib.lib, lib.category, lib.events, lib.distinct_ids) for lib in profile.libs_on_any_event] == [
            ("posthog-ios", "mobile", 1, 1)
        ]
        assert profile.libs_on_any_event_truncated is False

    def test_more_libs_than_the_cap_are_truncated(self) -> None:
        for index in range(SDK_PROFILE_MAX_LIBS + 2):
            _create_event(
                team=self.team,
                event=DEFAULT_EXPOSURE_EVENT,
                distinct_id=f"user-{index}",
                timestamp=timezone.now() - timedelta(days=1),
                properties={
                    "$lib": f"lib-{index:02d}",
                    "$feature_flag": "checkout-flag",
                    "$feature_flag_response": "test",
                },
            )

        profile = get_sdk_profile(self.team)

        assert len(profile.libs) == SDK_PROFILE_MAX_LIBS
        assert profile.libs_truncated is True

    @parameterized.expand(
        [
            ("same_flag_on_both", "shared-flag", "shared-flag", True),
            ("different_flags", "web-flag", "server-flag", False),
        ]
    )
    def test_evaluated_on_server_and_web(self, _name: str, web_flag: str, server_flag: str, expected: bool) -> None:
        for lib, flag in [("web", web_flag), ("posthog-python", server_flag)]:
            _create_event(
                team=self.team,
                event=DEFAULT_EXPOSURE_EVENT,
                distinct_id=f"{lib}-user",
                timestamp=timezone.now() - timedelta(days=1),
                properties={"$lib": lib, "$feature_flag": flag, "$feature_flag_response": "test"},
            )

        profile = get_sdk_profile(self.team)

        assert profile.evaluated_on_server_and_web is expected
        assert profile.flags_evaluated_on_server_and_web == int(expected)


class TestTargetSurfaceAndCandidateMetric(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.team.test_account_filters = [
            {"key": "is_internal", "type": "event", "operator": "is_not", "value": ["true"]}
        ]
        self.team.test_account_filters_default_checked = True
        self.team.save()

    def _event(self, distinct_id: str, event: str, days_ago: float, **properties: Any) -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id=distinct_id,
            timestamp=timezone.now() - timedelta(days=days_ago),
            properties={"$lib": "web", "$current_url": "https://example.com/pricing", **properties},
        )

    def _seed(self) -> None:
        for distinct_id in ["converter", "browser", "early-buyer", "internal", "other-page"]:
            _create_person(team=self.team, distinct_ids=[distinct_id])
        # Two purchases after the first visit: converted, and both count toward the mean.
        self._event("converter", "$pageview", 3, **{"$is_identified": False, "$device_id": "d-1"})
        self._event("converter", "purchase", 2)
        self._event("converter", "purchase", 1)
        self._event("browser", "$pageview", 3, **{"$is_identified": True, "$device_id": "d-2"})
        # A purchase before the first visit counts toward the mean but is not a conversion.
        self._event("early-buyer", "purchase", 5)
        self._event("early-buyer", "$pageview", 4, **{"$is_identified": False})
        self._event("internal", "$pageview", 3, is_internal="true")
        self._event("internal", "purchase", 2, is_internal="true")
        self._event("other-page", "$pageview", 3, **{"$current_url": "https://example.com/about"})
        self._event("other-page", "purchase", 2)
        # Outside the window.
        self._event("browser", "$pageview", 20)

    def test_target_surface(self) -> None:
        self._seed()

        surface = get_target_surface(
            self.team, SetupContextInputs(target_event="$pageview", target_url_contains="PRICING")
        )

        assert surface.test_accounts_filtered is True
        assert surface.unique_persons == 3
        assert surface.exposures_per_day_estimate == 3 / 14
        assert [(lib.lib, lib.category, lib.unique_persons) for lib in surface.libs] == [("web", "web", 3)]
        assert surface.anonymous_share == 2 / 3
        assert surface.device_id_share == 2 / 3

    def test_shares_come_from_the_rows_whichever_sdk_sent_them(self) -> None:
        # A mobile surface carries $is_identified and $device_id as well, so the shares have to
        # come from every SDK rather than from the web rows alone.
        for distinct_id, identified in [("ios-anon", False), ("ios-user", True)]:
            _create_person(team=self.team, distinct_ids=[distinct_id])
            _create_event(
                team=self.team,
                event="$screen",
                distinct_id=distinct_id,
                timestamp=timezone.now() - timedelta(days=1),
                properties={"$lib": "posthog-ios", "$is_identified": identified, "$device_id": f"d-{distinct_id}"},
            )

        surface = get_target_surface(self.team, SetupContextInputs(target_event="$screen"))

        assert (surface.anonymous_share, surface.device_id_share) == (0.5, 1.0)
        assert [(lib.lib, lib.anonymous_share, lib.device_id_share) for lib in surface.libs] == [
            ("posthog-ios", 0.5, 1.0)
        ]

    def test_property_filters_narrow_the_target_and_the_metric(self) -> None:
        # A substring on $current_url cannot isolate a page: every page URL contains the homepage
        # URL. An exact $pathname can, and a metric can need a filter of its own too.
        for distinct_id, pathname in [("home-buyer", "/"), ("home-browser", "/"), ("pricing-visitor", "/pricing")]:
            _create_person(team=self.team, distinct_ids=[distinct_id])
            self._event(distinct_id, "$pageview", 3, **{"$pathname": pathname})
        for distinct_id, payment_method in [
            ("home-buyer", "card"),
            ("home-browser", "voucher"),
            ("pricing-visitor", "card"),
        ]:
            self._event(distinct_id, "checkout started", 2, payment_method=payment_method)

        homepage = SetupContextInputs(
            target_event="$pageview",
            target_properties=({"key": "$pathname", "type": "event", "operator": "exact", "value": ["/"]},),
            metric_event="checkout started",
            metric_properties=({"key": "payment_method", "type": "event", "operator": "exact", "value": ["card"]},),
        )
        surface = get_target_surface(self.team, homepage)
        metric = get_candidate_metric(self.team, homepage)

        assert surface.unique_persons == 2
        assert surface.target_properties == [{"key": "$pathname", "type": "event", "operator": "exact", "value": ["/"]}]
        # Both homepage visitors reach the target, and only a card checkout counts as a metric
        # event, so the voucher checkout drops out and the pricing visitor never reaches the target.
        assert (metric.persons_reached, metric.persons_converted) == (2, 1)
        assert (metric.event_volume, metric.unique_persons) == (2, 2)
        assert metric.metric_properties == [
            {"key": "payment_method", "type": "event", "operator": "exact", "value": ["card"]}
        ]

    def test_test_accounts_leave_the_counts_the_way_they_leave_a_new_experiment(self) -> None:
        # A new experiment gets filterTestAccounts from apply_exposure_criteria_defaults, not from
        # the project's test_account_filters_default_checked. Reading the team field instead would
        # count test accounts into a baseline the experiment then filters, so the running time the
        # caller computes from it comes out too short.
        self.team.test_account_filters_default_checked = False
        self.team.save()
        self._seed()

        surface = get_target_surface(self.team, SetupContextInputs(target_event="$pageview"))

        assert (surface.test_accounts_filtered, surface.unique_persons) == (True, 4)

    def test_a_changed_test_account_filter_is_not_served_from_the_cache(self) -> None:
        self._seed()
        inputs = SetupContextInputs(target_event="$pageview")
        assert get_target_surface(self.team, inputs).unique_persons == 4

        self.team.test_account_filters = []
        self.team.save()

        surface = get_target_surface(self.team, inputs)
        assert (surface.test_accounts_filtered, surface.unique_persons) == (False, 5)

    def test_a_repeated_call_is_served_from_the_cache(self) -> None:
        self._seed()
        inputs = SetupContextInputs(target_event="$pageview")
        first = get_target_surface(self.team, inputs)

        with patch("products.experiments.backend.setup_context.execute_hogql_query") as query:
            cached = get_target_surface(self.team, inputs)

        query.assert_not_called()
        assert cached == first

        narrowed = get_target_surface(
            self.team,
            SetupContextInputs(
                target_event="$pageview",
                target_properties=(
                    {"key": "$current_url", "type": "event", "operator": "icontains", "value": "about"},
                ),
            ),
        )
        assert (first.unique_persons, narrowed.unique_persons) == (4, 1)

    def test_candidate_metric_baseline_feeds_the_calculator(self) -> None:
        self._seed()

        metric = get_candidate_metric(
            self.team,
            SetupContextInputs(target_event="$pageview", target_url_contains="pricing", metric_event="purchase"),
        )

        assert metric.test_accounts_filtered is True
        assert (metric.persons_reached, metric.persons_converted) == (3, 1)
        assert metric.conversion_rate == 1 / 3
        assert (metric.event_volume, metric.unique_persons) == (4, 3)
        assert metric.mean_count_baseline_stats is not None
        assert asdict(metric.mean_count_baseline_stats) == {"number_of_samples": 3, "sum": 3.0, "sum_squares": 5.0}

        assert metric.funnel_baseline_stats is not None
        serializer = RunningTimeBaselineStatsSerializer(data=asdict(metric.funnel_baseline_stats))
        assert serializer.is_valid(), serializer.errors
        baseline = BaselineStats(**serializer.validated_data)
        assert calculate_baseline_value(baseline, "funnel") == 1 / 3

    def test_candidate_metric_without_target_returns_volume_only(self) -> None:
        self._seed()

        metric = get_candidate_metric(self.team, SetupContextInputs(metric_event="purchase"))

        assert (metric.event_volume, metric.unique_persons) == (4, 3)
        assert metric.persons_reached is None
        assert metric.funnel_baseline_stats is None

    def test_a_metric_event_that_never_occurred_is_told_apart_from_no_conversion(self) -> None:
        # A misspelled metric event and a real event nobody converted on both give a conversion
        # rate of 0, so only the volume tells them apart.
        self._seed()

        misspelled = get_candidate_metric(
            self.team,
            SetupContextInputs(target_event="$pageview", target_url_contains="pricing", metric_event="purchace"),
        )

        assert (misspelled.event_volume, misspelled.unique_persons) == (0, 0)
        assert misspelled.conversion_rate == 0.0


class TestPostgresSections(APIBaseTest):
    def _experiment(
        self,
        name: str,
        *,
        variants: list[int] | None = None,
        days_ago: int = 1,
        **fields: Any,
    ) -> Experiment:
        flag_fields = {
            key: fields.pop(key)
            for key in ("ensure_experience_continuity", "bucketing_identifier", "evaluation_runtime")
            if key in fields
        }
        flag = FeatureFlag.objects.create(
            team=self.team,
            key=f"flag-{name}",
            created_by=self.user,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": f"variant-{index}", "rollout_percentage": rollout}
                        for index, rollout in enumerate(variants or [50, 50])
                    ]
                },
            },
            **flag_fields,
        )
        experiment = Experiment.objects.create(team=self.team, name=name, feature_flag=flag, **fields)
        Experiment.objects.filter(pk=experiment.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        return experiment

    def _saved_metric(self, name: str, query: dict[str, Any]) -> ExperimentSavedMetric:
        return ExperimentSavedMetric.objects.create(team=self.team, name=name, query=query)

    def test_previous_experiments(self) -> None:
        now = timezone.now()
        self._experiment("deleted", deleted=True, days_ago=1)
        archived = self._experiment("archived", archived=True, days_ago=2)
        three_way = self._experiment(
            "three-way",
            variants=[34, 33, 33],
            start_date=now - timedelta(days=10),
            metrics=[_mean_metric("inline-primary")],
            exposure_criteria={"multiple_variant_handling": "first_seen"},
            bucketing_identifier="device_id",
            days_ago=3,
        )
        saved_primary = self._experiment(
            "saved-primary",
            variants=[80, 20],
            start_date=now - timedelta(days=30),
            end_date=now - timedelta(days=5),
            # No "kind": the exposure config defaults to an event config, the way stored rows do.
            exposure_criteria={"exposure_config": {"event": "checkout", "properties": []}},
            ensure_experience_continuity=True,
            days_ago=4,
        )
        ExperimentToSavedMetric.objects.create(
            experiment=saved_primary,
            saved_metric=self._saved_metric("Revenue", _mean_metric("saved-primary-uuid")),
            metadata={"type": "primary"},
        )
        for completed_days_ago, status, result in [
            (6, ExperimentMetricResult.Status.COMPLETED, _stored_result(500, [480], True)),
            (5, ExperimentMetricResult.Status.COMPLETED, _stored_result(40, [30], False)),
            (4, ExperimentMetricResult.Status.FAILED, _stored_result(9999, [9999], True)),
        ]:
            ExperimentMetricResult.objects.create(
                experiment=saved_primary,
                metric_uuid="saved-primary-uuid",
                query_from=now - timedelta(days=30),
                query_to=now - timedelta(days=completed_days_ago),
                status=status,
                result=result,
                completed_at=now - timedelta(days=completed_days_ago),
            )
        ExperimentMetricResult.objects.create(
            experiment=three_way,
            metric_uuid="inline-primary",
            query_from=now - timedelta(days=10),
            query_to=now,
            status=ExperimentMetricResult.Status.COMPLETED,
            result=_stored_result(0, [0, 0], False),
            completed_at=now,
        )

        with self.assertNumQueries(3):
            previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        by_name = {experiment.name: experiment for experiment in previous.experiments}
        assert list(by_name) == ["three-way", "saved-primary", "archived"]

        assert by_name["archived"].state == "draft"
        assert by_name["archived"].outcome is None
        assert by_name["archived"].multiple_variant_handling == "exclude"
        assert by_name["archived"].multiple_variant_handling_set is False

        three = by_name["three-way"]
        assert (three.state, three.variant_count, three.split_even) == ("running", 3, True)
        assert (three.multiple_variant_handling, three.multiple_variant_handling_set) == ("first_seen", True)
        assert three.bucketing_identifier == "device_id"
        assert (three.primary_metric_types, three.primary_metric_events) == (["mean"], ["purchase"])
        assert three.feature_flag_key == "flag-three-way"
        assert three.outcome is not None and three.outcome.analyzed_exposures == 0

        saved = by_name["saved-primary"]
        assert (saved.state, saved.split_even, saved.ensure_experience_continuity) == ("stopped", False, True)
        assert saved.custom_exposure_event == "checkout"
        assert (saved.exposure_property_filters, saved.activation_event) == ([], None)
        assert (saved.primary_metric_count, saved.shared_metric_count) == (1, 1)
        assert saved.outcome is not None
        assert (saved.outcome.analyzed_exposures, saved.outcome.any_variant_significant) == (70, False)
        assert (saved.outcome.metric_type, saved.outcome.metric_samples) == ("mean", 70)
        assert saved.outcome.control_baseline_value == 1 / 40
        assert saved.outcome.result_data_through == now - timedelta(days=5)

        assert asdict(previous.summary) == {
            "total": 3,
            "launched": 2,
            "launched_without_results": 0,
            "launched_with_unknown_analyzed_exposures": 0,
            "launched_with_zero_analyzed_exposures": 1,
            "launched_with_under_100_analyzed_exposures": 2,
            "using_device_id_bucketing": 1,
            "using_persistence": 1,
            "using_custom_exposure": 1,
            "using_exposure_property_filters": 0,
            "using_activation": 0,
            "using_uneven_split": 1,
            "serving_single_variant": 0,
        }
        assert archived.id in {experiment.id for experiment in previous.experiments}

    def test_a_shipped_flag_does_not_read_as_an_uneven_split(self) -> None:
        # Shipping a variant rewrites the flag so that variant holds 100 and the rest hold 0,
        # which is not the split the experiment ran with. Shipping refuses a draft, so the same
        # shape on a draft is a deliberate split.
        now = timezone.now()
        self._experiment("shipped", variants=[0, 100], start_date=now - timedelta(days=20), end_date=now)
        self._experiment("draft-at-full", variants=[0, 100])

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        by_name = {listed.name: listed for listed in previous.experiments}
        assert (by_name["shipped"].split_even, by_name["shipped"].serving_single_variant) == (None, "variant-1")
        assert (by_name["draft-at-full"].split_even, by_name["draft-at-full"].serving_single_variant) == (False, None)
        assert (previous.summary.using_uneven_split, previous.summary.serving_single_variant) == (1, 1)

    def test_a_default_exposure_narrowed_by_properties_is_reported(self) -> None:
        # The default-exposure check ignores properties, but the exposure query applies them to
        # the default event too, so the filters are what narrows this experiment.
        pathname_filter = {"key": "$pathname", "type": "event", "operator": "exact", "value": ["/"]}
        self._experiment(
            "narrowed",
            exposure_criteria={
                "exposure_config": {"event": DEFAULT_EXPOSURE_EVENT, "properties": [pathname_filter]},
                "activation_config": {"event": "signed up", "properties": []},
            },
        )

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        listed = previous.experiments[0]
        assert listed.custom_exposure_event is None
        assert listed.exposure_property_filters == [pathname_filter]
        assert (listed.activation_event, listed.activation_action_id) == ("signed up", None)
        assert (previous.summary.using_custom_exposure, previous.summary.using_exposure_property_filters) == (0, 1)
        assert previous.summary.using_activation == 1

    def test_the_outcome_comes_from_the_current_run_and_the_latest_data(self) -> None:
        now = timezone.now()
        start = now - timedelta(days=10)
        experiment = self._experiment("relaunched", start_date=start, metrics=[_mean_metric("inline-primary")])
        for query_from, query_to, completed_at, result in [
            # Reset and relaunch keeps the earlier run's rows, which carry the earlier start date.
            (
                now - timedelta(days=60),
                now - timedelta(days=31),
                now - timedelta(days=31),
                _stored_result(900, [900], True),
            ),
            # A backfilled older day, written after the newest day was written.
            (start, now - timedelta(days=2), now, _stored_result(20, [20], False)),
            (start, now - timedelta(days=1), now - timedelta(hours=2), _stored_result(30, [40], False)),
        ]:
            ExperimentMetricResult.objects.create(
                experiment=experiment,
                metric_uuid="inline-primary",
                query_from=query_from,
                query_to=query_to,
                status=ExperimentMetricResult.Status.COMPLETED,
                result=result,
                completed_at=completed_at,
            )

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        outcome = previous.experiments[0].outcome
        assert outcome is not None
        assert outcome.analyzed_exposures == 70
        assert outcome.result_data_through == now - timedelta(days=1)

    def test_a_start_date_moved_earlier_keeps_the_outcome(self) -> None:
        now = timezone.now()
        experiment = self._experiment(
            "edited-start", start_date=now - timedelta(days=10), metrics=[_mean_metric("inline-primary")]
        )
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="inline-primary",
            query_from=now - timedelta(days=10),
            query_to=now,
            status=ExperimentMetricResult.Status.COMPLETED,
            result=_stored_result(40, [40], False),
            completed_at=now,
        )
        Experiment.objects.filter(pk=experiment.pk).update(start_date=now - timedelta(days=12))

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        outcome = previous.experiments[0].outcome
        assert outcome is not None and outcome.analyzed_exposures == 80

    def test_a_draft_does_not_crowd_out_a_launched_experiment(self) -> None:
        self._experiment("fresh-draft", days_ago=0)
        self._experiment("older-launch", start_date=timezone.now() - timedelta(days=30), days_ago=10)

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=1)

        assert [listed.name for listed in previous.experiments] == ["older-launch"]

    @parameterized.expand(
        [
            ("no_criteria_at_all", {}, True),
            ("criteria_without_the_field", {"multiple_variant_handling": "first_seen"}, True),
            ("switched_off", {"filterTestAccounts": False}, False),
        ]
    )
    def test_test_account_filtering_reads_the_way_the_experiment_analyzes(
        self, _name: str, exposure_criteria: dict[str, Any], expected: bool
    ) -> None:
        # Criteria that leave the field out still filter test accounts in every metric and exposure
        # query, and many stored experiments leave it out. Reading the stored value raw would tell
        # the caller the opposite of what those experiments' results show.
        self._experiment("criteria", exposure_criteria=exposure_criteria)

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        assert previous.experiments[0].filter_test_accounts is expected

    def test_a_result_without_sample_counts_is_unknown_rather_than_zero(self) -> None:
        # "Analyzed nobody" is the signal this section exists to surface, so a result that simply
        # stores no counts must not land in it.
        now = timezone.now()
        experiment = self._experiment(
            "no-samples", start_date=now - timedelta(days=10), metrics=[_mean_metric("inline-primary")]
        )
        ExperimentMetricResult.objects.create(
            experiment=experiment,
            metric_uuid="inline-primary",
            query_from=now - timedelta(days=10),
            query_to=now,
            status=ExperimentMetricResult.Status.COMPLETED,
            result={"baseline": {"key": "control"}, "variant_results": [{"key": "test"}]},
            completed_at=now,
        )

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        outcome = previous.experiments[0].outcome
        assert outcome is not None and outcome.analyzed_exposures is None
        assert previous.summary.launched_with_unknown_analyzed_exposures == 1
        assert previous.summary.launched_with_zero_analyzed_exposures == 0
        assert previous.summary.launched_without_results == 0

    def test_a_boolean_flag_reports_no_variant_split(self) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="boolean-flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 40}]},
        )
        Experiment.objects.create(team=self.team, name="Boolean", feature_flag=flag)

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        assert (previous.experiments[0].variant_count, previous.experiments[0].split_even) == (0, None)
        assert previous.experiments[0].rollout_percentage == 40
        assert previous.summary.using_uneven_split == 0

    def test_an_action_exposure_is_reported_as_an_action(self) -> None:
        action = Action.objects.create(team=self.team, name="Saw pricing", steps_json=[{"event": "$pageview"}])
        self._experiment(
            "action-exposure", exposure_criteria={"exposure_config": {"kind": "ActionsNode", "id": action.id}}
        )

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        assert previous.experiments[0].custom_exposure_action_id == action.id
        assert previous.experiments[0].custom_exposure_event is None

    @parameterized.expand(
        [
            ("exposure_config_the_analysis_cannot_read", {"exposure_config": {"kind": "ActionsNode"}}),
            ("handling_that_is_no_longer_a_valid_choice", {"multiple_variant_handling": "whatever_this_was"}),
        ]
    )
    def test_criteria_the_analysis_rejects_still_describe_the_experiment(
        self, _name: str, exposure_criteria: dict[str, Any]
    ) -> None:
        # Older rows hold criteria the current schema rejects. The experiment still runs and still
        # analyzes on the defaults, so the section has to report it rather than fail the whole list.
        self._experiment("legacy-criteria", exposure_criteria=exposure_criteria)

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        listed = previous.experiments[0]
        assert (listed.custom_exposure_event, listed.custom_exposure_action_id) == (None, None)
        assert listed.multiple_variant_handling == "exclude"

    def test_state_reads_the_same_as_the_rest_of_the_product(self) -> None:
        now = timezone.now()
        launched: dict[str, Any] = {"start_date": now - timedelta(days=4)}
        experiments = [
            self._experiment("as-draft", days_ago=1),
            self._experiment("as-running", days_ago=2, **launched),
            self._experiment("as-paused", days_ago=3, **launched),
            self._experiment("as-frozen", days_ago=4, **launched),
            self._experiment("as-stopped", days_ago=5, end_date=now, **launched),
        ]
        paused, frozen = experiments[2], experiments[3]
        paused.feature_flag.active = False
        paused.feature_flag.save()
        for group in frozen.feature_flag.filters["groups"]:
            group[EXPOSURE_FROZEN_GROUP_KEY] = True
        frozen.feature_flag.save()

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        states = {listed.name: listed.state for listed in previous.experiments}
        assert states == {
            "as-draft": "draft",
            "as-running": "running",
            "as-paused": "paused",
            "as-frozen": "exposure_frozen",
            "as-stopped": "stopped",
        }
        # Agreement with status_label, which the experiment serializer and the dashboard widgets
        # read. A state added there but not here raises instead of being reported.
        for experiment in experiments:
            assert states[experiment.name] == Experiment.objects.get(pk=experiment.pk).status_label

    def test_the_outcome_describes_a_primary_metric_whose_samples_are_exposures(self) -> None:
        now = timezone.now()
        # Declared metric-z first, but ordered so the results page leads with metric-a.
        ordered = self._experiment(
            "ordered",
            start_date=now - timedelta(days=10),
            metrics=[_mean_metric("metric-z"), _mean_metric("metric-a")],
            primary_metrics_ordered_uuids=["metric-a", "metric-z"],
            days_ago=1,
        )
        # A second experiment whose first primary is metric-z, so metric-z rows for `ordered` come
        # back from the same query and must not be read as its outcome.
        other = self._experiment(
            "other", start_date=now - timedelta(days=10), metrics=[_mean_metric("metric-z")], days_ago=2
        )
        # A legacy metric listed first can never have a stored result, so it must not hide the
        # current metric's result behind it.
        mixed = self._experiment(
            "mixed",
            start_date=now - timedelta(days=10),
            metrics=[{"kind": "ExperimentTrendsQuery", "uuid": "legacy-first"}, _mean_metric("current")],
            days_ago=3,
        )
        # A retention result counts the units that did the start event, not the exposures, so the
        # funnel behind it is the metric this outcome can describe.
        retention_first = self._experiment(
            "retention-first",
            start_date=now - timedelta(days=10),
            metrics=[_retention_metric("retained"), _funnel_metric("converted")],
            days_ago=4,
        )
        retention_only = self._experiment(
            "retention-only",
            start_date=now - timedelta(days=10),
            metrics=[_retention_metric("retained-only")],
            days_ago=5,
        )
        for experiment, metric_uuid, result in [
            (ordered, "metric-a", _stored_result(10, [1], False)),
            (ordered, "metric-z", _stored_result(900, [99], True)),
            (other, "metric-z", _stored_result(3, [2], False)),
            (mixed, "current", _stored_result(40, [2], False)),
            (retention_first, "retained", _stored_result(7, [6], False)),
            (retention_first, "converted", _stored_result(400, [402], False, baseline_sum=24)),
            (retention_only, "retained-only", _stored_result(9, [8], False)),
        ]:
            ExperimentMetricResult.objects.create(
                experiment=experiment,
                metric_uuid=metric_uuid,
                query_from=now - timedelta(days=10),
                query_to=now,
                status=ExperimentMetricResult.Status.COMPLETED,
                result=result,
                completed_at=now,
            )

        previous = get_previous_experiments(Experiment.objects.filter(team_id=self.team.pk), limit=10)

        outcomes = {listed.name: listed.outcome for listed in previous.experiments}
        assert outcomes["ordered"] is not None and outcomes["ordered"].analyzed_exposures == 11
        assert outcomes["other"] is not None and outcomes["other"].analyzed_exposures == 5
        assert outcomes["mixed"] is not None and outcomes["mixed"].analyzed_exposures == 42

        funnel = outcomes["retention-first"]
        assert funnel is not None
        assert (funnel.metric_type, funnel.analyzed_exposures) == ("funnel", 802)
        assert funnel.control_baseline_value == 24 / 400

        retained = outcomes["retention-only"]
        assert retained is not None
        assert (retained.metric_type, retained.metric_samples, retained.analyzed_exposures) == ("retention", 17, None)
        assert retained.control_baseline_value is None
        assert previous.summary.launched_with_unknown_analyzed_exposures == 1

    def test_shared_metrics_rank_by_live_reuse_and_match_action_events(self) -> None:
        live_a = self._experiment("live-a")
        live_b = self._experiment("live-b")
        deleted_a = self._experiment("deleted-a", deleted=True)
        deleted_b = self._experiment("deleted-b", deleted=True)

        popular = self._saved_metric("Popular", _mean_metric("popular", event="signup"))
        inflated = self._saved_metric("Inflated by deleted", _mean_metric("inflated", event="signup"))
        action = Action.objects.create(team=self.team, name="Bought", steps_json=[{"event": "purchase"}])
        via_action = self._saved_metric(
            "Via action",
            {
                "kind": "ExperimentMetric",
                "metric_type": "funnel",
                "uuid": "via-action",
                "series": [{"kind": "ActionsNode", "id": action.id}],
            },
        )
        self._saved_metric(
            "Retention", _retention_metric("retention", start_event="purchase", completion_event="renewed")
        )
        for experiment, saved_metric, metric_type in [
            (live_a, popular, "primary"),
            (live_b, popular, "secondary"),
            (live_a, inflated, "primary"),
            (deleted_a, inflated, "primary"),
            (deleted_b, inflated, "primary"),
        ]:
            ExperimentToSavedMetric.objects.create(
                experiment=experiment, saved_metric=saved_metric, metadata={"type": metric_type}
            )

        # Three aggregates over the same experiments subquery; a refactor that unrolls them turns
        # the ranking into one query per metric.
        with self.assertNumQueries(1):
            ranked = self._shared_metrics()
        assert [(m.name, m.used_as_primary, m.used_as_secondary) for m in ranked.metrics] == [
            ("Popular", 1, 1),
            ("Inflated by deleted", 1, 0),
            ("Retention", 0, 0),
            ("Via action", 0, 0),
        ]
        assert ranked.metrics[0].events == ["signup"]
        assert ranked.metrics[0].metric_event_roles is None
        assert ranked.metric_event_match_truncated is False

        # A metric that only starts from the event is a different precedent from one that
        # converts on it, so the role the event plays has to come back with the match.
        matched = self._shared_metrics(metric_event="purchase")
        assert [(m.name, m.matches_metric_event, m.metric_event_roles) for m in matched.metrics] == [
            ("Retention", True, ["retention_start"]),
            ("Via action", True, ["funnel_step", "funnel_final_step"]),
            ("Popular", False, []),
            ("Inflated by deleted", False, []),
        ]
        assert matched.metrics[1].action_ids == [action.id]
        assert via_action.id == matched.metrics[1].id

    def test_reuse_by_an_experiment_the_caller_cannot_see_does_not_count(self) -> None:
        # The metric list respects access, so the counts beside it must too: otherwise they leak
        # that an experiment the caller cannot open uses the metric.
        visible = self._experiment("visible")
        hidden = self._experiment("hidden")
        metric = self._saved_metric("Revenue", _mean_metric("revenue"))
        for experiment in (visible, hidden):
            ExperimentToSavedMetric.objects.create(
                experiment=experiment, saved_metric=metric, metadata={"type": "primary"}
            )

        shared = self._shared_metrics(experiments=Experiment.objects.filter(pk=visible.pk))

        assert (shared.metrics[0].used_as_primary, shared.metrics[0].used_as_secondary) == (1, 0)

    def _shared_metrics(
        self, *, metric_event: str | None = None, experiments: QuerySet[Experiment] | None = None
    ) -> Any:
        return get_shared_metrics(
            self.team,
            ExperimentSavedMetric.objects.filter(team_id=self.team.pk),
            experiments=(experiments if experiments is not None else Experiment.objects.filter(team_id=self.team.pk)),
            limit=10,
            metric_event=metric_event,
        )


class TestBuildSetupContext(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @parameterized.expand(
        [
            ("clickhouse_timeout", ClickHouseQueryTimeOut(), "timed_out"),
            ("unexpected_error", RuntimeError("boom"), "error"),
        ]
    )
    def test_a_failing_query_fails_only_its_sections(self, _name: str, error: Exception, expected: str) -> None:
        with patch("products.experiments.backend.setup_context.execute_hogql_query", side_effect=error):
            context = build_setup_context(
                team=self.team,
                inputs=SetupContextInputs(target_event="$pageview", metric_event="purchase"),
                experiments=Experiment.objects.filter(team_id=self.team.pk),
                saved_metrics=ExperimentSavedMetric.objects.filter(team_id=self.team.pk),
            )

        assert [context.sdk_profile.status, context.target_surface.status, context.candidate_metric.status] == [
            expected
        ] * 3
        assert context.sdk_profile.data is None
        assert [
            context.team_defaults.status,
            context.previous_experiments.status,
            context.shared_metrics.status,
        ] == ["ok"] * 3

    def test_sections_without_input_are_skipped(self) -> None:
        context = build_setup_context(
            team=self.team,
            inputs=SetupContextInputs(),
            experiments=Experiment.objects.filter(team_id=self.team.pk),
            saved_metrics=ExperimentSavedMetric.objects.filter(team_id=self.team.pk),
        )

        assert (context.target_surface.status, context.candidate_metric.status) == ("skipped", "skipped")
        assert context.sdk_profile.status == "ok"
