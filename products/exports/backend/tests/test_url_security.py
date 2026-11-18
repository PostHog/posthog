from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.team import Team

from products.exports.backend.url_security import UNAUTHORIZED_HEATMAP_URL_REASON, is_heatmap_url_allowed


@override_settings(SITE_URL="https://us.posthog.com")
class TestIsHeatmapUrlAllowed(SimpleTestCase):
    def setUp(self) -> None:
        network_check = patch("products.exports.backend.url_security.is_url_allowed", return_value=(True, None))
        self.mock_is_url_allowed = network_check.start()
        self.addCleanup(network_check.stop)

    @parameterized.expand(
        [
            ("exact_match", ["https://example.com"], "https://example.com/pricing"),
            ("www_variant", ["https://example.com"], "https://www.example.com/pricing"),
            ("wildcard_subdomain", ["https://*.example.com"], "https://shop.example.com/cart"),
            ("one_of_several", ["https://example.org", "https://example.com"], "https://example.com/"),
            ("skips_empty_entries", [None, "https://example.com"], "https://example.com/"),
        ]
    )
    def test_allows_url_on_an_authorized_domain(self, _name: str, app_urls: list[str | None], url: str) -> None:
        assert is_heatmap_url_allowed(url, "click", Team(app_urls=app_urls)) == (True, None)
        self.mock_is_url_allowed.assert_called_once_with(url)

    @parameterized.expand(
        [
            ("other_domain", ["https://example.com"], "https://example.org/"),
            ("lookalike_suffix", ["https://example.com"], "https://example.com.example.org/"),
            ("userinfo_prefix", ["https://example.com"], "https://example.com@example.org/"),
            ("encoded_authority", ["https://example.com"], "https://example.com%2F@example.org/"),
            ("encoded_whole_url", ["https://example.com"], "https%3A%2F%2Fexample.com%2F"),
            ("no_authorized_urls", [], "https://example.com/"),
            ("instance_origin_without_authorization", [], "https://us.posthog.com/"),
        ]
    )
    def test_rejects_url_outside_authorized_domains(self, _name: str, app_urls: list[str], url: str) -> None:
        for heatmap_type in ("click", "iframe", "recording", None):
            assert is_heatmap_url_allowed(url, heatmap_type, Team(app_urls=app_urls)) == (
                False,
                UNAUTHORIZED_HEATMAP_URL_REASON,
            )
        self.mock_is_url_allowed.assert_not_called()

    def test_authorized_url_still_needs_the_network_check(self) -> None:
        self.mock_is_url_allowed.return_value = (False, "Disallowed target IP: 10.0.0.1")

        assert is_heatmap_url_allowed("https://example.com/", "click", Team(app_urls=["https://example.com"])) == (
            False,
            "Disallowed target IP: 10.0.0.1",
        )

    @parameterized.expand(
        [
            ("same_origin_without_authorized_urls", [], "https://us.posthog.com/api/environments/1/x/", True),
            ("cross_origin_on_authorized_domain", ["https://example.com"], "https://example.com/page", False),
        ]
    )
    def test_screenshot_type_keeps_the_instance_origin_rule(
        self, _name: str, app_urls: list[str], url: str, expected_allowed: bool
    ) -> None:
        allowed, reason = is_heatmap_url_allowed(url, "screenshot", Team(app_urls=app_urls))

        assert allowed is expected_allowed
        if not expected_allowed:
            assert reason == "Screenshot heatmap URL must use the PostHog instance origin"
