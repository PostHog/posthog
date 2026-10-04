from io import BytesIO

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.security.pinned_requests import SSRFBlockedError

from products.web_analytics.backend.heatmap_preflight import (
    PREFLIGHT_MAX_REDIRECTS,
    PreflightResult,
    analyze_framing_headers,
    preflight_page,
)

APP_ORIGIN = "https://us.posthog.com"


@override_settings(SITE_URL=APP_ORIGIN)
class TestFramingHeaderAnalysis(SimpleTestCase):
    @parameterized.expand(
        [
            # Some sites send frame-ancestors 'none' alongside X-Frame-Options: DENY. The CSP is the
            # operative one; reporting this as allowed is the false negative that makes the failure
            # look like ours.
            (
                "csp_frame_ancestors_none_wins_over_xfo",
                {
                    "x-frame-options": "DENY",
                    "content-security-policy": "block-all-mixed-content; frame-ancestors 'none'; upgrade-insecure-requests;",
                },
                "blocked",
                "frame_ancestors",
            ),
            # A host that names the app in frame-ancestors. XFO is still DENY here, but browsers ignore XFO
            # when frame-ancestors is present, so treating XFO as decisive would wrongly warn on a working setup.
            (
                "csp_allowing_app_wins_over_xfo_deny",
                {"x-frame-options": "DENY", "content-security-policy": "frame-ancestors 'self' *.posthog.com"},
                "allowed",
                None,
            ),
            ("xfo_deny", {"x-frame-options": "DENY"}, "blocked", "x_frame_options"),
            ("xfo_sameorigin_is_not_us", {"x-frame-options": "SAMEORIGIN"}, "blocked", "x_frame_options"),
            # No browser we support implements ALLOW-FROM, and browsers ignore values they don't
            # recognize, so an unrecognized value must not produce a warning.
            ("xfo_unrecognized_value_is_ignored", {"x-frame-options": "ALLOWALL"}, "allowed", None),
            ("no_framing_headers", {}, "allowed", None),
            ("csp_wildcard", {"content-security-policy": "frame-ancestors *"}, "allowed", None),
            (
                "csp_exact_origin",
                {"content-security-policy": "frame-ancestors https://us.posthog.com"},
                "allowed",
                None,
            ),
            (
                "csp_scheme_mismatch",
                {"content-security-policy": "frame-ancestors http://us.posthog.com"},
                "blocked",
                "frame_ancestors",
            ),
            (
                "csp_only_other_site",
                {"content-security-policy": "frame-ancestors https://example.com"},
                "blocked",
                "frame_ancestors",
            ),
            (
                "csp_without_frame_ancestors_falls_back_to_xfo",
                {"content-security-policy": "default-src 'self'", "x-frame-options": "DENY"},
                "blocked",
                "x_frame_options",
            ),
            ("header_casing_is_ignored", {"X-Frame-Options": "deny"}, "blocked", "x_frame_options"),
            # Port is part of the origin the browser compares, so a source naming a different one
            # does not permit the app even though the host matches.
            (
                "csp_non_default_port_is_a_different_origin",
                {"content-security-policy": "frame-ancestors https://us.posthog.com:8443"},
                "blocked",
                "frame_ancestors",
            ),
            (
                "csp_spelled_out_default_port",
                {"content-security-policy": "frame-ancestors https://us.posthog.com:443"},
                "allowed",
                None,
            ),
            (
                "csp_wildcard_port",
                {"content-security-policy": "frame-ancestors https://us.posthog.com:*"},
                "allowed",
                None,
            ),
            # A scheme-source permits every origin on that scheme, so reading it as a hostname is
            # the false alarm that tells a customer their site blocks us when it doesn't.
            (
                "csp_scheme_source",
                {"content-security-policy": "frame-ancestors https:"},
                "allowed",
                None,
            ),
            # Several policies each apply on their own, so the strictest decides. requests joins
            # repeated headers with a comma exactly like a multi-policy header value.
            (
                "csp_strictest_of_several_policies_wins",
                {"content-security-policy": "frame-ancestors *, frame-ancestors 'none'"},
                "blocked",
                "frame_ancestors",
            ),
        ]
    )
    def test_framing_verdict(self, _name, headers, expected_framing, expected_blocked_by):
        assert analyze_framing_headers(headers) == (expected_framing, expected_blocked_by)


@override_settings(SITE_URL=APP_ORIGIN)
class TestPreflightPage(SimpleTestCase):
    def setUp(self):
        super().setUp()
        cache_patch = patch("products.web_analytics.backend.heatmap_preflight.cache")
        self.mock_cache = cache_patch.start()
        self.mock_cache.get.return_value = None
        self.addCleanup(cache_patch.stop)

    @staticmethod
    def _response(status_code: int, headers: dict[str, str], body: str = "") -> requests.Response:
        res = requests.Response()
        res.status_code = status_code
        res.headers.update(headers)
        # The body is streamed, so it has to come off `raw` rather than the cached `_content`.
        res.raw = BytesIO(body.encode())
        return res

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_non_2xx_reports_status_not_a_framing_verdict(self, mock_session):
        # The 429 body a customer's edge actually returned. Its headers describe the rate limiter, not
        # the page, so claiming "embedding allowed" here would send the user hunting the wrong problem.
        mock_session.return_value.__enter__.return_value.request.return_value = self._response(
            429, {}, "local_rate_limited"
        )

        result = preflight_page("https://example.com/page")

        assert result.framing == "unknown"
        assert result.http_status == 429
        assert result.body_excerpt == "local_rate_limited"
        self.mock_cache.set.assert_not_called()

    @parameterized.expand(
        [
            ("absolute_location", "https://www.example.com/final", "https://www.example.com/final"),
            ("relative_location", "/final", "https://example.com/final"),
        ]
    )
    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_the_verdict_comes_from_the_page_at_the_end_of_the_chain(self, _name, location, expected_hop, mock_session):
        # http->https, apex->www and trailing-slash redirects are how a healthy public page
        # normally answers. An iframe follows them, so stopping at the 3xx and reporting it would
        # accuse the customer's host of failing when nothing is wrong.
        request = mock_session.return_value.__enter__.return_value.request
        request.side_effect = [
            self._response(301, {"location": location}),
            self._response(200, {"x-frame-options": "DENY"}),
        ]

        result = preflight_page("https://example.com/page")

        assert result == PreflightResult("blocked", "x_frame_options", 200, None)
        # Every hop re-enters pinned_session, which is what validates and pins each target.
        assert [call.args[0] for call in mock_session.call_args_list] == ["https://example.com/page", expected_hop]

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_a_chain_that_never_settles_reports_no_status(self, mock_session):
        request = mock_session.return_value.__enter__.return_value.request
        request.side_effect = lambda *args, **kwargs: self._response(302, {"location": "https://example.com/again"})

        result = preflight_page("https://example.com/page")

        # No status, because the UI reads one as the host's answer about the page and a loop never
        # produced a page.
        assert result == PreflightResult("unknown", None, None, None)
        assert request.call_count == PREFLIGHT_MAX_REDIRECTS + 1

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_a_redirect_into_a_blocked_address_is_not_followed(self, mock_session):
        # The first hop is a public URL that passes validation; the second points inside. Validating
        # per hop is the only thing standing between a caller-supplied URL and an internal address.
        mock_session.return_value.__enter__.return_value.request.return_value = self._response(
            302, {"location": "http://169.254.169.254/latest/meta-data/"}
        )
        mock_session.side_effect = [mock_session.return_value, SSRFBlockedError("Private IP")]

        result = preflight_page("https://example.com/page")

        assert result == PreflightResult("unknown", None, None, None)

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_unreachable_host_is_a_verdict_not_an_exception(self, mock_session):
        mock_session.return_value.__enter__.return_value.request.side_effect = requests.ConnectionError("boom")

        result = preflight_page("https://example.com/page")

        assert result.framing == "unknown"
        assert result.http_status is None

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_a_body_that_never_ends_is_capped(self, mock_session):
        # requests' read timeout bounds the gap between chunks, not the total transfer, so an
        # endless trickle would otherwise grow a web worker without bound.
        def endless_chunks(chunk_size: int = 4096):
            while True:
                yield b"x" * chunk_size

        res = requests.Response()
        res.status_code = 503
        mock_session.return_value.__enter__.return_value.request.return_value = res
        with patch.object(requests.Response, "iter_content", side_effect=endless_chunks):
            result = preflight_page("https://example.com/page")

        assert result.http_status == 503
        assert result.body_excerpt is not None
        assert len(result.body_excerpt) <= 200

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_a_settled_verdict_is_cached_and_not_refetched(self, mock_session):
        request = mock_session.return_value.__enter__.return_value.request
        request.return_value = self._response(200, {"content-security-policy": "frame-ancestors 'none'"})

        first = preflight_page("https://example.com/page")
        assert first.framing == "blocked"
        assert first.blocked_by == "frame_ancestors"

        self.mock_cache.get.return_value = first
        assert preflight_page("https://example.com/page") == first
        request.assert_called_once()

    @patch("products.web_analytics.backend.heatmap_preflight.pinned_session")
    def test_credentials_never_reach_the_outbound_request(self, mock_session):
        # A customer-supplied URL can carry a signed token or basic-auth pair; it must not reach
        # the outbound request or any log line.
        request = mock_session.return_value.__enter__.return_value.request
        request.return_value = self._response(200, {})

        preflight_page("https://user:secret@example.com:8443/page")

        mock_session.assert_called_once_with("https://example.com:8443/page")
        assert request.call_args.args[1] == "https://example.com:8443/page"
