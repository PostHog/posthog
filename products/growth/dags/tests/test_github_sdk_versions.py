import json
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from products.growth.dags.github_sdk_versions import (
    LOCAL_RELEASES_CACHE_TTL_SECONDS,
    fetch_android_sdk_data,
    fetch_dotnet_sdk_data,
    fetch_elixir_sdk_data,
    fetch_flutter_sdk_data,
    fetch_go_sdk_data,
    fetch_ios_sdk_data,
    fetch_java_sdk_data,
    fetch_java_server_sdk_data,
    fetch_kmp_sdk_data,
    fetch_node_sdk_data,
    fetch_php_sdk_data,
    fetch_python_sdk_data,
    fetch_react_native_sdk_data,
    fetch_releases_from_repo,
    fetch_ruby_sdk_data,
    fetch_web_sdk_data,
    local_releases_cache,
)

# NOTE: Fixtures are defined as they were in October 10, 2025
# They can be updated by running the following Python Script:
#
# ```python
# import requests
# from pathlib import Path
#
# FIXTURES = Path(__file__).parent / "fixtures"
# RELEASES = FIXTURES / "releases"
#
# releases = {
#     "posthog_js_releases.json": "https://api.github.com/repos/PostHog/posthog-js/releases?per_page=25",
#     "posthog_js_lite_releases.json": "https://api.github.com/repos/PostHog/posthog-js-lite/releases?per_page=25",
#     "posthog_python_releases.json": "https://api.github.com/repos/PostHog/posthog-python/releases?per_page=10",
#     "posthog_flutter_releases.json": "https://api.github.com/repos/PostHog/posthog-flutter/releases?per_page=10",
#     "posthog_ios_releases.json": "https://api.github.com/repos/PostHog/posthog-ios/releases?per_page=10",
#     "posthog_android_releases.json": "https://api.github.com/repos/PostHog/posthog-android/releases?per_page=10",
#     "posthog_go_releases.json": "https://api.github.com/repos/PostHog/posthog-go/releases?per_page=10",
#     "posthog_dotnet_releases.json": "https://api.github.com/repos/PostHog/posthog-dotnet/releases?per_page=10",
#     "posthog_elixir_releases.json": "https://api.github.com/repos/PostHog/posthog-elixir/releases?per_page=10",
#     "posthog_ruby_releases.json": "https://api.github.com/repos/PostHog/posthog-ruby/releases?per_page=10",
#     "posthog_php_releases.json": "https://api.github.com/repos/PostHog/posthog-php/releases?per_page=10",
# }
#
#
# for filename, url in releases.items():
#     print(f"Downloading {filename}...")
#     r = requests.get(url)
#     (RELEASES / filename).write_text(r.text)
# ```

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RELEASES_DIR = FIXTURES_DIR / "releases"


class TestFetchSdkDataBase:
    def load_releases(self, filename: str) -> dict:
        """Load a releases JSON file from the releases directory."""
        with open(RELEASES_DIR / filename) as f:
            return json.load(f)

    def setup_ok_json_mock(self, mock_get, data):
        page1 = MagicMock()
        page1.ok = True
        page1.status_code = 200
        page1.json.return_value = data

        page2 = MagicMock()
        page2.ok = True
        page2.status_code = 200
        page2.json.return_value = []

        mock_get.side_effect = [page1, page2]

    def setup_ok_text_mock(self, mock_get, data):
        page1 = MagicMock()
        page1.ok = True
        page1.status_code = 200
        page1.text = data

        page2 = MagicMock()
        page2.ok = True
        page2.status_code = 200
        page2.text = ""

        mock_get.side_effect = [page1, page2]


class TestFetchWebSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_web_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_js_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_web_sdk_data()

        assert result["latestVersion"] == "1.298.1"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "1.298.1" in result["releaseDates"]
        assert result["releaseDates"]["1.298.1"] == "2025-11-26T13:26:47Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate

    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_web_sdk_data_request_failure(self, mock_get):
        response = MagicMock()
        response.ok = False
        response.status_code = 404
        mock_get.side_effect = [response]

        result = fetch_web_sdk_data()

        assert result == {}
        assert mock_get.call_count == 1


class TestFetchPythonSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_python_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_python_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_python_sdk_data()

        assert result["latestVersion"] == "7.0.1"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "7.0.1" in result["releaseDates"]
        assert result["releaseDates"]["7.0.1"] == "2025-11-15T12:43:55Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchNodeSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_node_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_js_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_node_sdk_data()

        assert result["latestVersion"] == "5.14.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "5.14.0" in result["releaseDates"]
        assert result["releaseDates"]["5.14.0"] == "2025-11-24T10:24:59Z"
        assert mock_get.call_count == 3  # Assert that it attempted to paginate + 1 for `posthog-js-lite`

        # `posthog-js-lite` included a leading `v` prefix on some tags, let's make sure it's removed
        assert not any(version.startswith("v") for version in result["releaseDates"].keys())


class TestFetchReactNativeSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_react_native_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_js_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_react_native_sdk_data()

        assert result["latestVersion"] == "4.14.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "4.14.0" in result["releaseDates"]
        assert result["releaseDates"]["4.14.0"] == "2025-11-26T13:26:49Z"
        assert mock_get.call_count == 3  # Assert that it attempted to paginate + 1 for `posthog-js-lite`

        # `posthog-js-lite` included a leading `v` prefix on some tags, let's make sure it's removed
        assert not any(version.startswith("v") for version in result["releaseDates"].keys())


class TestFetchFlutterSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_flutter_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_flutter_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_flutter_sdk_data()

        assert result["latestVersion"] == "5.9.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "5.9.0" in result["releaseDates"]
        assert result["releaseDates"]["5.9.0"] == "2025-11-05T13:22:41Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate

        # `flutter` included a leading `v` prefix on some tags, let's make sure it's removed
        assert not any(version.startswith("v") for version in result["releaseDates"].keys())


class TestFetchKmpSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_kmp_sdk_data_success(self, mock_get: MagicMock) -> None:
        self.setup_ok_json_mock(
            mock_get,
            [
                {
                    "tag_name": "v0.0.1",
                    "created_at": "2026-07-14T18:03:29Z",
                    "draft": False,
                    "prerelease": False,
                }
            ],
        )

        result = fetch_kmp_sdk_data()

        assert result == {
            "latestVersion": "0.0.1",
            "releaseDates": {"0.0.1": "2026-07-14T18:03:29Z"},
        }
        assert "/repos/PostHog/posthog-kmp/releases" in mock_get.call_args_list[0].args[1]


class TestFetchIosSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_ios_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_ios_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_ios_sdk_data()

        assert result["latestVersion"] == "3.35.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.35.0" in result["releaseDates"]
        assert result["releaseDates"]["3.35.0"] == "2025-11-07T16:22:45Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchAndroidSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_android_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_android_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_android_sdk_data()

        assert result["latestVersion"] == "3.26.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.26.0" in result["releaseDates"]
        assert result["releaseDates"]["3.26.0"] == "2025-11-05T20:29:02Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchJavaSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetches_releases_from_archived_java_repo(self, mock_get):
        self.setup_ok_json_mock(
            mock_get,
            [
                {
                    "tag_name": "1.2.0",
                    "created_at": "2025-01-29T20:23:43Z",
                    "draft": False,
                    "prerelease": False,
                },
                {
                    "tag_name": "1.1.0",
                    "created_at": "2023-03-17T15:33:22Z",
                    "draft": False,
                    "prerelease": False,
                },
            ],
        )

        result = fetch_java_sdk_data()

        assert result["latestVersion"] == "1.2.0"
        assert result["releaseDates"]["1.1.0"] == "2023-03-17T15:33:22Z"
        assert "/repos/PostHog/posthog-java/releases" in mock_get.call_args_list[0].args[1]


class TestFetchJavaServerSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetches_only_server_releases_from_android_monorepo(self, mock_get):
        releases_data = self.load_releases("posthog_android_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_java_server_sdk_data()

        assert result["latestVersion"] == "2.0.1"
        assert result["releaseDates"] == {
            "2.0.1": "2025-11-25T17:55:17Z",
            "2.0.0": "2025-11-06T20:11:49Z",
        }


class TestFetchGoSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_go_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_go_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_go_sdk_data()

        assert result["latestVersion"] == "1.6.13"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "1.6.13" in result["releaseDates"]
        assert result["releaseDates"]["1.6.13"] == "2025-11-21T21:58:29Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchPhpSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_php_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_php_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_php_sdk_data()

        assert result["latestVersion"] == "3.7.2"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.7.2" in result["releaseDates"]
        assert result["releaseDates"]["3.7.2"] == "2025-10-23T00:40:34Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchRubySdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_ruby_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_ruby_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_ruby_sdk_data()

        assert result["latestVersion"] == "3.3.3"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "3.3.3" in result["releaseDates"]
        assert result["releaseDates"]["3.3.3"] == "2025-10-22T17:40:15Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchElixirSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_elixir_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_elixir_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_elixir_sdk_data()

        assert result["latestVersion"] == "2.1.0"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "2.1.0" in result["releaseDates"]
        assert result["releaseDates"]["2.1.0"] == "2025-11-25T18:54:57Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


class TestFetchDotnetSdkData(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_fetch_dotnet_sdk_data_success(self, mock_get):
        releases_data = self.load_releases("posthog_dotnet_releases.json")
        self.setup_ok_json_mock(mock_get, releases_data)

        result = fetch_dotnet_sdk_data()

        assert result["latestVersion"] == "2.2.2"
        assert "releaseDates" in result
        assert len(result["releaseDates"]) > 0
        assert "2.2.2" in result["releaseDates"]
        assert result["releaseDates"]["2.2.2"] == "2025-11-21T17:27:02Z"
        assert mock_get.call_count == 2  # Assert that it attempted to paginate


def _release(tag_name: str, created_at: str) -> dict:
    return {"tag_name": tag_name, "created_at": created_at, "draft": False, "prerelease": False}


class TestMonorepoPackageTagMatching(TestFetchSdkDataBase):
    @pytest.mark.parametrize(
        "fetch_fn,releases,expected_latest,expected_date_keys",
        [
            # posthog-python moved to `posthog-v*` tags; sibling package tags must not match
            (
                fetch_python_sdk_data,
                [
                    _release("openfeature-provider-posthog-v0.1.39", "2026-08-01T00:00:00Z"),
                    _release("posthog-v7.38.0", "2026-07-30T00:00:00Z"),
                    _release("v7.12.0", "2025-08-30T00:00:00Z"),
                    _release("7.5.0", "2025-05-30T00:00:00Z"),
                ],
                "7.38.0",
                {"7.38.0", "7.12.0", "7.5.0"},
            ),
            # posthog-ruby moved to `posthog-ruby-v*` tags; `posthog-rails-v*` is a different package
            (
                fetch_ruby_sdk_data,
                [
                    _release("posthog-rails-v3.18.0", "2026-08-01T00:00:00Z"),
                    _release("posthog-ruby-v3.23.0", "2026-07-30T00:00:00Z"),
                    _release("v3.6.1", "2025-08-30T00:00:00Z"),
                    _release("3.3.3", "2025-05-30T00:00:00Z"),
                ],
                "3.23.0",
                {"3.23.0", "3.6.1", "3.3.3"},
            ),
            # posthog-dotnet moved to `PostHog-v*` tags; AspNetCore/AI package tags must not match
            (
                fetch_dotnet_sdk_data,
                [
                    _release("PostHog.AspNetCore-v2.8.2", "2026-08-01T00:00:00Z"),
                    _release("PostHog.AI-v0.1.4", "2026-07-31T00:00:00Z"),
                    _release("PostHog-v2.13.0", "2026-07-30T00:00:00Z"),
                    _release("2.6.0", "2025-09-30T00:00:00Z"),
                    _release("v2.4.1", "2025-08-30T00:00:00Z"),
                ],
                "2.13.0",
                {"2.13.0", "2.6.0", "2.4.1"},
            ),
            # posthog-kmp dropped its `v` prefix after 0.1.x
            (
                fetch_kmp_sdk_data,
                [
                    _release("0.2.2", "2026-07-30T00:00:00Z"),
                    _release("v0.1.0", "2026-05-30T00:00:00Z"),
                ],
                "0.2.2",
                {"0.2.2", "0.1.0"},
            ),
        ],
    )
    def test_current_and_historical_tag_schemes(self, fetch_fn, releases, expected_latest, expected_date_keys):
        with patch("posthog.egress.transport.transport.requests.request") as mock_get:
            self.setup_ok_json_mock(mock_get, releases)

            result = fetch_fn()

        assert result["latestVersion"] == expected_latest
        assert set(result["releaseDates"]) == expected_date_keys


class TestLatestVersionSelection(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_backported_hotfix_listed_first_is_not_latest(self, mock_get):
        # GitHub orders /releases by creation date, so a hotfix on an older release line
        # appears before the actual newest version
        self.setup_ok_json_mock(
            mock_get,
            [
                _release("posthog-js@1.200.5", "2026-08-01T00:00:00Z"),
                _release("posthog-js@1.298.1", "2026-07-20T00:00:00Z"),
            ],
        )

        result = fetch_web_sdk_data()

        assert result["latestVersion"] == "1.298.1"

    @patch("posthog.egress.transport.transport.requests.request")
    def test_unparseable_tag_cannot_become_latest(self, mock_get):
        # posthog-ios matches every release tag; a stray non-version tag must not win
        self.setup_ok_json_mock(
            mock_get,
            [
                _release("list", "2026-08-01T00:00:00Z"),
                _release("3.69.2", "2026-07-20T00:00:00Z"),
            ],
        )

        result = fetch_ios_sdk_data()

        assert result["latestVersion"] == "3.69.2"


class TestFetchReleasesFailureHandling(TestFetchSdkDataBase):
    @patch("posthog.egress.transport.transport.requests.request")
    def test_mid_pagination_failure_returns_no_data(self, mock_get):
        # A partial page set can miss versions and produce a wrong "latest"; the fetch must
        # fail closed so the previously cached Redis data keeps serving
        page1 = MagicMock()
        page1.ok = True
        page1.status_code = 200
        page1.json.return_value = [_release("posthog-js@1.298.1", "2026-07-20T00:00:00Z")] * 100

        page2 = MagicMock()
        page2.ok = False
        page2.status_code = 403

        mock_get.side_effect = [page1, page2]

        result = fetch_web_sdk_data()

        assert result == {}

    def test_failed_fetch_is_not_cached(self):
        repo = "PostHog/example-repo"
        local_releases_cache.pop(repo, None)

        fail = MagicMock()
        fail.ok = False
        fail.status_code = 403

        ok_page = MagicMock()
        ok_page.ok = True
        ok_page.status_code = 200
        ok_page.json.return_value = [_release("1.0.0", "2026-07-20T00:00:00Z")]

        empty_page = MagicMock()
        empty_page.ok = True
        empty_page.status_code = 200
        empty_page.json.return_value = []

        with (
            override_settings(TEST=False),
            patch("posthog.egress.transport.transport.requests.request") as mock_get,
        ):
            mock_get.side_effect = [fail, ok_page, empty_page]

            assert fetch_releases_from_repo(repo) == []
            # The failure must not be cached: the next call retries and succeeds
            releases = fetch_releases_from_repo(repo)

        local_releases_cache.pop(repo, None)
        assert len(releases) == 1

    def test_cached_releases_expire(self):
        repo = "PostHog/example-repo-ttl"
        local_releases_cache.pop(repo, None)

        def ok_pages():
            page = MagicMock()
            page.ok = True
            page.status_code = 200
            page.json.return_value = [_release("1.0.0", "2026-07-20T00:00:00Z")]
            empty = MagicMock()
            empty.ok = True
            empty.status_code = 200
            empty.json.return_value = []
            return [page, empty]

        with (
            override_settings(TEST=False),
            patch("posthog.egress.transport.transport.requests.request") as mock_get,
            patch("products.growth.dags.github_sdk_versions.time.monotonic") as mock_time,
        ):
            mock_get.side_effect = ok_pages() + ok_pages()

            mock_time.return_value = 0.0
            fetch_releases_from_repo(repo)
            fetch_releases_from_repo(repo)
            assert mock_get.call_count == 2  # Second call within the TTL is served from cache

            mock_time.return_value = LOCAL_RELEASES_CACHE_TTL_SECONDS + 1.0
            fetch_releases_from_repo(repo)
            assert mock_get.call_count == 4  # Past the TTL the releases are refetched

        local_releases_cache.pop(repo, None)


class TestSupportsUnprefixedReleaseTags(TestFetchSdkDataBase):
    @pytest.mark.parametrize(
        "fetch_fn,latest_tag,previous_tag,previous_version,latest_created_at,previous_created_at",
        [
            (fetch_python_sdk_data, "7.0.2", "v7.0.1", "7.0.1", "2025-11-16T12:43:55Z", "2025-11-15T12:43:55Z"),
            (fetch_go_sdk_data, "1.6.14", "v1.6.13", "1.6.13", "2025-11-22T21:58:29Z", "2025-11-21T21:58:29Z"),
            (fetch_elixir_sdk_data, "2.1.1", "v2.1.0", "2.1.0", "2025-11-26T18:54:57Z", "2025-11-25T18:54:57Z"),
            (fetch_dotnet_sdk_data, "2.2.3", "v2.2.2", "2.2.2", "2025-11-22T17:27:02Z", "2025-11-21T17:27:02Z"),
            (
                fetch_android_sdk_data,
                "3.27.0",
                "android-v3.26.0",
                "3.26.0",
                "2025-11-06T20:29:02Z",
                "2025-11-05T20:29:02Z",
            ),
        ],
    )
    def test_supports_unprefixed_release_tags(
        self, fetch_fn, latest_tag, previous_tag, previous_version, latest_created_at, previous_created_at
    ):
        with patch("posthog.egress.transport.transport.requests.request") as mock_get:
            self.setup_ok_json_mock(
                mock_get,
                [
                    {
                        "tag_name": latest_tag,
                        "draft": False,
                        "prerelease": False,
                        "created_at": latest_created_at,
                    },
                    {
                        "tag_name": previous_tag,
                        "draft": False,
                        "prerelease": False,
                        "created_at": previous_created_at,
                    },
                ],
            )

            result = fetch_fn()

        assert result["latestVersion"] == latest_tag
        assert result["releaseDates"][latest_tag] == latest_created_at
        assert result["releaseDates"][previous_version] == previous_created_at
