from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.web_analytics.backend.content_autopilot.site_discovery import discover_site, normalize_site_origin
from products.web_analytics.backend.public_url_fetch import FetchedPublicUrl, PublicUrlFetchError


def _response(url: str, *, status: int = 200, body: bytes = b"", location: str | None = None) -> FetchedPublicUrl:
    headers = {"Location": location} if location else {}
    return FetchedPublicUrl(url=url, status_code=status, headers=headers, body=body)


class TestContentAutopilotSiteDiscovery(SimpleTestCase):
    @parameterized.expand(
        [
            ("lowercase_host", "HTTPS://Example.COM/guides?q=1#top", "https://example.com"),
            ("default_port", "https://example.com:443/path", "https://example.com"),
            ("custom_port", "http://example.com:8080/path", "http://example.com:8080"),
        ]
    )
    def test_normalizes_site_origin(self, _name: str, raw_url: str, expected: str) -> None:
        self.assertEqual(normalize_site_origin(raw_url), expected)

    @parameterized.expand(
        [
            ("unsupported_scheme", "ftp://example.com"),
            ("missing_host", "https:///guides"),
            ("credentials", "https://token@example.com"),
            ("invalid_port", "https://example.com:not-a-port"),
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
                    url,
                    body=b"User-agent: *\nSitemap: https://example.com/content-sitemap.xml",
                )
            if url == "https://example.com/":
                return _response(url, body=b"<html><head><title>Example Docs | Guides</title></head></html>")
            if url.endswith("/content-sitemap.xml"):
                return _response(url, body=b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" />')
            return _response(url, status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("HTTPS://Example.com/docs")

        self.assertEqual(result["name"], "Example Docs")
        self.assertEqual(result["domain"], "https://example.com")
        self.assertEqual(result["source_urls"], ["https://example.com/content-sitemap.xml"])
        self.assertTrue(result["sitemap_detected"])
        self.assertEqual(result["warnings"], [])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_revalidates_a_same_origin_redirect(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url.endswith("/robots.txt"):
                return _response(url, status=404)
            if url == "https://example.com/":
                return _response(url, status=302, location="https://example.com:443/welcome")
            if url.endswith("/welcome"):
                return _response(url, body=b'<link rel="sitemap" href="/pages.xml">')
            if url.endswith("/pages.xml"):
                return _response(url, body=b"<urlset />")
            return _response(url, status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        self.assertTrue(result["sitemap_detected"])
        self.assertIn("https://example.com:443/welcome", [call.args[0] for call in fetch_public_url.call_args_list])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_never_fetches_a_cross_origin_redirect(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url == "https://example.com/":
                return _response(url, status=302, location="https://other.example/sitemap.xml")
            return _response(url, status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        self.assertFalse(result["sitemap_detected"])
        self.assertNotIn("other.example", " ".join(call.args[0] for call in fetch_public_url.call_args_list))

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_invalid_xml_uses_an_editable_sitemap_fallback(self, fetch_public_url: MagicMock) -> None:
        fetch_public_url.side_effect = lambda url, **kwargs: _response(
            url,
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
    def test_limits_sitemap_candidates_from_robots(self, fetch_public_url: MagicMock) -> None:
        sitemap_lines = "\n".join(f"Sitemap: https://example.com/sitemap-{index}.xml" for index in range(10))

        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url.endswith("/robots.txt"):
                return _response(url, body=sitemap_lines.encode())
            if url == "https://example.com/":
                raise PublicUrlFetchError("transport")
            return _response(url, status=404)

        fetch_public_url.side_effect = response_for

        discover_site("https://example.com")

        sitemap_calls = [call.args[0] for call in fetch_public_url.call_args_list if "/sitemap-" in call.args[0]]
        self.assertEqual(sitemap_calls, [f"https://example.com/sitemap-{index}.xml" for index in range(5)])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_skips_a_malformed_sitemap_candidate(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url.endswith("/robots.txt"):
                return _response(
                    url,
                    body=b"Sitemap: https://example.com:invalid/broken.xml\nSitemap: /sitemap.xml",
                )
            if url.endswith("/sitemap.xml"):
                return _response(url, body=b"<urlset />")
            return _response(url, status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        self.assertEqual(result["source_urls"], ["https://example.com/sitemap.xml"])
        self.assertTrue(result["sitemap_detected"])

    @patch("products.web_analytics.backend.content_autopilot.site_discovery.fetch_public_url")
    def test_skips_a_malformed_homepage_sitemap_candidate(self, fetch_public_url: MagicMock) -> None:
        def response_for(url: str, **kwargs: object) -> FetchedPublicUrl:
            if url == "https://example.com/":
                return _response(url, body=b'<link rel="sitemap" href="https://example.com:invalid/broken.xml">')
            if url.endswith("/sitemap.xml"):
                return _response(url, body=b"<urlset />")
            return _response(url, status=404)

        fetch_public_url.side_effect = response_for

        result = discover_site("https://example.com")

        self.assertEqual(result["source_urls"], ["https://example.com/sitemap.xml"])
        self.assertTrue(result["sitemap_detected"])
