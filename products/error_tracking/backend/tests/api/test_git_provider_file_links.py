import json
from datetime import timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils.timezone import now

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import Integration

from products.error_tracking.backend.models import ErrorTrackingRelease
from products.error_tracking.backend.presentation.views.git_provider_file_link_resolver import (
    _PUBLIC_TOKEN_CIRCUIT_OPEN_KEY,
    _PUBLIC_TOKEN_UNAUTHORIZED_COUNT_KEY,
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


COMMIT = "0123456789abcdef0123456789abcdef01234567"
FILE_TEXT = "import os\n\n\ndef one() -> None:\n    two()\n"


class TestFrameSourceFile(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        Integration.objects.create(team=self.team, kind="github", integration_id="1234", config={})
        self.release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="shop-1",
            version="1.0.0",
            project="shop",
            metadata={"git": {"remote_url": "https://github.com/acme/shop.git", "commit_id": COMMIT}},
        )

    def _event(self, frame: dict, release_id: str | None = None) -> tuple[str, str]:
        event_uuid = str(uuid4())
        timestamp = now() - timedelta(hours=1)
        _create_event(
            event_uuid=event_uuid,
            distinct_id="user-1",
            event="$exception",
            team=self.team,
            timestamp=timestamp,
            properties={
                "$exception_release": {"id": release_id or str(self.release.id), "version": "1.0.0"},
                "$exception_list": [
                    {"type": "ValueError", "value": "boom", "stacktrace": {"type": "resolved", "frames": [frame]}}
                ],
            },
        )
        flush_persons_and_events()
        return event_uuid, timestamp.isoformat()

    def _get(self, event_uuid: str, timestamp: str, raw_id: str = "frame-1/0"):
        return self.client.get(
            f"/api/projects/{self.team.id}/error_tracking/git-provider-file-links/source_file/",
            {"event_uuid": event_uuid, "event_timestamp": timestamp, "frame_raw_id": raw_id},
        )

    @patch("posthog.models.integration.github.GitHubIntegration.get_file_entry")
    @patch("posthog.models.integration.github.GitHubIntegration.installation_can_access_repository", return_value=True)
    def test_reads_the_frame_file_at_the_release_commit_once(self, _can_access, get_file_entry) -> None:
        get_file_entry.return_value = {"sha": "blob", "size": len(FILE_TEXT), "content": FILE_TEXT}
        event_uuid, timestamp = self._event(
            {"raw_id": "frame-1/0", "line": 5, "in_app": True, "repo_path": "services/api/app/one.py"}
        )

        first = self._get(event_uuid, timestamp)
        second = self._get(event_uuid, timestamp)

        assert first.status_code == 200, first.json()
        assert first.json() == {
            "repo_path": "services/api/app/one.py",
            "commit": COMMIT,
            "line": 5,
            "lines": ["import os", "", "", "def one() -> None:", "    two()"],
        }
        assert second.json() == first.json()
        get_file_entry.assert_called_once_with("acme/shop", "services/api/app/one.py", ref=COMMIT)

    @parameterized.expand(
        [
            ("frame_without_repo_path", {"raw_id": "frame-1/0", "line": 5, "in_app": True}, None, "frame-1/0"),
            ("frame_not_in_event", {"raw_id": "frame-1/0", "repo_path": "a/b.py"}, None, "other/0"),
            ("release_of_another_team", {"raw_id": "frame-1/0", "repo_path": "a/b.py"}, str(uuid4()), "frame-1/0"),
        ]
    )
    @patch("posthog.models.integration.github.GitHubIntegration.get_file_entry")
    def test_reads_nothing_the_stored_frame_does_not_name(
        self, _name: str, frame: dict, release_id: str | None, raw_id: str, get_file_entry
    ) -> None:
        event_uuid, timestamp = self._event(frame, release_id)

        response = self._get(event_uuid, timestamp, raw_id)

        assert response.status_code == 404
        get_file_entry.assert_not_called()
