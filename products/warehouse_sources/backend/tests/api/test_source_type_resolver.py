from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.presentation.views.external_data_source.source_type_resolver import (
    resolve_source_type,
    suggest_source_types,
)

CANDIDATES = ["Postgres", "GoogleAds", "BigQuery", "Stripe", "AmazonS3", "Mailchimp"]


class TestSourceTypeResolver(SimpleTestCase):
    @parameterized.expand(
        [
            ("exact", "Postgres", "Postgres"),
            ("lowercase", "postgres", "Postgres"),
            ("uppercase", "STRIPE", "Stripe"),
            ("spaces", "google ads", "GoogleAds"),
            ("underscore", "google_ads", "GoogleAds"),
            ("hyphen", "Google-Ads", "GoogleAds"),
            ("mixed_separators", " big _query- ", "BigQuery"),
            ("digit_in_name", "amazon s3", "AmazonS3"),
            ("unknown", "NotARealSource", None),
            ("empty", "", None),
            ("only_separators", " _- ", None),
            ("partial_name", "Postgre", None),
        ]
    )
    def test_resolve_source_type(self, _name, value, expected):
        assert resolve_source_type(value, CANDIDATES) == expected

    @parameterized.expand(
        [
            ("exact_key_wins_over_ambiguous_variant", ["Foo_Bar", "FooBar", "foobar"], "FooBar", "FooBar"),
            ("ambiguous_variant_is_not_guessed", ["Foo_Bar", "FooBar"], "foo bar", None),
        ]
    )
    def test_resolve_source_type_with_colliding_keys(self, _name, candidates, value, expected):
        assert resolve_source_type(value, candidates) == expected

    @parameterized.expand(
        [
            ("typo", "Postgress", ["Postgres"]),
            ("truncated", "Postgre", ["Postgres"]),
            ("separator_typo", "google adz", ["GoogleAds"]),
            ("nothing_close", "zzzzzzzz", []),
            ("empty", "", []),
        ]
    )
    def test_suggest_source_types(self, _name, value, expected):
        assert suggest_source_types(value, CANDIDATES) == expected

    def test_suggest_source_types_limits_results(self):
        suggestions = suggest_source_types("source", ["Source1", "Source2", "Source3", "Source4"], limit=2)
        assert len(suggestions) == 2
