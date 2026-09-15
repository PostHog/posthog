from collections.abc import Callable
from typing import Any

import pytest

from parameterized import parameterized

from products.feature_flags.backend.facade.config import ConfigFormatError
from products.feature_flags.backend.facade.references import flag_dependency_properties, referenced_cohort_ids

COHORT_PROPERTY: dict[str, Any] = {"key": "id", "type": "cohort", "value": 42}
FLAG_PROPERTY: dict[str, Any] = {"key": "7", "type": "flag", "value": ["true"], "operator": "exact"}
V1_GROUPS: list[dict[str, Any]] = [{"properties": [COHORT_PROPERTY, FLAG_PROPERTY], "rollout_percentage": 100}]

# A stored v2 document from the contract fixtures, with invented identifiers.
V2_DOCUMENT: dict[str, Any] = {
    "version": 2,
    "return_type": "boolean",
    "default_value": False,
    "rules": [{"id": "11111111-1111-4111-8111-111111111111", "rule_type": "targeted_release", "value": True}],
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
