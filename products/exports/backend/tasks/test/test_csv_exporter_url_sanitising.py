import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

import responses
from parameterized import parameterized

from posthog.utils import PotentialSecurityProblemException, absolute_uri

from products.exports.backend.tasks.csv_exporter import is_allowed_export_url, make_api_call


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


class TestExportURLAllowlist(SimpleTestCase):
    @parameterized.expand(
        [
            ("environment_persons", "https://app.posthog.com/api/environments/2/persons?limit=100", True),
            ("project_by_team_id", "https://app.posthog.com/api/projects/2/advanced_activity_logs/?page=2", True),
            ("project_by_project_id", "https://app.posthog.com/api/projects/7/llm_analytics/trace_reviews/", True),
            ("cohort_persons", "https://app.posthog.com/api/cohort/5/persons?offset=100", True),
            ("cohort_persons_trailing_slash", "https://app.posthog.com/api/cohort/5/persons/", True),
            ("mixed_case_host", "https://App.PostHog.com/api/environments/2/persons", True),
            ("environment_by_project_id", "https://app.posthog.com/api/environments/7/persons", False),
            ("non_ascii_digit", "https://app.posthog.com/api/environments/\u0662/persons", False),
            ("other_team", "https://app.posthog.com/api/environments/3/persons", False),
            ("other_project", "https://app.posthog.com/api/projects/8/insights/", False),
            ("unlisted_api_route", "https://app.posthog.com/api/users/@me/", False),
            ("non_api_path", "https://app.posthog.com/admin/", False),
            ("other_cohort_route", "https://app.posthog.com/api/cohort/5/", False),
            ("other_host", "https://other.example/api/environments/2/persons", False),
            ("other_scheme", "http://app.posthog.com/api/environments/2/persons", False),
            ("dot_segments", "https://app.posthog.com/api/environments/2/../../users/@me/", False),
            ("encoded_dot_segments", "https://app.posthog.com/api/environments/2/%2e%2e/%2e%2e/users/", False),
        ]
    )
    def test_is_allowed_export_url(self, _name: str, url: str, expected: bool) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            assert is_allowed_export_url(url, team_id=2, project_id=7) is expected

    @patch("products.exports.backend.tasks.csv_exporter.requests.request")
    def test_make_api_call_outside_allowlist(self, patched_request: MagicMock) -> None:
        with self.settings(SITE_URL="https://app.posthog.com"):
            with pytest.raises(ValueError, match="no longer supported"):
                make_api_call("token", None, 100, "GET", None, "/api/users/@me/", team_id=2, project_id=7)

        assert not patched_request.called

    @responses.activate
    def test_make_api_call_refuses_redirect_off_allowlisted_path(self) -> None:
        allowed_url = "https://app.posthog.com/api/environments/2/persons"
        responses.get(allowed_url, status=302, headers={"Location": "https://attacker.example/x"})
        attacker = responses.get("https://attacker.example/x", json={"results": [{"secret": 1}]})

        with self.settings(SITE_URL="https://app.posthog.com"):
            with pytest.raises(ValueError, match="no longer supported"):
                make_api_call("token", None, 100, "GET", None, "/api/environments/2/persons", team_id=2, project_id=7)

        assert attacker.call_count == 0

    @parameterized.expand(
        [
            ("under_site_path", "https://example.com/posthog/api/environments/2/persons", True),
            ("outside_site_path", "https://example.com/api/environments/2/persons", False),
            ("sibling_of_site_path", "https://example.com/posthog-other/api/environments/2/persons", False),
        ]
    )
    def test_is_allowed_export_url_with_site_path(self, _name: str, url: str, expected: bool) -> None:
        with self.settings(SITE_URL="https://example.com/posthog"):
            assert is_allowed_export_url(url, team_id=2, project_id=7) is expected
