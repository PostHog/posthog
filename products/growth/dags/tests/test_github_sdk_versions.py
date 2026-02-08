import json
from pathlib import Path

from unittest.mock import MagicMock, patch

from products.growth.dags.github_sdk_versions import (
    fetch_android_sdk_data,
    fetch_dotnet_sdk_data,
    fetch_elixir_sdk_data,
    fetch_flutter_sdk_data,
    fetch_go_sdk_data,
    fetch_ios_sdk_data,
    fetch_node_sdk_data,
    fetch_php_sdk_data,
    fetch_python_sdk_data,
    fetch_react_native_sdk_data,
    fetch_ruby_sdk_data,
    fetch_web_sdk_data,
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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

    @patch("products.growth.dags.github_sdk_versions.requests.get")
    def test_fetch_web_sdk_data_request_failure(self, mock_get):
        response = MagicMock()
        response.ok = False
        response.status_code = 404
        mock_get.side_effect = [response]

        result = fetch_web_sdk_data()

        assert result == {}
        assert mock_get.call_count == 1


class TestFetchPythonSdkData(TestFetchSdkDataBase):
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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


class TestFetchIosSdkData(TestFetchSdkDataBase):
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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


class TestFetchGoSdkData(TestFetchSdkDataBase):
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
    @patch("products.growth.dags.github_sdk_versions.requests.get")
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
