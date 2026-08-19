"""Tests for experiment metric result serialization helpers."""

import json

from django.test import SimpleTestCase

from parameterized import parameterized

from products.experiments.backend.result_serialization import sanitize_non_finite


class TestSanitizeNonFinite(SimpleTestCase):
    @parameterized.expand(
        [
            ("infinity", float("inf")),
            ("negative_infinity", float("-inf")),
            ("nan", float("nan")),
        ]
    )
    def test_replaces_non_finite_and_stays_valid_json(self, _name: str, bad_value: float) -> None:
        # Mirrors the two failure shapes seen in production: a non-finite `sum` on the baseline
        # and a non-finite value inside a variant `confidence_interval`.
        payload = {
            "baseline": {"sum": bad_value, "number_of_samples": 10},
            "variant_results": [{"key": "test", "confidence_interval": [bad_value, 1.0]}],
        }

        sanitized = sanitize_non_finite(payload)

        self.assertIsNone(sanitized["baseline"]["sum"])
        self.assertEqual(sanitized["baseline"]["number_of_samples"], 10)
        self.assertIsNone(sanitized["variant_results"][0]["confidence_interval"][0])
        self.assertEqual(sanitized["variant_results"][0]["confidence_interval"][1], 1.0)

        # The regression: Postgres rejects the `Infinity` / `NaN` tokens that json.dumps emits by
        # default, so the sanitized payload must serialize with them disallowed.
        json.dumps(sanitized, allow_nan=False)

    def test_leaves_finite_values_untouched(self) -> None:
        payload = {"sum": 3.5, "count": 2, "label": "ok", "nested": {"values": [1.0, 2.0]}}
        self.assertEqual(sanitize_non_finite(payload), payload)
