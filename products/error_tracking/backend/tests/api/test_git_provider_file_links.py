import json
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from posthog.models.utils import uuid7

from products.error_tracking.backend.models import ErrorTrackingRelease, ErrorTrackingStackFrame, ErrorTrackingSymbolSet

COMMIT = "0123456789abcdef0123456789abcdef01234567"
TREE = ["packages/web/src/three.ts", "packages/web/src/two.ts", "packages/api/src/three.ts", "README.md"]


def _response(status: int, body: dict | list | None = None) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict({})
    response._content = json.dumps(body if body is not None else {}).encode()
    return response


class _FakeGitHubApi:
    """Answers the two GitHub reads the resolver makes and counts them."""

    def __init__(self, default_branch: str = "main") -> None:
        self.default_branch = default_branch
        self.calls: list[str] = []

    def get(self, path: str, *, endpoint: str, etag: str | None = None) -> requests.Response:
        self.calls.append(path)
        if path.startswith("/repos/acme/app/git/trees/"):
            return _response(200, {"tree": [{"path": p, "type": "blob"} for p in TREE], "truncated": False})
        if path == "/repos/acme/app":
            return _response(200, {"default_branch": self.default_branch})
        return _response(404)


class _SourceLinksTestMixin(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/error_tracking/git-provider-file-links/resolve/"

    def _resolve(self, release_id: str, raw_ids: list[str]) -> dict[str, dict[str, Any]]:
        response = self.client.post(self._url(), {"release_id": release_id, "raw_ids": raw_ids}, format="json")
        assert response.status_code == 200, response.content
        return {link["raw_id"]: link for link in response.json()["results"]}

    def _release(self, git: dict[str, str] | None) -> ErrorTrackingRelease:
        return ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id=str(uuid7()),
            version="1.0.0",
            project="app",
            metadata={"git": git} if git is not None else {},
        )

    def _symbol_set(self) -> ErrorTrackingSymbolSet:
        # Event release mode: the symbol set carries no release, the event does.
        return ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref=str(uuid7()), storage_ptr=f"symbolsets/{uuid7()}", content_hash="h1"
        )

    def _frame(
        self, symbol_set: ErrorTrackingSymbolSet, raw_id: str, source: str, line: int = 3, with_context: bool = True
    ) -> str:
        # Mirrors what cymbal stores for a source map frame: the token line counts from zero, and
        # the context holds the line as the stack trace shows it.
        ErrorTrackingStackFrame.objects.create(
            team=self.team,
            raw_id=raw_id,
            part=0,
            symbol_set=symbol_set,
            resolved=True,
            contents={"source": source, "line": line - 1, "lang": "javascript", "in_app": True, "resolved": True},
            context={"before": [], "line": {"number": line, "line": "run()"}, "after": []} if with_context else None,
        )
        return f"{raw_id}/0"


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "source-links-tests"}}
)
class TestGitProviderFileLinksResolve(_SourceLinksTestMixin):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.api = _FakeGitHubApi()
        for patcher in [
            patch("products.error_tracking.backend.logic.source_links.github_api_for", return_value=self.api),
            patch(
                "products.error_tracking.backend.logic.source_links.symbol_set_sources",
                return_value=["../src/three.ts", "../src/two.ts"],
            ),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_links_frames_to_the_release_commit(self) -> None:
        release = self._release({"remote_url": "git@github.com:acme/app.git", "commit_id": COMMIT})
        symbol_set = self._symbol_set()
        three = self._frame(symbol_set, "frame-three", "../src/three.ts")
        missing = self._frame(symbol_set, "frame-missing", "../src/not-in-repo.ts")

        links = self._resolve(str(release.id), [three, missing])

        assert links == {
            three: {
                "raw_id": three,
                "provider": "github",
                "url": f"https://github.com/acme/app/blob/{COMMIT}/packages/web/src/three.ts#L3",
                "path": "packages/web/src/three.ts",
            }
        }
        assert self.api.calls == [f"/repos/acme/app/git/trees/{COMMIT}?recursive=1"]

    def test_uses_the_default_branch_when_the_release_has_no_commit(self) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app"})
        two = self._frame(self._symbol_set(), "frame-two", "../src/two.ts", line=7)

        links = self._resolve(str(release.id), [two])

        assert links[two]["url"] == "https://github.com/acme/app/blob/main/packages/web/src/two.ts#L7"
        assert self.api.calls == ["/repos/acme/app", "/repos/acme/app/git/trees/main?recursive=1"]

    @parameterized.expand(
        [
            ("with_context", True),
            ("without_context", False),
        ]
    )
    def test_anchors_the_link_at_the_line_the_stack_trace_shows(self, _name: str, with_context: bool) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts", line=5, with_context=with_context)

        assert self._resolve(str(release.id), [three])[three]["url"].endswith("/packages/web/src/three.ts#L5")

    def test_a_second_page_load_makes_no_github_request(self) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts")
        first = self._resolve(str(release.id), [three])

        second = self._resolve(str(release.id), [three])

        assert second == first
        assert len(self.api.calls) == 1

    @parameterized.expand(
        [
            ("unknown_release", False),
            ("release_without_repository", True),
        ]
    )
    def test_a_release_without_a_repository_gives_no_links_and_no_github_request(
        self, _name: str, release_exists: bool
    ) -> None:
        release_id = str(self._release(git=None).id) if release_exists else str(uuid7())
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts")

        assert self._resolve(release_id, [three]) == {}
        assert self.api.calls == []


@override_settings(
    GITHUB_TOKEN="public-pat",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "source-links-public"}},
)
class TestGitProviderFileLinksPublicToken(_SourceLinksTestMixin):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        patcher = patch(
            "products.error_tracking.backend.logic.source_links.GitHubIntegration.first_for_team_repository",
            return_value=None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _request_at_commit(self, index: int) -> Any:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": f"{index:040x}"})
        frame = self._frame(self._symbol_set(), f"frame-{index}", "../src/a.ts")
        return self.client.post(self._url(), {"release_id": str(release.id), "raw_ids": [frame]}, format="json")

    def test_repeated_unauthorized_responses_trip_the_public_token_circuit(self) -> None:
        # A dead shared token must stop being used after three 401s, or every page load keeps
        # spamming GitHub with unauthorized requests.
        with patch(
            "products.error_tracking.backend.logic.source_links.github_request", return_value=_response(401)
        ) as gh:
            for index in range(3):
                assert self._request_at_commit(index).status_code == 200
            assert gh.call_count == 3

            gh.reset_mock()
            response = self._request_at_commit(3)

        assert response.json() == {"results": []}
        gh.assert_not_called()
