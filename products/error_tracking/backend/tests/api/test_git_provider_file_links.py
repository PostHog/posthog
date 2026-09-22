import json
from datetime import UTC, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY
from requests.structures import CaseInsensitiveDict

from posthog.models.integration import Integration
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

    identity = "installation:1"

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


def _frames_counted(provider: str, outcome: str) -> float:
    return (
        REGISTRY.get_sample_value("error_tracking_source_link_frames_total", {"provider": provider, "outcome": outcome})
        or 0.0
    )


class _SourceLinksTestMixin(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/error_tracking/git-provider-file-links/resolve/"

    def _resolve(self, release_id: str, raw_ids: list[str]) -> dict[str, dict[str, Any]]:
        response = self.client.post(self._url(), {"release_id": release_id, "raw_ids": raw_ids}, format="json")
        assert response.status_code == 200, response.content
        return {link["raw_id"]: link for link in response.json()["results"]}

    def _release(self, git: dict[str, Any] | None) -> ErrorTrackingRelease:
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
        self,
        symbol_set: ErrorTrackingSymbolSet,
        raw_id: str,
        source: str,
        line: int = 3,
        with_context: bool = True,
        resolved: bool = True,
    ) -> str:
        # Mirrors what cymbal stores: a source map token line counts from zero, an unresolved frame
        # keeps the SDK's one-based line, and the context holds the line as the stack trace shows it.
        ErrorTrackingStackFrame.objects.create(
            team=self.team,
            raw_id=raw_id,
            part=0,
            symbol_set=symbol_set,
            resolved=resolved,
            contents={
                "source": source,
                "line": line - 1 if resolved else line,
                "lang": "javascript",
                "in_app": True,
                "resolved": resolved,
            },
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
        counted_before = {outcome: _frames_counted("github", outcome) for outcome in ("linked", "unlinked")}

        links = self._resolve(str(release.id), [three, missing])

        # The dashboard reads these label values, so a rename or a lost increment breaks it silently.
        assert {outcome: _frames_counted("github", outcome) - before for outcome, before in counted_before.items()} == {
            "linked": 1,
            "unlinked": 1,
        }

        assert links == {
            three: {
                "raw_id": three,
                "provider": "github",
                "url": f"https://github.com/acme/app/blob/{COMMIT}/packages/web/src/three.ts#L3",
                "path": "packages/web/src/three.ts",
            }
        }
        assert self.api.calls == [f"/repos/acme/app/git/trees/{COMMIT}?recursive=1"]

    @parameterized.expand(
        [
            ("no_commit", {}),
            ("commit_not_a_string", {"commit_id": ["0" * 40]}),
            ("commit_not_a_sha", {"commit_id": "v1.0.0"}),
        ]
    )
    def test_uses_the_default_branch_when_the_release_has_no_usable_commit(self, _name: str, git: dict) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", **git})
        two = self._frame(self._symbol_set(), "frame-two", "../src/two.ts", line=7)

        links = self._resolve(str(release.id), [two])

        assert links[two]["url"] == "https://github.com/acme/app/blob/main/packages/web/src/two.ts#L7"
        assert self.api.calls == ["/repos/acme/app", "/repos/acme/app/git/trees/main?recursive=1"]

    @parameterized.expand(
        [
            ("with_context", True, True),
            ("without_context", False, True),
            ("unresolved_without_context", False, False),
        ]
    )
    def test_anchors_the_link_at_the_line_the_stack_trace_shows(
        self, _name: str, with_context: bool, resolved: bool
    ) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(
            self._symbol_set(), "frame-three", "../src/three.ts", line=5, with_context=with_context, resolved=resolved
        )

        assert self._resolve(str(release.id), [three])[three]["url"].endswith("/packages/web/src/three.ts#L5")

    def test_a_second_page_load_makes_no_github_request(self) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts")
        first = self._resolve(str(release.id), [three])

        second = self._resolve(str(release.id), [three])

        assert second == first
        assert len(self.api.calls) == 1

    def test_a_symbol_set_cut_off_by_the_deadline_is_read_again_on_the_next_load(self) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts")
        two = self._frame(self._symbol_set(), "frame-two", "../src/two.ts")
        counted_before = _frames_counted("github", "cut_off")

        with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as traveller:

            def slow_read(_symbol_set: Any) -> list[str]:
                traveller.shift(timedelta(seconds=16))
                return ["../src/three.ts", "../src/two.ts"]

            with patch(
                "products.error_tracking.backend.logic.source_links.symbol_set_sources", side_effect=slow_read
            ) as reads:
                first = self._resolve(str(release.id), [three, two])

            assert reads.call_count == 1
            assert _frames_counted("github", "cut_off") - counted_before == 1
            second = self._resolve(str(release.id), [three, two])

        assert len(first) == 1
        assert set(second) == {three, two}

    @parameterized.expand(
        [
            ("stored_map_read", ["../src/three.ts"], 1),
            ("storage_outage", None, 2),
        ]
    )
    def test_a_mapping_built_during_a_storage_outage_is_not_kept(
        self, _name: str, stored_sources: list[str] | None, expected_reads: int
    ) -> None:
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts")

        with patch(
            "products.error_tracking.backend.logic.source_links.symbol_set_sources",
            side_effect=[stored_sources, ["../src/three.ts"]],
        ) as reads:
            first = self._resolve(str(release.id), [three])
            with time_machine.travel(datetime.now(UTC) + timedelta(minutes=6), tick=False):
                second = self._resolve(str(release.id), [three])

        assert first == second
        assert reads.call_count == expected_reads

    @patch(
        "products.error_tracking.backend.presentation.views.git_provider_file_link_resolver.SourceLinkResolveThrottle.rate",
        new="2/minute",
    )
    @patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True)
    def test_a_browser_session_is_throttled_per_team(self, _enabled: Any) -> None:
        # The default throttles skip session users, and a miss here costs live provider requests.
        release = self._release({"remote_url": "https://github.com/acme/app", "commit_id": COMMIT})
        three = self._frame(self._symbol_set(), "frame-three", "../src/three.ts")
        body = {"release_id": str(release.id), "raw_ids": [three]}

        statuses = [self.client.post(self._url(), body, format="json").status_code for _ in range(3)]

        assert statuses == [200, 200, 429]

    @parameterized.expand(
        [
            ("unknown_release", None),
            ("release_without_git", {}),
            ("remote_url_not_a_string", {"git": {"remote_url": 1}}),
            ("git_not_an_object", {"git": "https://github.com/acme/app"}),
        ]
    )
    def test_a_release_without_a_repository_gives_no_links_and_no_github_request(
        self, _name: str, metadata: dict | None
    ) -> None:
        release_id = str(uuid7())
        if metadata is not None:
            release_id = str(
                ErrorTrackingRelease.objects.create(
                    team=self.team, hash_id=str(uuid7()), version="1.0.0", project="app", metadata=metadata
                ).id
            )
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


class _FakeGitLab:
    """Answers blob searches with one hit per path in ``blobs``, and records each request."""

    def __init__(self, blobs: list[str]) -> None:
        self.blobs = blobs
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.on_request: Any = None

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append((url, kwargs.get("params") or {}, kwargs))
        if self.on_request is not None:
            return self.on_request()
        return _response(200, [{"path": path, "ref": "main"} for path in self.blobs])


@override_settings(
    GITLAB_TOKEN="shared",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "source-links-gitlab"}},
)
class TestGitProviderFileLinksGitLab(_SourceLinksTestMixin):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.gitlab = _FakeGitLab(["src/date-utils.ts", "packages/web/src/utils.ts"])
        for patcher in [
            patch("products.error_tracking.backend.logic.source_links.requests.get", side_effect=self.gitlab.get),
            patch("products.error_tracking.backend.logic.source_links.is_url_allowed", return_value=(True, None)),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.release = self._release({"remote_url": "https://gitlab.com/acme/app.git", "commit_id": COMMIT})

    def _integration(self, hostname: str) -> Integration:
        return Integration.objects.create(
            team=self.team, kind="gitlab", config={"hostname": hostname}, sensitive_config={"access_token": "t"}
        )

    def test_links_the_exact_file_name_at_the_release_commit(self) -> None:
        # A hit whose name merely ends with the frame's file name must not win, and the link must
        # open the commit the release recorded rather than whatever branch the search ran on.
        utils = self._frame(self._symbol_set(), "frame-utils", "../src/utils.ts", line=4)

        links = self._resolve(str(self.release.id), [utils])

        assert links == {
            utils: {
                "raw_id": utils,
                "provider": "gitlab",
                "url": f"https://gitlab.com/acme/app/-/blob/{COMMIT}/packages/web/src/utils.ts#L4",
                "path": "packages/web/src/utils.ts",
            }
        }
        url, params, kwargs = self.gitlab.calls[0]
        assert url == "https://gitlab.com/api/v4/projects/acme%2Fapp/search"
        assert params == {"scope": "blobs", "search": "run()", "ref": COMMIT}
        assert kwargs["allow_redirects"] is False

    def test_only_integrations_on_the_repository_host_receive_the_code_line(self) -> None:
        self._integration("https://gitlab.example.com/")
        self._integration("https://gitlab.com/")
        self.gitlab.blobs = []
        utils = self._frame(self._symbol_set(), "frame-utils", "../src/utils.ts")

        assert self._resolve(str(self.release.id), [utils]) == {}

        hosts = {url.removesuffix("/api/v4/projects/acme%2Fapp/search") for url, _, _ in self.gitlab.calls}
        assert hosts == {"https://gitlab.com"}
        assert {kwargs["headers"]["PRIVATE-TOKEN"] for _, _, kwargs in self.gitlab.calls} == {"shared", "t"}

    def test_vendor_frames_and_repeated_lines_do_not_search_again(self) -> None:
        symbol_set = self._symbol_set()
        app = self._frame(symbol_set, "frame-app", "../src/utils.ts")
        again = self._frame(symbol_set, "frame-again", "../src/utils.ts")
        vendor = self._frame(symbol_set, "frame-vendor", "../node_modules/lib/utils.ts")
        ErrorTrackingStackFrame.objects.filter(raw_id="frame-vendor").update(
            contents={"source": "../node_modules/lib/utils.ts", "line": 2, "lang": "javascript", "in_app": False}
        )

        links = self._resolve(str(self.release.id), [app, again, vendor])

        assert set(links) == {app, again}
        assert len(self.gitlab.calls) == 1

    def test_a_second_page_load_reuses_the_cached_hit(self) -> None:
        utils = self._frame(self._symbol_set(), "frame-utils", "../src/utils.ts")
        first = self._resolve(str(self.release.id), [utils])

        second = self._resolve(str(self.release.id), [utils])

        assert set(first) == {utils}
        assert second == first
        assert len(self.gitlab.calls) == 1

    def test_a_lookup_cut_off_by_the_deadline_is_tried_again_on_the_next_load(self) -> None:
        self._integration("https://gitlab.com")
        utils = self._frame(self._symbol_set(), "frame-utils", "../src/utils.ts")

        with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as traveller:

            def slow_miss() -> requests.Response:
                traveller.shift(timedelta(seconds=16))
                return _response(200, [])

            self.gitlab.on_request = slow_miss
            assert self._resolve(str(self.release.id), [utils]) == {}
            # The shared token's search ran over the deadline, so the integration was not tried.
            assert len(self.gitlab.calls) == 2

            self.gitlab.on_request = None
            assert set(self._resolve(str(self.release.id), [utils])) == {utils}
