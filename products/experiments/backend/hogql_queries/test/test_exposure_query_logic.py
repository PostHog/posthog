import pytest

from parameterized import parameterized

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria, MultipleVariantHandling

from posthog.models.team import Team

from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    get_exposure_event_and_property,
    get_multiple_variant_handling_from_experiment,
    get_test_accounts_filter,
    normalize_to_exposure_criteria,
)


def _event_config(event):
    return {"exposure_config": {"kind": "ExperimentEventExposureConfig", "event": event, "properties": []}}


class TestGetExposureEventAndProperty:
    @parameterized.expand(
        [
            # (name, exposure criteria, resolved default event, expected (event, variant property))
            # Default-shaped configs must follow the resolved event the analysis queries count on,
            # or the replay surfaces that resolve (session buckets) read a different population.
            ("no_config", None, EXPERIMENT_EXPOSURE_EVENT, (EXPERIMENT_EXPOSURE_EVENT, "$feature_flag_response")),
            (
                "stored_default_config",
                _event_config("$feature_flag_called"),
                EXPERIMENT_EXPOSURE_EVENT,
                (EXPERIMENT_EXPOSURE_EVENT, "$feature_flag_response"),
            ),
            # An explicit $experiment_exposure config keeps its event either side of the rollout,
            # with the variant on $feature_flag_response since the event duplicates flag calls.
            (
                "explicit_rollout_event_config",
                _event_config("$experiment_exposure"),
                DEFAULT_EXPOSURE_EVENT,
                (EXPERIMENT_EXPOSURE_EVENT, "$feature_flag_response"),
            ),
            # Custom events and actions are untouched by the rollout.
            (
                "custom_event",
                _event_config("checkout_started"),
                EXPERIMENT_EXPOSURE_EVENT,
                ("checkout_started", "$feature/my-flag"),
            ),
            (
                "action",
                {"exposure_config": {"kind": "ActionsNode", "id": 42}},
                EXPERIMENT_EXPOSURE_EVENT,
                (None, "$feature/my-flag"),
            ),
            # Callers that deliberately stay on the legacy event pass it explicitly.
            (
                "legacy_event_passed_explicitly",
                None,
                DEFAULT_EXPOSURE_EVENT,
                (DEFAULT_EXPOSURE_EVENT, "$feature_flag_response"),
            ),
        ]
    )
    def test_resolves_default_exposure_against_the_rollout_event(
        self, _name, exposure_criteria, default_exposure_event, expected
    ):
        assert (
            get_exposure_event_and_property("my-flag", exposure_criteria, default_exposure_event=default_exposure_event)
            == expected
        )


class TestNormalizeToExposureCriteria:
    @pytest.mark.parametrize(
        "input_value,expected_type",
        [
            (None, type(None)),
            (ExperimentExposureCriteria(), ExperimentExposureCriteria),
            ({}, ExperimentExposureCriteria),
            ({"exposure_config": {"event": "test", "properties": []}}, ExperimentExposureCriteria),
        ],
    )
    def test_handles_different_input_types(self, input_value, expected_type):
        result = normalize_to_exposure_criteria(input_value)
        assert isinstance(result, expected_type)

    def test_does_not_mutate_input_dict(self):
        original = {"exposure_config": {"event": "test", "properties": []}}
        original_copy = original.copy()

        normalize_to_exposure_criteria(original)

        # Original dict should remain unchanged
        assert original == original_copy
        assert isinstance(original["exposure_config"], dict)

    def test_converts_nested_exposure_config(self):
        input_dict = {"exposure_config": {"event": "test_event", "properties": []}}

        result = normalize_to_exposure_criteria(input_dict)

        assert result is not None
        assert isinstance(result.exposure_config, ExperimentEventExposureConfig)
        assert result.exposure_config.event == "test_event"

    def test_converts_nested_activation_config(self):
        input_dict = {"activation_config": {"event": "purchase", "properties": []}}

        result = normalize_to_exposure_criteria(input_dict)

        assert result is not None
        assert isinstance(result.activation_config, ExperimentEventExposureConfig)
        assert result.activation_config.event == "purchase"

    def test_preserves_already_typed_object(self):
        typed_criteria = ExperimentExposureCriteria()

        result = normalize_to_exposure_criteria(typed_criteria)

        # Should return the exact same object, not a copy
        assert result is typed_criteria

    def test_drops_unknown_keys(self):
        # The write path historically accepted unknown top-level keys, so saved
        # criteria can carry e.g. a stray `properties` — the strict parse must not
        # break on them.
        input_dict = {
            "filterTestAccounts": True,
            "properties": [{"key": "email", "value": "test", "operator": "icontains", "type": "person"}],
        }

        result = normalize_to_exposure_criteria(input_dict)

        assert result is not None
        assert result.filterTestAccounts is True


class TestGetTestAccountsFilter:
    _team_filter = {"key": "$host", "type": "event", "value": "localhost", "operator": "not_icontains"}

    @parameterized.expand([(None,), ({},), ({"filterTestAccounts": False},)])
    def test_does_not_filter_unless_opted_in(self, exposure_criteria):
        # filterTestAccounts defaults to False: absent criteria must not pick up the team's filters.
        team = Team(id=1, project_id=1, test_account_filters=[self._team_filter])
        assert get_test_accounts_filter(team, exposure_criteria) == []

    def test_applies_team_filters_when_opted_in(self):
        team = Team(id=1, project_id=1, test_account_filters=[self._team_filter])
        assert len(get_test_accounts_filter(team, {"filterTestAccounts": True})) == 1


class TestGetMultipleVariantHandling:
    @parameterized.expand(
        [
            (None, MultipleVariantHandling.EXCLUDE),
            ({}, MultipleVariantHandling.EXCLUDE),
            ({"multiple_variant_handling": "first_seen"}, MultipleVariantHandling.FIRST_SEEN),
        ]
    )
    def test_defaults_to_exclude(self, exposure_criteria, expected):
        assert get_multiple_variant_handling_from_experiment(exposure_criteria) == expected
