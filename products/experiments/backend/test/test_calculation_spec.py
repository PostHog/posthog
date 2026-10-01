import json
import dataclasses
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import ActionsNode, ExperimentEventExposureConfig, MultipleVariantHandling

from posthog.models.team.extensions import get_or_create_team_extension

from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig
from products.experiments.backend.hogql_queries.experiment_query_builder import ExposureQueryParams
from products.experiments.backend.hogql_queries.utils import BayesianSettings, FrequentistSettings
from products.experiments.backend.metric_calculation.spec import (
    CalculationSpec,
    ExperimentCalculationSettings,
    StoredSpec,
    plan,
)
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

# Result rows and stored `fingerprint` values of these configurations already hold these hashes, so the
# calculation key must keep producing them. Keyed by (metric kind, breakdown, only_count_matured_users).
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
    def test_key_equals_the_stored_fingerprint(
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

        assert spec.calculation_key() == stored_key

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


_FREQUENTIST_SETTINGS = dataclasses.replace(
    _SETTINGS,
    start_date=datetime(2026, 1, 5, 10, 30, 15, 250000, tzinfo=ZoneInfo("Europe/Oslo")),
    aggregation_group_type_index=0,
    variants=("control", "test"),
    excluded_variants=("test-2",),
    exposure=ExposureQueryParams(
        exposure_config=ExperimentEventExposureConfig(
            event="$experiment_exposure",
            properties=[{"key": "plan", "value": ["pro"], "operator": "exact", "type": "event"}],
        ),
        activation_config=ActionsNode(id=7, name="Activated"),
        multiple_variant_handling=MultipleVariantHandling.FIRST_SEEN,
        filter_test_accounts=True,
    ),
    test_account_filters=({"key": "email", "value": "@example.com", "operator": "not_icontains", "type": "person"},),
    stats=FrequentistSettings(
        alpha=0.050000000000000044,
        difference_type=DifferenceType.ABSOLUTE,
        sequential_testing_enabled=True,
        sequential_tuning_parameter=5000,
    ),
    cuped=CupedQueryConfig(enabled=True, lookback_days=7),
    only_count_matured_users=True,
    timezone="Europe/Oslo",
    stored_exposure_criteria={"filterTestAccounts": True, "multiple_variant_handling": "first_seen"},
)
_DRAFT_SETTINGS = dataclasses.replace(
    _SETTINGS,
    start_date=None,
    exposure=ExposureQueryParams(
        exposure_config=ActionsNode(id=3),
        activation_config=None,
        multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
        filter_test_accounts=False,
    ),
)


@pytest.mark.parametrize(
    "settings,definition",
    [
        (_SETTINGS, _MEAN),
        (_FREQUENTIST_SETTINGS, {**DEFINITIONS["funnel"], "uuid": "m1", "breakdownFilter": {"breakdowns": []}}),
        (_DRAFT_SETTINGS, {**DEFINITIONS["retention"], "uuid": "m1", "name": "Retention", "fingerprint": "f" * 64}),
    ],
    ids=["bayesian_without_exposure", "frequentist_with_exposure_and_filters", "draft_with_action_exposure"],
)
def test_a_stored_spec_decodes_to_the_spec_it_stored(
    settings: ExperimentCalculationSettings, definition: dict[str, Any]
) -> None:
    spec = settings.spec_for(metric_id="m1", role="secondary", definition=definition)
    stored = StoredSpec.of(spec)

    decoded = StoredSpec(spec_version=stored.spec_version, payload=json.loads(json.dumps(stored.payload))).decode()

    assert decoded == spec
    assert decoded.calculation_key() == spec.calculation_key()
    assert (decoded.metric_id, decoded.role, decoded.definition, decoded.settings.stored_exposure_criteria) == (
        spec.metric_id,
        spec.role,
        spec.definition,
        spec.settings.stored_exposure_criteria,
    )


# A spec in the version 1 form, as result rows store it. It has the configuration of the ("mean", False, False)
# case in STORED_KEYS, so it must keep decoding to that key.
_STORED_VERSION_1_PAYLOAD: dict[str, Any] = {
    "metric_id": "inline-mean",
    "role": "secondary",
    "definition": {**DEFINITIONS["mean"], "uuid": "inline-mean", "name": "inline mean"},
    "settings": {
        "team_id": 1,
        "start_date": "2026-01-05T09:30:00+00:00",
        "feature_flag_key": "flag",
        "aggregation_group_type_index": None,
        "variants": ["control", "test"],
        "baseline": "control",
        "excluded_variants": ["test-2"],
        "exposure": {
            "exposure_config": {
                "event": "$feature_flag_called",
                "kind": "ExperimentEventExposureConfig",
                "properties": [],
                "response": None,
                "version": None,
            },
            "activation_config": None,
            "multiple_variant_handling": "first_seen",
            "filter_test_accounts": True,
        },
        "test_account_filters": [],
        "stats": {"method": "bayesian", "ci_level": 0.95, "difference_type": "relative"},
        "cuped": {"enabled": False, "lookback_days": 14},
        "only_count_matured_users": False,
        "timezone": "UTC",
        "stored_exposure_criteria": EXPOSURE,
    },
}


def test_a_version_1_spec_keeps_decoding_to_its_key() -> None:
    decoded: CalculationSpec = StoredSpec(spec_version=1, payload=_STORED_VERSION_1_PAYLOAD).decode()

    assert decoded.spec_version == 1
    assert decoded.calculation_key() == STORED_KEYS[("mean", False, False)]
