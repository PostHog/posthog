import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority

from products.error_tracking.backend.presentation.views.git_provider_file_link_resolver import (
    _PUBLIC_TOKEN_CIRCUIT_OPEN_KEY,
    _PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY,
    get_gitlab_file_url,
    search_github_file,
)


def _response(status: int, body: dict | None = None, raw: bytes | None = None) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict({})
    response._content = raw if raw is not None else json.dumps(body or {}).encode()
    return response


@override_settings(GITHUB_TOKEN="public-pat")
class TestGitProviderFileLinksResolveGithub(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.delete(_PUBLIC_TOKEN_CIRCUIT_OPEN_KEY)
        cache.delete(_PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY)
        self.addCleanup(cache.delete, _PUBLIC_TOKEN_CIRCUIT_OPEN_KEY)
        self.addCleanup(cache.delete, _PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY)

    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/error_tracking/git-provider-file-links/resolve_github/"

    def _query(self) -> dict[str, str]:
        return {"owner": "o", "repository": "r", "code_sample": "print(1)", "file_name": "main.py"}

    def test_three_unauthorized_trip_circuit_and_skip_public_token(self) -> None:
        # A dead public PAT must stop being called after 3 consecutive 401s, or it spams GitHub with
        # unauthorized requests forever (the prod symptom this fix targets).
        with patch(
            "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.github_request",
            return_value=_response(401),
        ) as gh:
            for _ in range(3):
                self.client.get(self._url(), self._query())
            assert gh.call_count == 3  # no integration configured, so one call per request

            gh.reset_mock()
            response = self.client.get(self._url(), self._query())

        assert response.json() == {"found": False}
        gh.assert_not_called()  # circuit open -> public token path skipped entirely

    def test_success_resets_unauthorized_count(self) -> None:
        # Two 401s then a 2xx must clear the counter, so intermittent auth blips never trip the breaker.
        with patch(
            "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.github_request"
        ) as gh:
            gh.side_effect = [_response(401), _response(401), _response(200, {"items": []})]
            for _ in range(3):
                self.client.get(self._url(), self._query())

        assert cache.get(_PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY) is None
        assert cache.get(_PUBLIC_TOKEN_CIRCUIT_OPEN_KEY) is None

    def test_budget_exhausted_on_integration_path_degrades_to_not_found(self) -> None:
        # The integration path (installation set, sheddable NORMAL lane) is the one place the
        # limiter can shed a search — removing the except clause would 500 the endpoint instead
        # of degrading to not-found.
        with patch(
            "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.github_request",
            side_effect=GitHubEgressBudgetExhausted("shed"),
        ):
            outcome = search_github_file(
                code_sample="print(1)",
                token="tok",
                owner="o",
                repository="r",
                file_name="main.py",
                installation_id="123",
                priority=Priority.NORMAL,
            )

        assert outcome.url is None
        assert outcome.status_code is None

    def test_malformed_success_body_degrades_to_not_found(self) -> None:
        # A 200 with a non-JSON body must not escape as a 500 — parsing lives inside the guard.
        with patch(
            "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.github_request",
            return_value=_response(200, raw=b"not json"),
        ):
            response = self.client.get(self._url(), self._query())

        assert response.status_code == 200
        assert response.json() == {"found": False}


class TestGetGitlabFileUrl(SimpleTestCase):
    @parameterized.expand(
        [
            ("http_scheme", "http://gitlab.example.com"),
            ("internal_host", "https://localhost"),
            ("metadata_ip", "https://169.254.169.254"),
        ]
    )
    def test_rejects_disallowed_host_without_request(self, _name: str, gitlab_url: str) -> None:
        with patch(
            "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.requests.get"
        ) as get:
            url = get_gitlab_file_url(
                code_sample="print(1)",
                token="tok",
                owner="o",
                repository="r",
                file_name="main.py",
                gitlab_url=gitlab_url,
            )

        assert url is None
        get.assert_not_called()

    def test_does_not_follow_redirects(self) -> None:
        redirect = _response(302)
        redirect.headers = CaseInsensitiveDict({"Location": "https://other.example.com/"})
        with (
            patch("posthog.models.integration.gitlab.is_url_allowed", return_value=(True, None)),
            patch(
                "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.requests.get",
                return_value=redirect,
            ) as get,
        ):
            url = get_gitlab_file_url(
                code_sample="print(1)",
                token="tok",
                owner="o",
                repository="r",
                file_name="main.py",
                gitlab_url="https://gitlab.example.com",
            )

        assert url is None
        assert get.call_count == 2
        for call in get.call_args_list:
            assert call.kwargs["allow_redirects"] is False
