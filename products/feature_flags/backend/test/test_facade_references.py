from collections.abc import Callable
from typing import Any

import pytest

from parameterized import parameterized

from products.feature_flags.backend.facade.config import ConfigFormatError, decode_config
from products.feature_flags.backend.facade.references import (
    FlagReferences,
    InvalidIds,
    flag_dependency_properties,
    referenced_cohort_ids,
    references,
)

COHORT_PROPERTY: dict[str, Any] = {"key": "id", "type": "cohort", "value": 42}
FLAG_PROPERTY: dict[str, Any] = {"key": "7", "type": "flag", "value": ["true"], "operator": "exact"}
V1_GROUPS: list[dict[str, Any]] = [{"properties": [COHORT_PROPERTY, FLAG_PROPERTY], "rollout_percentage": 100}]

# A stored v2 document in the contract's shape, with invented identifiers.
V2_DOCUMENT: dict[str, Any] = {
    "version": 2,
    "return_type": "boolean",
    "default_value": False,
    "rules": [
        {
            "id": "11111111-1111-4111-8111-111111111111",
            "rule_type": "targeted_release",
            "targeting": {"properties": []},
            "value": True,
        }
    ],
}

UNSUPPORTED_DOCUMENTS = [
    ("v2_document", V2_DOCUMENT),
    ("v2_discriminator_with_v1_looking_groups", {"version": 2, "groups": V1_GROUPS}),
    ("string_discriminator", {"version": "1", "groups": V1_GROUPS}),
    ("boolean_discriminator", {"version": True, "groups": V1_GROUPS}),
    ("null_discriminator", {"version": None, "groups": V1_GROUPS}),
    ("unknown_future_version", {"version": 3, "groups": V1_GROUPS}),
    ("untrusted_discriminator", {"version": "<untrusted-version>", "groups": V1_GROUPS}),
]


class TestReferencedCohortIds:
    @parameterized.expand(
        [
            ("none_filters", None, set()),
            ("empty_filters", {}, set()),
            ("no_groups", {"multivariate": {}}, set()),
            ("empty_groups", {"groups": []}, set()),
            ("null_groups", {"groups": None}, set()),
            ("null_properties", {"groups": [{"properties": None, "rollout_percentage": 100}]}, set()),
            (
                "person_properties_only",
                {"groups": [{"properties": [{"type": "person", "key": "email", "value": "a@example.com"}]}]},
                set(),
            ),
            ("single_cohort", {"groups": [{"properties": [{"type": "cohort", "value": 123}]}]}, {123}),
            (
                "multiple_cohorts_same_group",
                {"groups": [{"properties": [{"type": "cohort", "value": 1}, {"type": "cohort", "value": 2}]}]},
                {1, 2},
            ),
            (
                "cohorts_across_groups",
                {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 10}]},
                        {"properties": [{"type": "cohort", "value": 20}]},
                    ]
                },
                {10, 20},
            ),
            ("string_value_coerced", {"groups": [{"properties": [{"type": "cohort", "value": "456"}]}]}, {456}),
            ("invalid_string_skipped", {"groups": [{"properties": [{"type": "cohort", "value": "bad"}]}]}, set()),
            ("none_value_skipped", {"groups": [{"properties": [{"type": "cohort", "value": None}]}]}, set()),
            ("missing_value_skipped", {"groups": [{"properties": [{"type": "cohort"}]}]}, set()),
            (
                "duplicates_collapsed",
                {
                    "groups": [
                        {"properties": [{"type": "cohort", "value": 5}]},
                        {"properties": [{"type": "cohort", "value": 5}]},
                    ]
                },
                {5},
            ),
            ("explicit_version_1", {"version": 1, "groups": V1_GROUPS}, {42}),
            ("explicit_version_1_float", {"version": 1.0, "groups": V1_GROUPS}, {42}),
        ]
    )
    def test_reads_v1_documents(self, _name: str, filters: dict | None, expected: set[int]) -> None:
        assert referenced_cohort_ids(filters) == expected


class TestFlagDependencyProperties:
    @parameterized.expand(
        [
            ("absent_version", {"groups": V1_GROUPS}),
            ("explicit_version_1", {"version": 1, "groups": V1_GROUPS}),
        ]
    )
    def test_returns_the_callers_own_flag_properties(self, _name: str, filters: dict) -> None:
        flag_property = filters["groups"][0]["properties"][1]

        returned = flag_dependency_properties(filters)

        assert len(returned) == 1
        # Consumers annotate the property in place, so identity matters, not equality.
        assert returned[0] is flag_property

    @parameterized.expand(
        [
            ("none_filters", None),
            ("null_groups", {"groups": None}),
            ("null_properties", {"groups": [{"properties": None}]}),
            ("cohort_only", {"groups": [{"properties": [COHORT_PROPERTY]}]}),
        ]
    )
    def test_reads_empty_v1_documents(self, _name: str, filters: dict | None) -> None:
        assert flag_dependency_properties(filters) == []


class TestUnsupportedFormatRejection:
    @parameterized.expand(
        [
            (f"{read.__name__}_{name}", read, filters)
            for read in (referenced_cohort_ids, flag_dependency_properties)
            for name, filters in UNSUPPORTED_DOCUMENTS
        ]
    )
    def test_rejects_before_reading_v1_keys(self, _name: str, read: Callable[[dict], Any], filters: dict) -> None:
        with pytest.raises(ConfigFormatError) as exc_info:
            read(filters)

        kind = exc_info.value.config_format.kind
        assert kind != "v1"
        # The message names the kind only, so a log line never carries the stored discriminator.
        assert str(exc_info.value) == f"config format {kind!r} is not handled here"


def _v2_document(*rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": 2,
        "return_type": "boolean",
        "default_value": False,
        "rules": [
            {
                "id": f"00000000-0000-4000-8000-00000000000{index}",
                "rule_type": "targeted_release",
                "targeting": {"properties": properties},
                "value": True,
            }
            for index, properties in enumerate(rules)
        ],
    }


def _cohort(value: object) -> dict[str, Any]:
    return {"key": "id", "type": "cohort", "value": value}


def _flag(key: object) -> dict[str, Any]:
    return {"key": key, "type": "flag", "operator": "flag_evaluates_to", "value": True}


class TestReferences:
    @parameterized.expand(
        [
            ("none_document", None, FlagReferences()),
            ("null_groups", {"groups": None}, FlagReferences()),
            ("null_properties", {"groups": [{"properties": None}]}, FlagReferences()),
            ("fixture_groups", {"groups": V1_GROUPS}, FlagReferences(cohort_ids=(42,), flag_ids=(7,))),
            (
                "first_seen_order_without_duplicates",
                {
                    "groups": [
                        {"properties": [_cohort(5), _flag("9"), _cohort("3")]},
                        {"properties": [_cohort(5), _flag(9), _flag("2")]},
                    ]
                },
                FlagReferences(cohort_ids=(5, 3), flag_ids=(9, 2)),
            ),
            (
                "v2_rule_targeting",
                _v2_document([_cohort(5), {"key": "email", "type": "person", "value": "a"}], [_flag("9"), _cohort(3)]),
                FlagReferences(cohort_ids=(5, 3), flag_ids=(9,)),
            ),
        ]
    )
    def test_reads_identities_from_either_format(self, _name: str, document: Any, expected: FlagReferences) -> None:
        assert references(decode_config(document)) == expected

    @parameterized.expand(
        [
            ("v1", {"groups": [{"properties": [_cohort(5), _flag("9")]}]}),
            ("v2", _v2_document([_cohort(5), _flag("9")])),
        ]
    )
    def test_returns_identities_not_the_stored_dicts(self, _name: str, document: dict[str, Any]) -> None:
        result = references(decode_config(document))

        properties = (
            document["groups"][0]["properties"]
            if "groups" in document
            else document["rules"][0]["targeting"]["properties"]
        )
        properties[0]["value"] = 6
        properties[1]["key"] = "10"

        assert result == FlagReferences(cohort_ids=(5,), flag_ids=(9,))

    @parameterized.expand(
        [
            (f"{version}_{name}", document)
            for name, invalid in (("string", "not-an-id"), ("null", None), ("object", {"id": 1}))
            for version, document in (
                ("v1", {"groups": [{"properties": [_cohort(invalid), _flag(invalid), _cohort(5), _flag("9")]}]}),
                ("v2", _v2_document([_cohort(invalid), _flag(invalid), _cohort(5), _flag("9")])),
            )
        ]
    )
    def test_invalid_ids_are_skipped_or_raised_per_reference_kind(self, _name: str, document: dict[str, Any]) -> None:
        config = decode_config(document)

        assert references(config) == FlagReferences(cohort_ids=(5,), flag_ids=(9,))
        with pytest.raises((TypeError, ValueError)):
            references(config, invalid_cohort_ids="raise")
        with pytest.raises((TypeError, ValueError)):
            references(config, invalid_flag_ids="raise")

    @parameterized.expand(
        [
            ("strict_cohorts", [_cohort(5), _flag("a-flag-key")], "raise", "skip", FlagReferences(cohort_ids=(5,))),
            ("strict_flags", [_cohort("not-an-id"), _flag("9")], "skip", "raise", FlagReferences(flag_ids=(9,))),
        ]
    )
    def test_a_strict_kind_ignores_invalid_ids_of_the_other_kind(
        self,
        _name: str,
        properties: list[dict[str, Any]],
        invalid_cohort_ids: InvalidIds,
        invalid_flag_ids: InvalidIds,
        expected: FlagReferences,
    ) -> None:
        config = decode_config({"groups": [{"properties": properties}]})

        result = references(config, invalid_cohort_ids=invalid_cohort_ids, invalid_flag_ids=invalid_flag_ids)

        assert result == expected

    @parameterized.expand(
        [
            ("group_not_an_object", {"groups": ["junk"]}, AttributeError),
            ("property_not_an_object", {"groups": [{"properties": ["junk"]}]}, AttributeError),
            ("groups_not_a_list", {"groups": 5}, TypeError),
        ]
    )
    def test_malformed_v1_structure_raises(self, _name: str, document: dict[str, Any], error: type[Exception]) -> None:
        with pytest.raises(error):
            references(decode_config(document))

    @parameterized.expand([(name, document) for name, document in UNSUPPORTED_DOCUMENTS if name != "v2_document"])
    def test_rejects_documents_in_no_readable_format(self, _name: str, document: dict[str, Any]) -> None:
        with pytest.raises(ConfigFormatError) as exc_info:
            references(decode_config(document))
        assert exc_info.value.config_format.kind == "unsupported"
