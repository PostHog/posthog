import re

from django.test import SimpleTestCase

from parameterized import parameterized

from products.wizard.backend.tool_catalog.derived import env_key_pattern


class TestDerivedEnvKeyPattern(SimpleTestCase):
    @parameterized.expand(
        [
            ("single_word", "Zendesk", ["ZENDESK_API_TOKEN"], ["ZENDESKER", "MY_ZENDESK_KEY"]),
            ("split_and_joined", "QuickBooks", ["QUICKBOOKS_CLIENT_ID", "QUICK_BOOKS_TOKEN"], ["QUICK_TOKEN"]),
            ("acronym", "ZohoCRM", ["ZOHO_CRM_KEY", "ZOHOCRM_KEY"], ["ZOHO_KEY"]),
        ]
    )
    def test_matches_vendor_keys_only(self, _name: str, source: str, matches: list[str], misses: list[str]) -> None:
        pattern = env_key_pattern(source)
        assert pattern is not None
        for key in matches:
            assert re.match(pattern, key), key
        for key in misses:
            assert not re.match(pattern, key), key

    @parameterized.expand([("generic_word", "Branch"), ("too_short", "Box")])
    def test_skips_names_that_would_match_unrelated_keys(self, _name: str, source: str) -> None:
        assert env_key_pattern(source) is None
