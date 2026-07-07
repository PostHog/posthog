from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import requests
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.transport import GitHubEgressBudgetExhausted

from products.error_tracking.backend.presentation.views.git_provider_file_link_resolver import (
    _PUBLIC_TOKEN_CIRCUIT_OPEN_KEY,
    _PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY,
)


def _response(status: int, body: dict | None = None) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict({})
    response._content = requests.compat.json.dumps(body or {}).encode()
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

    def test_budget_exhausted_on_public_path_degrades_to_not_found(self) -> None:
        # A shed (sheddable) call must degrade to found:false, never surface as a 500.
        with patch(
            "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.github_request",
            side_effect=GitHubEgressBudgetExhausted("shed"),
        ):
            response = self.client.get(self._url(), self._query())

        assert response.status_code == 200
        assert response.json() == {"found": False}
