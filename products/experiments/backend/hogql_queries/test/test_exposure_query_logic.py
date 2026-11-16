import pytest

from parameterized import parameterized

from posthog.schema import (
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    ExperimentWarehouseNativeExposureConfig,
    MultipleVariantHandling,
)

from posthog.hogql.errors import ExposedHogQLError

from posthog.models.team import Team

from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    EXPERIMENT_EXPOSURE_EVENT,
    exposure_criteria_on_the_event,
    exposure_filters_off_the_event_narrow_who,
    get_exposure_event_and_property,
    get_multiple_variant_handling_from_experiment,
    get_test_accounts_filter,
    has_positive_test_account_filter,
    normalize_to_exposure_criteria,
)


def _event_config(event):
    return {"exposure_config": {"kind": "ExperimentEventExposureConfig", "event": event, "properties": []}}


_WAREHOUSE_NATIVE_EXPOSURE = ExperimentWarehouseNativeExposureConfig(
    connection_id="00000000-0000-0000-0000-000000000000",
    query="SELECT user_id AS entity_id, variant, exposed_at AS timestamp FROM exposures",
    unit={"unit_type": "customer", "id_namespace": "billing_customer_id"},
)


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

    def test_stored_warehouse_native_exposure_config_matches_the_typed_object(self):
        # Stored criteria are a dict. A dict read as an event config would slip past the
        # warehouse-native guards and fail later with an unrelated error.
        from_dict = normalize_to_exposure_criteria(
            {"exposure_config": _WAREHOUSE_NATIVE_EXPOSURE.model_dump(mode="json")}
        )

        assert from_dict == ExperimentExposureCriteria(exposure_config=_WAREHOUSE_NATIVE_EXPOSURE)


class TestExposureCriteriaOnTheEvent:
    @parameterized.expand(
        [
            # (name, filter, kept, can be left out)
            ("event_property", {"key": "plan", "value": "pro", "operator": "exact", "type": "event"}, True, True),
            (
                "event_semver",
                {"key": "$app_version", "value": "2.1.0", "operator": "semver_gte", "type": "event"},
                True,
                True,
            ),
            ("person_property", {"key": "plan", "value": "pro", "operator": "exact", "type": "person"}, False, True),
            ("cohort", {"key": "id", "value": 1, "type": "cohort"}, False, True),
            ("session", {"key": "$entry_pathname", "value": "/", "operator": "exact", "type": "session"}, False, True),
            (
                "event_date",
                {"key": "signup", "value": "2026-01-01", "operator": "is_date_after", "type": "event"},
                False,
                False,
            ),
            (
                "event_virtual_property",
                {"key": "$virt_is_bot", "value": "false", "operator": "exact", "type": "event"},
                False,
                False,
            ),
            (
                "event_cleaned_path",
                {"key": "$pathname", "value": "/a", "operator": "is_cleaned_path_exact", "type": "event"},
                False,
                False,
            ),
            ("element", {"key": "text", "value": "Buy", "operator": "exact", "type": "element"}, False, False),
            ("hogql", {"key": "timestamp >= toDateTime('2026-01-01', 'UTC')", "type": "hogql"}, False, False),
            (
                "event_metadata",
                {"key": "distinct_id", "value": "a", "operator": "exact", "type": "event_metadata"},
                False,
                False,
            ),
        ]
    )
    def test_keeps_only_the_filters_on_the_exposure_event(self, _name, prop, kept, can_be_left_out):
        exposure_criteria = {
            "exposure_config": {"kind": "ExperimentEventExposureConfig", "event": "checkout", "properties": [prop]}
        }
        criteria = exposure_criteria_on_the_event(exposure_criteria)

        assert criteria is not None and isinstance(criteria.exposure_config, ExperimentEventExposureConfig)
        assert len(criteria.exposure_config.properties or []) == int(kept)
        assert exposure_filters_off_the_event_narrow_who(exposure_criteria) is (kept or can_be_left_out)


class TestGetExposureConfigParamsForBuilder:
    @parameterized.expand(
        [
            ("stored_dict", {"exposure_config": _WAREHOUSE_NATIVE_EXPOSURE.model_dump(mode="json")}),
            ("typed", ExperimentExposureCriteria(exposure_config=_WAREHOUSE_NATIVE_EXPOSURE)),
        ]
    )
    def test_refuses_warehouse_native_exposure_as_a_query_error(self, _name, exposure_criteria):
        with pytest.raises(ExposedHogQLError, match="cannot be calculated yet"):
            get_exposure_config_params_for_builder(exposure_criteria, Team(id=1, project_id=1), None)


class TestGetTestAccountsFilter:
    _team_filter = {"key": "$host", "type": "event", "value": "localhost", "operator": "not_icontains"}

    @parameterized.expand([(None,), ({},), ({"filterTestAccounts": True},)])
    def test_applies_team_filters_unless_opted_out(self, exposure_criteria):
        # Absent criteria follow DEFAULT_FILTER_TEST_ACCOUNTS, the same read the main results
        # query applies, so this surface describes the same population as the results table.
        team = Team(id=1, project_id=1, test_account_filters=[self._team_filter])
        assert len(get_test_accounts_filter(team, exposure_criteria)) == 1

    def test_opting_out_skips_team_filters(self):
        team = Team(id=1, project_id=1, test_account_filters=[self._team_filter])
        assert get_test_accounts_filter(team, {"filterTestAccounts": False}) == []


class TestHasPositiveTestAccountFilter:
    @parameterized.expand(
        [
            ("positive_operator", [{"key": "$ip", "type": "event", "operator": "exact", "value": "203.0.113.1"}], True),
            ("missing_operator_means_exact", [{"key": "$ip", "type": "event", "value": "203.0.113.1"}], True),
            ("positive_cohort", [{"key": "id", "type": "cohort", "operator": "in", "value": 1}], True),
            (
                "one_positive_among_negative",
                [
                    {"key": "$host", "type": "event", "operator": "is_not", "value": ["localhost"]},
                    {"key": "$ip", "type": "event", "operator": "exact", "value": "203.0.113.1"},
                ],
                True,
            ),
            ("negative_cohort", [{"key": "id", "type": "cohort", "operator": "not_in", "value": 1}], False),
            ("hogql_only", [{"key": "properties.a = 1", "type": "hogql"}], False),
            ("no_filters", [], False),
            ("not_a_list", {}, False),
        ]
    )
    def test_reads_the_operator_of_each_filter(self, _name, filters, expected):
        assert has_positive_test_account_filter(Team(test_account_filters=filters)) is expected


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
