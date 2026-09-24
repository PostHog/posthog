from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.utils import PotentialSecurityProblemException, absolute_uri

from products.exports.backend.tasks.csv_exporter import make_api_call


class TestCSVExporterURLSanitization(SimpleTestCase):
    def test_sanitize_url_when_provided_path(self) -> None:
        with self.settings(SITE_URL="https://something.posthog.com"):
            sanitised = absolute_uri(None or "/some/location")
            assert sanitised == "https://something.posthog.com/some/location"

    def test_sanitize_url_when_provided_path_and_site_url_has_a_port(self) -> None:
        with self.settings(SITE_URL="https://localhost:8000"):
            sanitised = absolute_uri(None or "/some/location")
            assert sanitised == "https://localhost:8000/some/location"

    error_test_cases = [
        ("tab before authority", "https://localhost:8000", "\t//example.com/export"),
        ("newline before authority", "https://localhost:8000", "\n//example.com/export"),
        ("space before authority", "https://localhost:8000", " //example.com/export"),
        ("null before authority", "https://localhost:8000", "\x00//example.com/export"),
        ("control in authority", "https://localhost:8000", "https://local\thost:8000/export"),
        (
            "changing scheme",
            "https://localhost:8000",
            "http://localhost:8000/some/location",
        ),
        (
            "changing port",
            "https://localhost:8000",
            "https://localhost:8123/some/location",
        ),
        (
            "changing port and url",
            "https://something.posthog.com:8000",
            "https://localhost:8123/some/location",
        ),
        (
            "changing domain",
            "https://app.posthog.com",
            "https://google.com/some/location",
        ),
    ]

    @parameterized.expand(error_test_cases)
    def test_sanitise_url_error_cases_as_paths(self, _name: str, site_url: str, provided_url_or_path: str) -> None:
        with self.settings(SITE_URL=site_url), self.assertRaises(PotentialSecurityProblemException):
            absolute_uri(None or provided_url_or_path)

    @parameterized.expand(error_test_cases)
    def test_sanitise_url_error_cases_as_next_url(self, _name: str, site_url: str, provided_url_or_path: str) -> None:
        with self.settings(SITE_URL=site_url), self.assertRaises(PotentialSecurityProblemException):
            absolute_uri(provided_url_or_path or None)

    def test_export_request_does_not_follow_redirect(self) -> None:
        with (
            self.settings(SITE_URL="https://example.com"),
            patch("products.exports.backend.tasks.csv_exporter.requests.request") as request,
        ):
            request.return_value = Mock(status_code=302)
            response = make_api_call("token", None, 100, "GET", None, "/api/projects/1/insights/")

        assert response.status_code == 302
        assert request.call_args.kwargs["allow_redirects"] is False
