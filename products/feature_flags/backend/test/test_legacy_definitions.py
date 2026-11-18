import copy
from itertools import count
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.legacy_definitions import (
    cohort_references,
    drop_legacy_dependents,
    validate_legacy_filters,
)
from products.feature_flags.backend.local_evaluation import _apply_flag_dependency_transformation

_ids = count(1000)


def definition(key: str, filters: dict[str, Any] | None = None, flag_id: int | None = None) -> dict[str, Any]:
    return {"id": next(_ids) if flag_id is None else flag_id, "key": key, "filters": filters or {}}


def depends_on(key: str, reference: str | int, value: bool = False) -> dict[str, Any]:
    return definition(key, {"groups": [{"properties": [{"type": "flag", "key": reference, "value": value}]}]})


def feed(flags: list[dict[str, Any]]) -> dict[str, Any]:
    return {"flags": flags, "cohorts": {}, "group_type_mapping": {}, "minimal_flag_called_events": True}


class TestLegacyDefinitions(SimpleTestCase):
    @parameterized.expand(
        [(str(value), {"version": value, "groups": []}) for value in (2, 2.0, 3, "1", "2", True, False, None)]
        + [
            ("root_list", []),
            ("root_string", ""),
            ("root_number", 0),
            ("groups", {"groups": {}}),
            ("group", {"groups": [None]}),
            ("properties", {"groups": [{"properties": [None]}]}),
            ("payloads", {"payloads": []}),
            ("holdout", {"holdout": "control"}),
            ("multivariate", {"multivariate": []}),
            ("variants", {"multivariate": {"variants": [None]}}),
        ]
        + [
            (f"dependency_{key}", {"groups": [{"properties": [{"type": "flag", "key": key}]}]})
            for key in (None, True, False, 7.0, [7], {"id": 7})
        ]
        + [
            (f"cohort_{value}", {"groups": [{"properties": [{"type": "cohort", "key": "id", "value": value}]}]})
            for value in (None, "not-an-id", "", "7.5", True, False, 7.5, 7.0, [7], {"id": 7})
        ]
    )
    def test_rejects_unsupported_and_malformed_filters(self, _name: str, filters: Any) -> None:
        with self.assertRaises(ValueError):
            validate_legacy_filters(filters)

    @parameterized.expand(
        [
            ("absent", {}),
            ("null", None),
            ("integer", {"version": 1}),
            ("float", {"version": 1.0}),
            ("null_groups", {"groups": None}),
            ("null_properties", {"groups": [{"properties": None}]}),
            ("integer_cohort", {"groups": [{"properties": [{"type": "cohort", "key": "id", "value": 7}]}]}),
            ("string_cohort", {"groups": [{"properties": [{"type": "cohort", "key": "id", "value": "7"}]}]}),
        ]
    )
    def test_accepts_supported_filters(self, _name: str, filters: Any) -> None:
        validate_legacy_filters(filters)

    @parameterized.expand([("7",), (7,), ("excluded",)])
    def test_drops_transitive_dependents_of_excluded_flags(self, reference: str | int) -> None:
        flags = [
            definition("healthy"),
            depends_on("dependent", reference),
            depends_on("transitive", "dependent", value=True),
        ]
        before = copy.deepcopy(flags)
        assert drop_legacy_dependents(flags, {"7": "excluded"}) == [flags[0]]
        assert flags == before

    def test_without_exclusions_returns_the_same_list(self) -> None:
        flags = [definition("healthy"), depends_on("dependent", "missing")]
        assert drop_legacy_dependents(flags, {}) is flags

    @parameterized.expand([("numeric_excluded_key", True), ("named_excluded_key", False)])
    def test_exclusions_resolve_id_collisions_without_removing_independent_flags(
        self, _name: str, excluded_numeric_key: bool
    ) -> None:
        excluded_key = "7" if excluded_numeric_key else "unsupported"
        healthy = definition("healthy" if excluded_numeric_key else "8", flag_id=7)
        flags = [
            healthy,
            *(
                depends_on(f"dependent-{type(reference).__name__}-{reference}", reference)
                for reference in (7, "7", 8, "8")
            ),
            depends_on("transitive", "dependent-int-8", value=True),
        ]
        result = drop_legacy_dependents(flags, {"8": excluded_key})
        assert [flag["key"] for flag in result] == [healthy["key"], "dependent-int-7", "dependent-str-7"]

    def test_deep_cycle_keeps_independent_definition_and_finishes_transformation(self) -> None:
        flags = [depends_on(str(index), str((index + 1) % 400)) for index in range(400)]
        independent = definition("healthy")
        result = _apply_flag_dependency_transformation(feed([*flags, independent]), {})
        assert result["flags"][-1] == independent
        assert all(
            flag["filters"]["groups"][0]["properties"][0]["dependency_chain"] == [] for flag in result["flags"][:-1]
        )

    @parameterized.expand(
        [
            ({"values": [None]},),
            ({"type": "AND", "values": [{"values": [{"type": "person", "key": "tier", "value": "example"}]}]},),
            ({"type": "AND", "values": [{"type": "person", "value": "example"}]},),
            ({"type": "AND", "values": [{"type": "person", "key": "tier"}]},),
        ]
        + [
            ({"type": "AND", "values": [{"type": "cohort", "key": "id", "value": value}]},)
            for value in (None, "not-an-id", "", "7.5", True, False, 7.5, 7.0, [7], {"id": 7})
        ]
    )
    def test_rejects_malformed_cohort_properties(self, properties: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            cohort_references(properties)

    def test_collects_nested_cohort_references(self) -> None:
        properties = {
            "type": "OR",
            "values": [
                {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": 2}]},
                {"type": "cohort", "key": "id", "value": "3"},
                {},
            ],
        }
        assert cohort_references(properties) == {"2", "3"}
