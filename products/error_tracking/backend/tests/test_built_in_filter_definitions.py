import json
import hashlib
from typing import Any

from django.test import SimpleTestCase

from products.error_tracking.backend.logic.built_in_filter_definitions import (
    BUILT_IN_FILTERS,
    MAX_CACHED_REGEX_LENGTH,
    chunk_alternation,
)

# Change a fingerprint only together with the version on the same line.
# A new version is what makes the refresh workflow rewrite the rules that teams already have.
EXPECTED_VERSIONS_AND_FINGERPRINTS = {
    "web_crawlers": (1, "33b05492aed24155"),
    "localhost": (1, "7ad200576377d96b"),
    "legacy_browsers": (1, "490c65a7a8b97684"),
    "react_hydration_errors": (1, "0267abc10a0c36bd"),
    "chunk_load_errors": (1, "b59788a16e9212be"),
    "resize_observer_loop": (1, "0a408f528a00d2dd"),
}


def _fingerprint(filters: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()[:16]


def _regex_values(filters: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in filters.get("values", []):
        if "values" in value:
            values.extend(_regex_values(value))
        elif value.get("operator") == "regex":
            values.append(value["value"])
    return values


class TestBuiltInFilterDefinitions(SimpleTestCase):
    def test_a_changed_definition_has_a_new_version(self) -> None:
        actual = {f.key: (f.version, _fingerprint(f.filters)) for f in BUILT_IN_FILTERS}

        assert actual == EXPECTED_VERSIONS_AND_FINGERPRINTS, (
            "A built-in filter definition changed. Bump its version so that the refresh workflow rewrites "
            "existing rules, then update EXPECTED_VERSIONS_AND_FINGERPRINTS."
        )

    def test_every_regex_fits_the_ingestion_regex_cache(self) -> None:
        for definition in BUILT_IN_FILTERS:
            for pattern in _regex_values(definition.filters):
                assert len(pattern) <= MAX_CACHED_REGEX_LENGTH, definition.key

    def test_chunk_alternation_keeps_every_pattern_in_order(self) -> None:
        patterns = [f"bot{i}" * 20 for i in range(30)]

        chunks = chunk_alternation(patterns, max_length=200)

        assert len(chunks) > 1
        assert all(len(chunk) <= 200 for chunk in chunks)
        assert "|".join(chunks) == "|".join(f"(?:{p})" for p in patterns)
