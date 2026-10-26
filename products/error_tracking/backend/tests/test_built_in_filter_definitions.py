from typing import Any

from django.test import SimpleTestCase

from products.error_tracking.backend.logic.built_in_filter_definitions import (
    BUILT_IN_FILTERS,
    MAX_CACHED_REGEX_LENGTH,
    chunk_alternation,
)


def _regex_values(filters: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in filters.get("values", []):
        if "values" in value:
            values.extend(_regex_values(value))
        elif value.get("operator") == "regex":
            values.append(value["value"])
    return values


class TestBuiltInFilterDefinitions(SimpleTestCase):
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
