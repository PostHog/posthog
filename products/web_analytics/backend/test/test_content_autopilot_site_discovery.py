from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.web_analytics.backend.content_autopilot.site_discovery import (
    _MAX_DISCOVERY_REQUESTS,
    discover_site,
    has_same_public_origin,
    has_same_public_site,
    normalize_site_origin,
)
from products.web_analytics.backend.public_url_fetch import FetchedPublicUrl, PublicUrlFetchError


def _response(*, status: int = 200, body: bytes = b"", location: str | None = None) -> FetchedPublicUrl:
    return FetchedPublicUrl(status_code=status, headers={"location": location} if location else {}, body=body)


class TestContentAutopilotSiteDiscovery(SimpleTestCase):
    @parameterized.expand(
        [
            ("lowercase_host", "HTTPS://Example.COM/guides?q=1#top", "https://example.com"),
            ("default_port", "https://example.com:443/path", "https://example.com"),
            ("custom_port", "http://example.com:8080/path", "http://example.com:8080"),
            ("fully_qualified_dot", "https://example.com./path", "https://example.com"),
            ("unicode_host", "https://ПРИМЕР.РФ/guides?q=1", "https://xn--e1afmkfd.xn--p1ai"),
            ("punycode_host", "https://xn--e1afmkfd.xn--p1ai", "https://xn--e1afmkfd.xn--p1ai"),
            ("ipv6_host", "https://[::1]:8443/path", "https://[::1]:8443"),
        ]
    )
    def test_normalizes_site_origin(self, _name: str, raw_url: str, expected: str) -> None:
        self.assertEqual(normalize_site_origin(raw_url), expected)

    def test_matches_one_site_across_unicode_and_punycode_spellings(self) -> None:
        punycode_sitemap = "https://xn--e1afmkfd.xn--p1ai/sitemap.xml"

        self.assertTrue(has_same_public_origin(punycode_sitemap, normalize_site_origin("https://пример.рф")))
        self.assertTrue(has_same_public_site(punycode_sitemap, "https://пример.рф"))

    @parameterized.expand(
        [
            ("unsupported_scheme", "ftp://example.com"),
            ("missing_host", "https:///guides"),
            ("credentials", "https://token@example.com"),
            ("invalid_port", "https://example.com:not-a-port"),
            ("zero_port", "https://example.com:0"),
            ("backslash_authority", "https://example.com\\@evil.example"),
            ("encoded_backslash_authority", "https://example.com%5c@evil.example"),
        ]
    )
    def test_rejects_invalid_site_origin(self, _name: str, raw_url: str) -> None:
        with self.assertRaises(ValueError):
            normalize_site_origin(raw_url)

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_detects_site_defaults_and_sitemap(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url.endswith("/robots.txt"):
                return _response(
                    body=b"User-agent: *\nSitemap: https://example.com/content-sitemap.xml",
                )
            if url == "https://example.com/":
                return _response(body=b"<html><head><title>Example Docs | Guides</title></head></html>")
            if url.endswith("/content-sitemap.xml"):
                return _response(body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" />')
            return _response(status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("HTTPS://Example.com/docs")

        self.assertEqual(result["name"], "Example Docs")
        self.assertEqual(result["domain"], "https://example.com")
        self.assertEqual(result["source_urls"], ["https://example.com/content-sitemap.xml"])
        self.assertTrue(result["sitemap_detected"])
        self.assertEqual(result["warnings"], [])

    @parameterized.expand(
        [
            (
                "prefers_og_site_name",
                b'<meta property="og:site_name" content="Example"><title>Pricing | Example Docs</title>',
                "Example",
            ),
            ("falls_back_to_the_title", b"<title>Example Docs | Guides</title>", "Example Docs"),
            ("falls_back_to_the_hostname", b"<html><head></head></html>", "example.com"),
            (
                "strips_control_characters_and_bidi_marks",
                b'<meta property="og:site_name" content="Example\x00 \xe2\x80\xae Docs">',
                "Example Docs",
            ),
        ]
    )
    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_names_the_site(self, _name: str, homepage: bytes, expected: str, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url == "https://example.com/":
                return _response(body=homepage)
            return _response(status=404)

        fetch_public_url.side_effect = response_for

        self.assertEqual(discover_site("https://example.com")["name"], expected)

    @parameterized.expand(
        [
            ("www_variant", "https://www.example.com/sitemap.xml", True),
            ("subdomain", "https://docs.example.com/sitemap.xml", True),
            ("unrelated_site", "https://cdn.other-site.example/sitemap.xml", False),
        ]
    )
    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_keeps_a_redirected_sitemap_url_on_the_profile_origin(
        self, _name: str, redirect_target: str, stays_on_site: bool, fetch_public_url: MagicMock
    ) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url == "https://example.com/sitemap.xml":
                return _response(status=301, location=redirect_target)
            if url == redirect_target:
                return _response(body=b"<urlset />")
            return _response(status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        self.assertEqual(result["sitemap_detected"], stays_on_site)
        self.assertEqual(result["source_urls"], ["https://example.com/sitemap.xml"])
        self.assertEqual(result["domain"], "https://example.com")

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_caps_the_requests_one_discovery_sends(self, fetch_public_url: MagicMock) -> None:
        fetch_public_url.side_effect = lambda url, **kwargs: _response(status=302, location="/redirect")

        result = discover_site("https://example.com")

        self.assertEqual(fetch_public_url.call_count, _MAX_DISCOVERY_REQUESTS)
        self.assertFalse(result["sitemap_detected"])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_invalid_xml_uses_an_editable_sitemap_fallback(self, fetch_public_url: MagicMock) -> None:
        fetch_public_url.side_effect = lambda url, **kwargs: _response(
            status=404 if url.endswith(("/robots.txt", "/")) else 200,
            body=b"<urlset>" if url.endswith(".xml") else b"",
        )

        result = discover_site("https://example.com")

        self.assertEqual(result["source_urls"], ["https://example.com/sitemap.xml"])
        self.assertEqual(
            result["warnings"],
            ["We couldn't verify a sitemap. Review the suggested URL before saving."],
        )

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_caps_robots_candidates_and_still_probes_conventional_paths(self, fetch_public_url: MagicMock) -> None:
        sitemap_lines = "\n".join(f"Sitemap: https://example.com/sitemap-{index}.xml" for index in range(10))

        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url.endswith("/robots.txt"):
                return _response(body=sitemap_lines.encode())
            if url == "https://example.com/":
                raise PublicUrlFetchError("transport")
            if url == "https://example.com/sitemap.xml":
                return _response(body=b"<urlset />")
            return _response(status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        declared = {f"https://example.com/sitemap-{index}.xml" for index in range(10)}
        declared_calls = [call.args[0] for call in fetch_public_url.call_args_list if call.args[0] in declared]
        self.assertEqual(declared_calls, [f"https://example.com/sitemap-{index}.xml" for index in range(5)])
        self.assertEqual(result["source_urls"], ["https://example.com/sitemap.xml"])
        self.assertTrue(result["sitemap_detected"])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_skips_a_malformed_sitemap_candidate(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url.endswith("/robots.txt"):
                return _response(
                    body=b"Sitemap: https://example.com:invalid/broken.xml\nSitemap: /sitemap.xml",
                )
            if url.endswith("/sitemap.xml"):
                return _response(body=b"<urlset />")
            return _response(status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        self.assertEqual(result["source_urls"], ["https://example.com/sitemap.xml"])
        self.assertTrue(result["sitemap_detected"])
