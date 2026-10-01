import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria

from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig
from products.experiments.backend.hogql_queries.exposure_query_logic import EXPERIMENT_EXPOSURE_EVENT_CUTOFF
from products.experiments.backend.hogql_queries.utils import BayesianSettings, FrequentistSettings
from products.experiments.backend.metric_calculation.spec import ExperimentCalculationSettings, normalize_exposure, plan
from products.experiments.backend.metric_resolution import MetricRole, MetricSource
from products.experiments.backend.models.experiment import Experiment, ExperimentSavedMetric, ExperimentToSavedMetric
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.stats.shared.enums import DifferenceType
from products.feature_flags.backend.models.feature_flag import FeatureFlag

START = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
EXPOSURE = {"filterTestAccounts": True, "multiple_variant_handling": "first_seen"}
EXCLUDED = ["test-2"]
OS_BREAKDOWN = {"type": "event", "property": "$os_name"}
DEFINITIONS: dict[str, dict[str, Any]] = {
    "mean": {
        "kind": "ExperimentMetric",
        "metric_type": "mean",
        "source": {"kind": "EventsNode", "event": "purchase", "math": "sum", "math_property": "amount"},
    },
    "funnel": {
        "kind": "ExperimentMetric",
        "metric_type": "funnel",
        "series": [{"kind": "EventsNode", "event": "signup"}, {"kind": "EventsNode", "event": "purchase"}],
    },
    "ratio": {
        "kind": "ExperimentMetric",
        "metric_type": "ratio",
        "numerator": {"kind": "EventsNode", "event": "purchase", "math": "sum", "math_property": "amount"},
        "denominator": {"kind": "EventsNode", "event": "$pageview"},
    },
    "retention": {
        "kind": "ExperimentMetric",
        "metric_type": "retention",
        "start_event": {"kind": "EventsNode", "event": "signup"},
        "completion_event": {"kind": "EventsNode", "event": "purchase"},
        "retention_window_start": 1,
        "retention_window_end": 7,
        "retention_window_unit": "day",
        "start_handling": "first_seen",
    },
}

# Result rows written before key version 2 hold these hashes, and the display readers find them by the legacy
# key, so it must keep producing them. Keyed by (metric kind, breakdown, only_count_matured_users).
STORED_KEYS: dict[tuple[str, bool, bool], str] = {
    ("mean", False, False): "8c4c170619bed04837934834898b06c80e1ffb081cfc83e50394e7a90809e7f1",
    ("mean", False, True): "170e5a30b8b04a520777ec3cccac4e055f7038b64dd547263499ee75ea1b71fc",
    ("mean", True, False): "d9418c3005318f3a0a6981b2b75f0206ffe7b7f84b4a2f7247932d1d97f4f467",
    ("mean", True, True): "27dd63a2c60b41077a25c00da5a18a423776b7b737f2b454a6ef272e7f8e6abd",
    ("funnel", False, False): "2ec08b25f36bf0378e7bc215ae0e018dd676ad2e60e4e9a403bcbaa85906daab",
    ("funnel", False, True): "15ad6d37f74689c2d855977d98f8be2603db074526f4a5e87443631726a6e9a4",
    ("funnel", True, False): "b36542151b551ee82b08f64cddaaa7370462229630d8fe504414e09f65589810",
    ("funnel", True, True): "097f7e5ca118fa71c5b12f488ba09db0205931bc614385dc12a1ff4e243b0abe",
    ("ratio", False, False): "27aad466328984c484df1dae3277d2c2a340b26f0d2bf9dc75211e82918d131b",
    ("ratio", False, True): "18fed315c9fe9f5f64e2d7b5ccdc648cc33c3adcc41cedd47fdc215141acf69d",
    ("ratio", True, False): "15291a129138dd1f88cb99b815a5fa83b60ed47529969b521597aac0d7c01a0a",
    ("ratio", True, True): "8bcd1736f4ef024c1f59370cf5fadfb9e7257a7250967d7823f4310ee4763ef8",
    ("retention", False, False): "f2e0910b439d762b3bde9c87f893d93a67494cd720cda511a80e651b9e26c39a",
    ("retention", False, True): "2ef4f5ad56672d51e1c0014eaa1c0ef479edf31c91fe647276762ebb956c6302",
    ("retention", True, False): "964b72fe0c578d5341283cc942f0cd977a82a76344d36c5b34ada99878a09c8f",
    ("retention", True, True): "8a6fad45873cb5df74efabedb7bd33f1574deb53aeb6a3d06ca4fae4af063828",
}

STORED_KEY_CASES = [
    (
        f"{kind}_{source}{'_breakdown' if breakdown else ''}{'_matured' if matured else ''}",
        kind,
        source,
        breakdown,
        {"only_count_matured_users": matured},
        stored_key,
    )
    for (kind, breakdown, matured), stored_key in STORED_KEYS.items()
    for source in ("inline", "saved")
] + [
    (
        "frequentist",
        "mean",
        "inline",
        False,
        {"stats_config": {"method": "frequentist"}},
        "547cdafd4eb1feb4e0141877cac89d7ebf5743a856167357afeebc506484d930",
    ),
    (
        "no_exposure_criteria",
        "mean",
        "inline",
        False,
        {"exposure_criteria": None},
        "873e2ca8eccf41d7bc4c17c90bc7986c1a687a7ecd4efa9e2e6cc3dcb9fe319c",
    ),
    (
        "unsorted_repeated_exclusions",
        "mean",
        "inline",
        False,
        {"excluded_variants": ["test-3", "test-2", "test-3"]},
        "fb0618f7eca245137558b0df0ab259a6065ffb60d36141b2b2081456e5e70b9d",
    ),
    (
        "no_exclusions",
        "mean",
        "inline",
        False,
        {"excluded_variants": []},
        "6f5bef90e2346c391745571fdd712d894a314d2087e68ce97b96b9333b9caa9b",
    ),
    (
        "draft",
        "mean",
        "inline",
        False,
        {"start_date": None},
        "db178cb6fac5e977163f9ce6a70cbc7ff99b3648f93c95ca3460415d600560a3",
    ),
]


class TestCalculationSpec(BaseTest):
    def _flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            created_by=self.user,
            key=f"flag-{uuid4().hex[:8]}",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 34},
                        {"key": "test", "rollout_percentage": 33},
                        {"key": "test-2", "rollout_percentage": 33},
                    ]
                },
            },
        )

    def _experiment(self, flag: FeatureFlag | None = None, **overrides: Any) -> Experiment:
        fields: dict[str, Any] = {
            "start_date": START,
            "stats_config": {},
            "exposure_criteria": EXPOSURE,
            "excluded_variants": EXCLUDED,
            **overrides,
        }
        return Experiment.objects.create(
            team=self.team, created_by=self.user, feature_flag=flag or self._flag(), name="exp", **fields
        )

    def _add_metric(
        self,
        experiment: Experiment,
        kind: str,
        source: MetricSource,
        *,
        breakdown: bool = False,
        role: MetricRole = "secondary",
    ) -> None:
        definition = {**DEFINITIONS[kind], "uuid": f"{source}-{kind}", "name": f"{source} {kind}"}
        if source == "inline":
            if breakdown:
                definition["breakdownFilter"] = {"breakdowns": [OS_BREAKDOWN]}
            field = "metrics" if role == "primary" else "metrics_secondary"
            setattr(experiment, field, [*(getattr(experiment, field) or []), definition])
            experiment.save()
            return
        saved_metric = ExperimentSavedMetric.objects.create(team=self.team, name=uuid4().hex, query=definition)
        metadata: dict[str, Any] = {"type": role}
        if breakdown:
            metadata["breakdowns"] = [OS_BREAKDOWN]
        ExperimentToSavedMetric.objects.create(experiment=experiment, saved_metric=saved_metric, metadata=metadata)

    @parameterized.expand(STORED_KEY_CASES)
    def test_legacy_key_equals_the_stored_fingerprint(
        self,
        _name: str,
        kind: str,
        source: MetricSource,
        breakdown: bool,
        overrides: dict[str, Any],
        stored_key: str,
    ) -> None:
        experiment = self._experiment(**overrides)
        self._add_metric(experiment, kind, source, breakdown=breakdown)

        [spec] = plan(experiment)

        assert spec.legacy_key() == stored_key

    @parameterized.expand([("no_breakdowns", False), ("with_breakdowns", True)])
    def test_equivalent_inline_and_saved_metrics_have_equal_specs(self, _name: str, breakdown: bool) -> None:
        experiment = self._experiment()
        self._add_metric(experiment, "funnel", "inline", breakdown=breakdown, role="primary")
        self._add_metric(experiment, "funnel", "saved", breakdown=breakdown, role="secondary")

        inline_spec, saved_spec = plan(experiment)

        assert (inline_spec.metric_id, inline_spec.role) == ("inline-funnel", "primary")
        assert (saved_spec.metric_id, saved_spec.role) == ("saved-funnel", "secondary")
        assert inline_spec == saved_spec
        assert inline_spec.calculation_key() == saved_spec.calculation_key()

    def test_settings_resolve_team_defaults_and_flag_variants(self) -> None:
        team_config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        team_config.default_cuped_enabled = True
        team_config.default_cuped_lookback_days = 7
        team_config.default_sequential_testing_enabled = True
        team_config.default_sequential_tuning_parameter = 5000
        team_config.save()
        self.team.test_account_filters = [
            {"key": "email", "value": "@example.com", "operator": "not_icontains", "type": "person"}
        ]
        self.team.save()
        experiment = self._experiment(
            stats_config={"method": "frequentist", "frequentist": {"alpha": 0.1}}, exposure_criteria=None
        )
        self._add_metric(experiment, "mean", "inline")

        [spec] = plan(experiment)

        settings = spec.settings
        assert settings.variants == ("control", "test")
        assert settings.baseline == "control"
        assert settings.stats == FrequentistSettings(
            alpha=0.1,
            difference_type=DifferenceType.RELATIVE,
            sequential_testing_enabled=True,
            sequential_tuning_parameter=5000.0,
        )
        assert settings.cuped == CupedQueryConfig(enabled=True, lookback_days=7)
        assert settings.exposure is not None and settings.exposure.filter_test_accounts
        assert settings.test_account_filters == tuple(self.team.test_account_filters)

    @parameterized.expand(
        [
            (
                "absent_and_default_test_account_filtering",
                {"exposure_criteria": None},
                {"exposure_criteria": {"filterTestAccounts": True}},
            ),
            (
                "team_default_and_explicit_cuped",
                {"stats_config": {}},
                {"stats_config": {"cuped": {"enabled": True, "lookback_days": 14}}},
            ),
            (
                "inferred_and_explicit_baseline",
                {"stats_config": {}},
                {"stats_config": {"baseline_variant_key": "control"}},
            ),
            (
                "absent_and_explicit_default_exposure_event",
                {"exposure_criteria": {"filterTestAccounts": True}},
                {
                    "exposure_criteria": {
                        "filterTestAccounts": True,
                        "exposure_config": {
                            "kind": "ExperimentEventExposureConfig",
                            "event": "$feature_flag_called",
                            "properties": [],
                        },
                    }
                },
            ),
            (
                "tuning_parameter_without_sequential_testing",
                {"stats_config": {"method": "frequentist"}},
                {"stats_config": {"method": "frequentist", "frequentist": {"sequential_tuning_parameter": 10000}}},
            ),
        ]
    )
    def test_configurations_that_compute_the_same_thing_have_equal_specs(
        self, _name: str, first: dict[str, Any], second: dict[str, Any]
    ) -> None:
        team_config = get_or_create_team_extension(self.team, TeamExperimentsConfig)
        team_config.default_cuped_enabled = True
        team_config.save()
        flag = self._flag()
        specs = []
        for overrides in (first, second):
            experiment = self._experiment(flag, **overrides)
            self._add_metric(experiment, "mean", "inline")
            specs.extend(plan(experiment))

        first_spec, second_spec = specs
        assert first_spec == second_spec
        assert first_spec.calculation_key() == second_spec.calculation_key()

    @parameterized.expand(
        [
            ("baseline", "experiment", {"stats_config": {"baseline_variant_key": "test"}}, True),
            ("credible_interval", "experiment", {"stats_config": {"bayesian": {"ci_level": 0.9}}}, True),
            ("explicit_cuped", "experiment", {"stats_config": {"cuped": {"enabled": True}}}, True),
            ("team_default_cuped", "team_config", {"default_cuped_enabled": True}, True),
            ("alpha", "experiment", {"stats_config": {"frequentist": {"alpha": 0.1}}}, True),
            ("team_default_sequential", "team_config", {"default_sequential_testing_enabled": True}, True),
            ("flag_aggregation", "flag", {"aggregation_group_type_index": 0}, True),
            ("team_test_account_filters", "team", {"test_account_filters": [{"key": "email", "type": "person"}]}, True),
            ("test_account_filtering_off", "experiment", {"exposure_criteria": {"filterTestAccounts": False}}, True),
            ("name_and_description", "experiment", {"name": "renamed", "description": "new words"}, False),
            ("display_order", "experiment", {"primary_metrics_ordered_uuids": ["inline-mean"]}, False),
            ("end_date", "experiment", {"end_date": datetime(2026, 2, 1, tzinfo=UTC)}, False),
            ("conclusion", "experiment", {"conclusion": "won", "conclusion_comment": "shipped"}, False),
        ]
    )
    def test_the_key_changes_with_every_analytical_input_and_nothing_else(
        self, _name: str, target: str, changes: dict[str, Any], key_changes: bool
    ) -> None:
        # Alpha and sequential testing only reach the resolved settings of a frequentist experiment.
        base_stats = {"method": "frequentist"} if _name in ("alpha", "team_default_sequential") else {}
        experiment = self._experiment(stats_config=base_stats)
        self._add_metric(experiment, "mean", "inline", role="primary")
        [before] = plan(experiment)

        if target == "experiment":
            if "stats_config" in changes:
                changes = {"stats_config": {**base_stats, **changes["stats_config"]}}
            Experiment.objects.filter(pk=experiment.pk).update(**changes)
        elif target == "team_config":
            TeamExperimentsConfig.objects.filter(team=self.team).update(**changes)
        elif target == "flag":
            flag = experiment.feature_flag
            flag.filters = {**flag.filters, **changes}
            flag.save()
        else:
            for name, value in changes.items():
                setattr(self.team, name, value)
            self.team.save()
        get_or_create_team_extension(self.team, TeamExperimentsConfig)
        [after] = plan(Experiment.objects.get(pk=experiment.pk))

        assert (after.calculation_key() != before.calculation_key()) is key_changes

    def test_the_key_does_not_depend_on_the_exposure_event_rollout_flag(self) -> None:
        experiment = self._experiment(start_date=EXPERIMENT_EXPOSURE_EVENT_CUTOFF + timedelta(days=1))
        self._add_metric(experiment, "mean", "inline")
        specs = {}
        for flag_enabled in (False, True):
            with patch(
                "products.experiments.backend.hogql_queries.exposure_query_logic.posthoganalytics.feature_enabled",
                return_value=flag_enabled,
            ):
                [specs[flag_enabled]] = plan(experiment)

        # The query runner still counts the event the flag picks.
        assert [spec.settings.exposure and spec.settings.exposure.exposure_config for spec in specs.values()] == [
            ExperimentEventExposureConfig(event="$feature_flag_called", properties=[]),
            ExperimentEventExposureConfig(event="$experiment_exposure", properties=[]),
        ]
        assert specs[False] == specs[True]
        assert specs[False].calculation_key() == specs[True].calculation_key()

    @parameterized.expand(
        [
            ("unknown_exposure_criteria_key", {"exposure_criteria": {"filterTestAccounts": True, "unknown": 1}}),
            ("null_frequentist_settings", {"stats_config": {"method": "frequentist", "frequentist": None}}),
            ("non_object_cuped_settings", {"stats_config": {"cuped": ["enabled"]}}),
        ]
    )
    def test_configuration_the_runner_rejects_still_gets_a_key(self, _name: str, overrides: dict[str, Any]) -> None:
        experiment = self._experiment(**overrides)
        self._add_metric(experiment, "mean", "inline")

        [spec] = plan(experiment)

        assert len(spec.calculation_key()) == 64


_SETTINGS = ExperimentCalculationSettings(
    team_id=1,
    start_date=START,
    feature_flag_key="flag",
    aggregation_group_type_index=None,
    variants=("control", "test"),
    baseline="control",
    excluded_variants=(),
    exposure=None,
    normalized_exposure=normalize_exposure(None),
    test_account_filters=(),
    stats=BayesianSettings(ci_level=0.95, difference_type=DifferenceType.RELATIVE),
    cuped=CupedQueryConfig(),
    only_count_matured_users=False,
    timezone="UTC",
    stored_exposure_criteria=None,
)
_MEAN = {**DEFINITIONS["mean"], "uuid": "m1"}


@pytest.mark.parametrize(
    "variant,expected_equal",
    [
        ({**_MEAN, "breakdownFilter": {"breakdowns": []}}, True),
        ({**_MEAN, "breakdownFilter": {"breakdowns": None}}, True),
        ({**_MEAN, "breakdownFilter": None}, True),
        ({**_MEAN, "breakdownFilter": {"breakdowns": [OS_BREAKDOWN]}}, False),
    ],
)
def test_only_real_breakdowns_change_the_key(variant: dict, expected_equal: bool) -> None:
    base_key = _SETTINGS.spec_for(metric_id="m1", role="primary", definition=_MEAN).calculation_key()
    variant_key = _SETTINGS.spec_for(metric_id="m1", role="primary", definition=variant).calculation_key()
    assert (variant_key == base_key) is expected_equal


_FREQUENTIST = FrequentistSettings(
    alpha=0.05, difference_type=DifferenceType.RELATIVE, sequential_testing_enabled=False, sequential_tuning_parameter=0
)


@pytest.mark.parametrize(
    "stats,metric_change,expected_equal",
    [
        # `1 - 0.95` is how a confidence level becomes a stored alpha.
        (dataclasses.replace(_FREQUENTIST, alpha=1 - 0.95), {}, True),
        (dataclasses.replace(_FREQUENTIST, alpha=0.1), {}, False),
        (_FREQUENTIST, {"upper_bound_percentile": 0.9500000000000001}, True),
        (_FREQUENTIST, {"upper_bound_percentile": 0.9}, False),
        (_FREQUENTIST, {"conversion_window": 14.0}, True),
    ],
)
def test_float_noise_does_not_split_keys(
    stats: FrequentistSettings, metric_change: dict[str, Any], expected_equal: bool
) -> None:
    base = dataclasses.replace(_SETTINGS, stats=_FREQUENTIST)
    base_key = base.spec_for(
        metric_id="m1", role="primary", definition={**_MEAN, "upper_bound_percentile": 0.95, "conversion_window": 14}
    ).calculation_key()
    variant_key = (
        dataclasses.replace(_SETTINGS, stats=stats)
        .spec_for(
            metric_id="m1",
            role="primary",
            definition={**_MEAN, "upper_bound_percentile": 0.95, "conversion_window": 14, **metric_change},
        )
        .calculation_key()
    )
    assert (variant_key == base_key) is expected_equal


_SEQUENTIAL = dataclasses.replace(_FREQUENTIST, sequential_testing_enabled=True, sequential_tuning_parameter=5000)
_CUPED = CupedQueryConfig(enabled=True, lookback_days=14)
_RETENTION = {**DEFINITIONS["retention"], "uuid": "m1"}
_BROWSER_FILTER = {"key": "$browser", "type": "event", "value": ["Chrome"], "operator": "exact"}
_DEFAULT_EVENT_WITH_PROPERTIES: dict[str, Any] = {
    "filterTestAccounts": True,
    "multiple_variant_handling": "exclude",
    "exposure_config": {
        "kind": "ExperimentEventExposureConfig",
        "event": "$feature_flag_called",
        "properties": [_BROWSER_FILTER],
    },
}
_ACTION_ACTIVATION: dict[str, Any] = {
    "filterTestAccounts": False,
    "multiple_variant_handling": "first_seen",
    "activation_config": {
        "kind": "ActionsNode",
        "id": 7,
        "name": "Signed up",
        "properties": [{"key": "plan", "type": "person", "value": ["pro"], "operator": "exact"}],
    },
}
_CUSTOM_EVENT: dict[str, Any] = {
    "filterTestAccounts": True,
    "exposure_config": {"kind": "ExperimentEventExposureConfig", "event": "checkout_viewed", "properties": []},
}
_ACTION_EXPOSURE: dict[str, Any] = {"filterTestAccounts": True, "exposure_config": {"kind": "ActionsNode", "id": 7}}


def _with_exposure(
    criteria: dict[str, Any], settings: ExperimentCalculationSettings = _SETTINGS
) -> ExperimentCalculationSettings:
    return dataclasses.replace(settings, normalized_exposure=normalize_exposure(criteria))


# Each case changes one value that the calculation reads and expects a new key, or changes a value that the
# calculation ignores and expects the same key. Named after the field it changes.
_KEY_INPUT_CASES: list[tuple[str, ExperimentCalculationSettings, ExperimentCalculationSettings, dict, bool]] = [
    (
        "settings.start_date",
        _SETTINGS,
        dataclasses.replace(_SETTINGS, start_date=START + timedelta(days=1)),
        _MEAN,
        False,
    ),
    ("settings.feature_flag_key", _SETTINGS, dataclasses.replace(_SETTINGS, feature_flag_key="other"), _MEAN, False),
    (
        "settings.aggregation_group_type_index",
        _SETTINGS,
        dataclasses.replace(_SETTINGS, aggregation_group_type_index=0),
        _MEAN,
        False,
    ),
    ("settings.variants", _SETTINGS, dataclasses.replace(_SETTINGS, variants=("control", "test", "b")), _MEAN, False),
    ("settings.baseline", _SETTINGS, dataclasses.replace(_SETTINGS, baseline="test"), _MEAN, False),
    ("settings.excluded_variants", _SETTINGS, dataclasses.replace(_SETTINGS, excluded_variants=("b",)), _MEAN, False),
    (
        "settings.test_account_filters",
        _SETTINGS,
        dataclasses.replace(_SETTINGS, test_account_filters=({"key": "email", "type": "person"},)),
        _MEAN,
        False,
    ),
    ("settings.stats", _SETTINGS, dataclasses.replace(_SETTINGS, stats=_FREQUENTIST), _MEAN, False),
    ("settings.cuped", _SETTINGS, dataclasses.replace(_SETTINGS, cuped=_CUPED), _MEAN, False),
    (
        "settings.only_count_matured_users",
        _SETTINGS,
        dataclasses.replace(_SETTINGS, only_count_matured_users=True),
        _MEAN,
        False,
    ),
    ("settings.timezone", _SETTINGS, dataclasses.replace(_SETTINGS, timezone="Asia/Kolkata"), _RETENTION, False),
    *[
        (
            f"timezone_for_a_{kind}_metric",
            _SETTINGS,
            dataclasses.replace(_SETTINGS, timezone="Asia/Kolkata"),
            definition,
            True,
        )
        for kind, definition in (("mean", _MEAN), ("funnel", DEFINITIONS["funnel"]), ("ratio", DEFINITIONS["ratio"]))
    ],
    (
        "bayesian.ci_level",
        _SETTINGS,
        dataclasses.replace(_SETTINGS, stats=BayesianSettings(ci_level=0.9, difference_type=DifferenceType.RELATIVE)),
        _MEAN,
        False,
    ),
    (
        "bayesian.difference_type",
        _SETTINGS,
        dataclasses.replace(_SETTINGS, stats=BayesianSettings(ci_level=0.95, difference_type=DifferenceType.ABSOLUTE)),
        _MEAN,
        False,
    ),
    *[
        (
            f"frequentist.{name}",
            dataclasses.replace(_SETTINGS, stats=_SEQUENTIAL),
            dataclasses.replace(_SETTINGS, stats=changed),
            _MEAN,
            False,
        )
        for name, changed in (
            ("alpha", dataclasses.replace(_SEQUENTIAL, alpha=0.1)),
            ("difference_type", dataclasses.replace(_SEQUENTIAL, difference_type=DifferenceType.ABSOLUTE)),
            ("sequential_testing_enabled", dataclasses.replace(_SEQUENTIAL, sequential_testing_enabled=False)),
            ("sequential_tuning_parameter", dataclasses.replace(_SEQUENTIAL, sequential_tuning_parameter=10000)),
        )
    ],
    *[
        (
            f"cuped.{name}",
            dataclasses.replace(_SETTINGS, cuped=_CUPED),
            dataclasses.replace(_SETTINGS, cuped=changed),
            _MEAN,
            False,
        )
        for name, changed in (
            ("enabled", dataclasses.replace(_CUPED, enabled=False)),
            ("lookback_days", dataclasses.replace(_CUPED, lookback_days=7)),
        )
    ],
    *[
        (
            f"exposure_criteria.{name}",
            _with_exposure(_DEFAULT_EVENT_WITH_PROPERTIES),
            _with_exposure(changed),
            _MEAN,
            False,
        )
        for name, changed in (
            ("exposure_config", _CUSTOM_EVENT),
            (
                "activation_config",
                {**_DEFAULT_EVENT_WITH_PROPERTIES, "activation_config": _ACTION_ACTIVATION["activation_config"]},
            ),
            ("filterTestAccounts", {**_DEFAULT_EVENT_WITH_PROPERTIES, "filterTestAccounts": False}),
            (
                "multiple_variant_handling",
                {**_DEFAULT_EVENT_WITH_PROPERTIES, "multiple_variant_handling": "first_seen"},
            ),
        )
    ],
    (
        "exposure_config.event",
        _with_exposure(_CUSTOM_EVENT),
        _with_exposure(
            {**_CUSTOM_EVENT, "exposure_config": {**_CUSTOM_EVENT["exposure_config"], "event": "cart_viewed"}}
        ),
        _MEAN,
        False,
    ),
    (
        "exposure_config.properties",
        _with_exposure(_DEFAULT_EVENT_WITH_PROPERTIES),
        _with_exposure(
            {
                **_DEFAULT_EVENT_WITH_PROPERTIES,
                "exposure_config": {**_DEFAULT_EVENT_WITH_PROPERTIES["exposure_config"], "properties": []},
            }
        ),
        _MEAN,
        False,
    ),
    (
        "actions_node.id",
        _with_exposure(_ACTION_EXPOSURE),
        _with_exposure({**_ACTION_EXPOSURE, "exposure_config": {"kind": "ActionsNode", "id": 8}}),
        _MEAN,
        False,
    ),
    (
        "actions_node.properties",
        _with_exposure(_ACTION_EXPOSURE),
        _with_exposure(
            {**_ACTION_EXPOSURE, "exposure_config": {"kind": "ActionsNode", "id": 7, "properties": [_BROWSER_FILTER]}}
        ),
        _MEAN,
        False,
    ),
]


@pytest.mark.parametrize("_name,before,after,definition,keys_equal", _KEY_INPUT_CASES)
def test_the_key_follows_what_the_calculation_reads(
    _name: str,
    before: ExperimentCalculationSettings,
    after: ExperimentCalculationSettings,
    definition: dict,
    keys_equal: bool,
) -> None:
    before_key = before.spec_for(metric_id="m1", role="primary", definition=definition).calculation_key()
    after_key = after.spec_for(metric_id="m1", role="primary", definition=definition).calculation_key()
    assert (after_key == before_key) is keys_equal


def test_every_field_that_can_change_the_key_has_a_case() -> None:
    # The key reads explicit field lists, so a field added to one of these types reaches no key until someone adds
    # it. This fails until the new field has a case above, and the case fails until the key reads the field.
    compared_settings = {field.name for field in dataclasses.fields(ExperimentCalculationSettings) if field.compare}
    expected = (
        # The exposure_criteria cases cover normalized_exposure. The team is the tenant, not an input.
        {f"settings.{name}" for name in compared_settings - {"team_id", "normalized_exposure"}}
        | {f"bayesian.{field.name}" for field in dataclasses.fields(BayesianSettings)}
        | {f"frequentist.{field.name}" for field in dataclasses.fields(FrequentistSettings)}
        | {f"cuped.{field.name}" for field in dataclasses.fields(CupedQueryConfig)}
        | {f"exposure_criteria.{name}" for name in ExperimentExposureCriteria.model_fields}
        # The kind tells an event from an action, and the actions_node cases cover that. The response and the
        # version are not inputs of the query.
        | {
            f"exposure_config.{name}"
            for name in set(ExperimentEventExposureConfig.model_fields) - {"kind", "response", "version"}
        }
    )
    changing_cases = {name for name, *_rest, keys_equal in _KEY_INPUT_CASES if not keys_equal}
    assert expected <= changing_cases


@pytest.mark.parametrize(
    "settings,definition,key",
    [
        (_SETTINGS, _MEAN, "0ece714ef02b5e32a6201b72fccc0e2c908c3dd477b082d56f8d504c4b088a40"),
        (
            dataclasses.replace(
                _with_exposure(_DEFAULT_EVENT_WITH_PROPERTIES),
                stats=_FREQUENTIST,
                excluded_variants=("test-2",),
                test_account_filters=({"key": "email", "value": "@example.com", "type": "person"},),
                cuped=CupedQueryConfig(enabled=True, lookback_days=7),
            ),
            _MEAN,
            "d197595521eb7283bcd4afa83f37afa8db49731eb52e70a3494f28b961f8900b",
        ),
        (
            dataclasses.replace(_with_exposure(_ACTION_ACTIVATION), stats=_SEQUENTIAL, timezone="Europe/Berlin"),
            _RETENTION,
            "aebb0ab85180a4c2f0b341840f2e4399fe3acc042a62f638b511d301d88f481f",
        ),
    ],
)
def test_key_version_2_is_stable(settings: ExperimentCalculationSettings, definition: dict, key: str) -> None:
    # Every stored result is filed under this hash. A change to the hashed payload, such as a new settings field,
    # makes all of them unreachable for reuse, so it has to come with a CALCULATION_KEY_VERSION bump and new pins.
    assert settings.spec_for(metric_id="m1", role="primary", definition=definition).calculation_key() == key
