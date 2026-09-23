import copy
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.legacy_definitions import retain_legacy_flags, sanitize_legacy_definitions
from products.feature_flags.backend.local_evaluation import _apply_flag_dependency_transformation


def definition(key: str, filters: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    return {"key": key, "filters": filters if filters is not None else {}, **fields}


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
        ]
        + [
            (f"dependency_{key}", {"groups": [{"properties": [{"type": "flag", "key": key}]}]})
            for key in (None, True, False, 7.0, [7], {"id": 7})
        ]
        + [
            (f"cohort_{value}", {"groups": [{"properties": [{"type": "cohort", "key": "id", "value": value}]}]})
            for value in (None, "not-an-id", "", "7.5", [7], {"id": 7})
        ]
    )
    def test_excludes_invalid_targets_and_transitive_dependents(self, _name: str, filters: Any) -> None:
        flags = [
            definition("healthy", {"groups": []}),
            definition("unsupported", filters, id=7, active=False, deleted=True),
        ]
        for reference in ("7", 7, "unsupported"):
            for value in (True, False):
                key = f"dependent-{type(reference).__name__}-{reference}-{value}"
                flags.append(
                    definition(key, {"groups": [{"properties": [{"type": "flag", "key": reference, "value": value}]}]})
                )
                flags.append(
                    definition(
                        f"transitive-{key}",
                        {"groups": [{"properties": [{"type": "flag", "key": key, "value": value}]}]},
                    )
                )
        original = feed(flags)
        before = copy.deepcopy(original)
        assert sanitize_legacy_definitions(original)["flags"] == [flags[0]]
        assert original == before

    @parameterized.expand([("7",), (7,), ("excluded",)])
    def test_seed_excludes_the_flag_itself_and_transitive_dependents(self, reference: str | int) -> None:
        flags = [
            definition("healthy"),
            definition("excluded", id=7),
            definition("dependent", {"groups": [{"properties": [{"type": "flag", "key": reference, "value": False}]}]}),
            definition(
                "transitive", {"groups": [{"properties": [{"type": "flag", "key": "dependent", "value": True}]}]}
            ),
        ]
        before = copy.deepcopy(flags)
        assert retain_legacy_flags(flags, {"excluded"}) == [flags[0]]
        assert flags == before

    @parameterized.expand([(False, False), (False, True), (True, False), (True, True)])
    def test_exclusions_resolve_id_collisions_without_removing_independent_flags(
        self, seeded: bool, unsupported_numeric_key: bool
    ) -> None:
        unsupported = definition("7" if unsupported_numeric_key else "unsupported", {"version": 2}, id=8)
        healthy = definition("healthy" if unsupported_numeric_key else "8", id=7)
        flags = [healthy]
        if not seeded:
            flags.append(unsupported)
        for reference in (7, "7", 8, "8"):
            flags.append(
                definition(
                    f"dependent-{type(reference).__name__}-{reference}",
                    {"groups": [{"properties": [{"type": "flag", "key": reference, "value": False}]}]},
                )
            )
        flags.append(
            definition(
                "transitive",
                {"groups": [{"properties": [{"type": "flag", "key": "dependent-int-8", "value": True}]}]},
            )
        )
        result = sanitize_legacy_definitions(
            feed(flags), {unsupported["key"]} if seeded else None, {"8": unsupported["key"]} if seeded else None
        )
        assert [flag["key"] for flag in result["flags"]] == [healthy["key"], "dependent-int-7", "dependent-str-7"]

    def test_invalid_key_still_excludes_dependents_by_id(self) -> None:
        payload = feed(
            [
                definition("7", id=8),
                {"id": 7},
                definition("dependent", {"groups": [{"properties": [{"type": "flag", "key": 7, "value": False}]}]}),
            ]
        )
        assert [flag["key"] for flag in sanitize_legacy_definitions(payload)["flags"]] == ["7"]

    @parameterized.expand(
        [
            ("absent", {}),
            ("integer", {"version": 1}),
            ("float", {"version": 1.0}),
            ("null_groups", {"groups": None}),
            ("null_properties", {"groups": [{"properties": None}]}),
            ("integer_cohort", {"groups": [{"properties": [{"type": "cohort", "key": "id", "value": 7}]}]}),
            ("string_cohort", {"groups": [{"properties": [{"type": "cohort", "key": "id", "value": "7"}]}]}),
        ]
    )
    def test_preserves_supported_values_and_order(self, _name: str, filters: Any) -> None:
        payload = feed([definition("second", filters), definition("first")])
        assert sanitize_legacy_definitions(payload) is payload

    @parameterized.expand([(None,), ([],), ({},), ({"flags": {}, "cohorts": {}, "group_type_mapping": {}},)])
    def test_invalid_envelope_is_a_failure(self, payload: Any) -> None:
        with self.assertRaises(ValueError):
            sanitize_legacy_definitions(payload)

    def test_deep_cycle_keeps_independent_definition_and_finishes_transformation(self) -> None:
        flags = [
            definition(
                str(index),
                {"groups": [{"properties": [{"type": "flag", "key": str((index + 1) % 400), "value": False}]}]},
            )
            for index in range(400)
        ]
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
    )
    def test_malformed_nested_cohort_omits_only_affected_flags(self, properties: dict[str, Any]) -> None:
        payload = feed(
            [
                definition("healthy", {"groups": [{"properties": [{"type": "cohort", "value": "3"}]}]}),
                definition("uses-cohort", {"groups": [{"properties": [{"type": "cohort", "value": "1"}]}]}),
                definition(
                    "depends", {"groups": [{"properties": [{"type": "flag", "key": "uses-cohort", "value": False}]}]}
                ),
            ]
        )
        payload["cohorts"] = {
            "1": {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": 2}]},
            "2": properties,
            "3": {"type": "AND", "values": [{"type": "cohort", "key": "id", "value": 4}]},
            "4": {"type": "AND", "values": [{"type": "person", "key": "tier", "value": "example"}]},
        }
        result = sanitize_legacy_definitions(payload)
        assert [flag["key"] for flag in result["flags"]] == ["healthy"]
        assert result["cohorts"] == {key: payload["cohorts"][key] for key in ("3", "4")}
