from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise import (
    INCREMENTAL_LOOKBACK,
    BitriseResumeConfig,
    _build_after_param,
    _to_unix_timestamp,
    bitrise_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import (
    BITRISE_ENDPOINTS,
    ENDPOINTS,
)

TRACKED_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.bitrise.make_tracked_session"
)


def _response(body: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


class FakeResumableManager:
    def __init__(self, state: BitriseResumeConfig | None = None):
        self._state = state
        self.saved: list[BitriseResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> BitriseResumeConfig | None:
        return self._state

    def save_state(self, data: BitriseResumeConfig) -> None:
        self.saved.append(data)


class TestToUnixTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), 1767323045),
            (datetime(2026, 1, 2, 3, 4, 5), 1767323045),
            (date(2026, 1, 2), 1767312000),
            ("2026-01-02T03:04:05Z", 1767323045),
            ("2026-01-02T03:04:05+00:00", 1767323045),
            (1767323045, 1767323045),
            ("not-a-date", None),
        ],
    )
    def test_conversion(self, value, expected):
        assert _to_unix_timestamp(value) == expected


class TestBuildAfterParam:
    def test_subtracts_lookback_from_watermark(self):
        watermark = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        after = _build_after_param(True, watermark)
        assert after == 1767323045 - int(INCREMENTAL_LOOKBACK.total_seconds())

    @pytest.mark.parametrize(
        "should_use_incremental_field, last_value",
        [
            (False, datetime(2026, 1, 2, tzinfo=UTC)),
            (True, None),
            (True, "garbage"),
        ],
    )
    def test_no_filter_when_not_incremental(self, should_use_incremental_field, last_value):
        assert _build_after_param(should_use_incremental_field, last_value) is None


class TestValidateCredentials:
    @mock.patch(TRACKED_SESSION)
    def test_valid_personal_access_token(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": {}})
        assert validate_credentials("token") is True
        # /me succeeded, no fallback probe needed.
        assert mock_session.return_value.get.call_count == 1

    @mock.patch(TRACKED_SESSION)
    def test_workspace_token_falls_back_to_apps_probe(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"message": "Unauthorized"}, status_code=401),
            _response({"data": []}),
        ]
        assert validate_credentials("workspace-token") is True

    @mock.patch(TRACKED_SESSION)
    def test_invalid_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"message": "Unauthorized"}, status_code=401),
            _response({"message": "Unauthorized"}, status_code=401),
        ]
        assert validate_credentials("bad") is False

    @mock.patch(TRACKED_SESSION)
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRowsApps:
    @mock.patch(TRACKED_SESSION)
    def test_paginates_via_next_anchor_and_saves_state(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {"next": "anchor1"}}),
            _response({"data": [{"slug": "app2"}], "paging": {}}),
        ]
        manager = FakeResumableManager()

        batches = list(get_rows("token", "apps", mock.MagicMock(), manager))

        assert [item["slug"] for batch in batches for item in batch] == ["app1", "app2"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["next"] == ["anchor1"]
        # State saved once, after the first page yielded and only while more pages remain.
        assert [saved.next for saved in manager.saved] == ["anchor1"]

    @mock.patch(TRACKED_SESSION)
    def test_resumes_from_saved_anchor(self, mock_session):
        mock_session.return_value.get.return_value = _response({"data": [{"slug": "app3"}], "paging": {}})
        manager = FakeResumableManager(state=BitriseResumeConfig(next="anchor2"))

        batches = list(get_rows("token", "apps", mock.MagicMock(), manager))

        assert [item["slug"] for batch in batches for item in batch] == ["app3"]
        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert parse_qs(urlparse(first_url).query)["next"] == ["anchor2"]


class TestGetRowsBuilds:
    @mock.patch(TRACKED_SESSION)
    def test_fans_out_over_apps_and_injects_app_slug(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
            _response({"data": [{"slug": "b1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
            _response({"data": [{"slug": "b2", "triggered_at": "2026-01-02T00:00:00Z"}], "paging": {}}),
        ]

        batches = list(get_rows("token", "builds", mock.MagicMock(), FakeResumableManager()))

        flat = [item for batch in batches for item in batch]
        assert [(b["slug"], b["app_slug"]) for b in flat] == [("b1", "app1"), ("b2", "app2")]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urlparse(urls[1]).path == "/v0.1/apps/app1/builds"
        assert urlparse(urls[2]).path == "/v0.1/apps/app2/builds"
        assert parse_qs(urlparse(urls[1]).query)["sort_by"] == ["created_at"]

    @mock.patch(TRACKED_SESSION)
    def test_incremental_passes_after_param(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {}}),
            _response({"data": [], "paging": {}}),
        ]

        list(
            get_rows(
                "token",
                "builds",
                mock.MagicMock(),
                FakeResumableManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

        builds_url = mock_session.return_value.get.call_args_list[1].args[0]
        after = int(parse_qs(urlparse(builds_url).query)["after"][0])
        assert after == int(datetime(2026, 1, 2, tzinfo=UTC).timestamp()) - int(INCREMENTAL_LOOKBACK.total_seconds())

    @mock.patch(TRACKED_SESSION)
    def test_full_refresh_has_no_after_param(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {}}),
            _response({"data": [], "paging": {}}),
        ]

        list(get_rows("token", "builds", mock.MagicMock(), FakeResumableManager()))

        builds_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "after" not in parse_qs(urlparse(builds_url).query)

    @mock.patch(TRACKED_SESSION)
    def test_saves_bookmark_between_apps_and_page_anchor_within_app(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
            _response({"data": [{"slug": "b1"}], "paging": {"next": "page2"}}),
            _response({"data": [{"slug": "b2"}], "paging": {}}),
            _response({"data": [{"slug": "b3"}], "paging": {}}),
        ]
        manager = FakeResumableManager()

        list(get_rows("token", "builds", mock.MagicMock(), manager))

        assert [(s.app_slug, s.next) for s in manager.saved] == [("app1", "page2"), ("app2", None)]

    @mock.patch(TRACKED_SESSION)
    def test_resumes_from_bookmarked_app(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
            _response({"data": [{"slug": "b9"}], "paging": {}}),
        ]
        manager = FakeResumableManager(state=BitriseResumeConfig(app_slug="app2", next="page3"))

        batches = list(get_rows("token", "builds", mock.MagicMock(), manager))

        # app1 is skipped entirely; app2 resumes from its saved page anchor.
        flat = [item for batch in batches for item in batch]
        assert [(b["slug"], b["app_slug"]) for b in flat] == [("b9", "app2")]
        builds_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert urlparse(builds_url).path == "/v0.1/apps/app2/builds"
        assert parse_qs(urlparse(builds_url).query)["next"] == ["page3"]

    @mock.patch(TRACKED_SESSION)
    def test_stale_bookmark_restarts_from_first_app(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {}}),
            _response({"data": [{"slug": "b1"}], "paging": {}}),
        ]
        manager = FakeResumableManager(state=BitriseResumeConfig(app_slug="deleted-app", next="page9"))

        batches = list(get_rows("token", "builds", mock.MagicMock(), manager))

        flat = [item for batch in batches for item in batch]
        assert [b["app_slug"] for b in flat] == ["app1"]
        builds_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "next" not in parse_qs(urlparse(builds_url).query)

    @mock.patch(TRACKED_SESSION)
    def test_deleted_app_404_is_skipped(self, mock_session):
        not_found = _response({"message": "Not Found"}, status_code=404)
        not_found.raise_for_status.side_effect = requests.HTTPError(response=not_found)
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}, {"slug": "app2"}], "paging": {}}),
            not_found,
            _response({"data": [{"slug": "b2"}], "paging": {}}),
        ]

        batches = list(get_rows("token", "builds", mock.MagicMock(), FakeResumableManager()))

        flat = [item for batch in batches for item in batch]
        assert [(b["slug"], b["app_slug"]) for b in flat] == [("b2", "app2")]


class TestGetRowsWorkflows:
    @mock.patch(TRACKED_SESSION)
    def test_maps_workflow_names_to_rows(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {}}),
            _response({"data": ["primary", "deploy"]}),
        ]

        batches = list(get_rows("token", "workflows", mock.MagicMock(), FakeResumableManager()))

        flat = [item for batch in batches for item in batch]
        assert flat == [
            {"app_slug": "app1", "workflow": "primary"},
            {"app_slug": "app1", "workflow": "deploy"},
        ]


class TestGetRowsArtifacts:
    @mock.patch(TRACKED_SESSION)
    def test_fans_out_over_builds_and_injects_parent_identifiers(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {}}),
            _response({"data": [{"slug": "b1", "triggered_at": "2026-01-01T00:00:00Z"}], "paging": {}}),
            _response({"data": [{"slug": "art1", "title": "app.ipa"}], "paging": {}}),
        ]

        batches = list(get_rows("token", "artifacts", mock.MagicMock(), FakeResumableManager()))

        flat = [item for batch in batches for item in batch]
        assert flat == [
            {
                "slug": "art1",
                "title": "app.ipa",
                "app_slug": "app1",
                "build_slug": "b1",
                "build_triggered_at": "2026-01-01T00:00:00Z",
            }
        ]
        artifacts_url = mock_session.return_value.get.call_args_list[2].args[0]
        assert urlparse(artifacts_url).path == "/v0.1/apps/app1/builds/b1/artifacts"

    @mock.patch(TRACKED_SESSION)
    def test_incremental_filters_parent_builds(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"slug": "app1"}], "paging": {}}),
            _response({"data": [], "paging": {}}),
        ]

        list(
            get_rows(
                "token",
                "artifacts",
                mock.MagicMock(),
                FakeResumableManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )

        builds_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "after" in parse_qs(urlparse(builds_url).query)


class TestGetRowsUnknownEndpoint:
    @mock.patch(TRACKED_SESSION)
    def test_raises_value_error(self, mock_session):
        with pytest.raises(ValueError):
            list(get_rows("token", "nope", mock.MagicMock(), FakeResumableManager()))


class TestBitriseSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = BITRISE_ENDPOINTS[endpoint]
        response = bitrise_source("token", endpoint, mock.MagicMock(), FakeResumableManager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Fan-out + newest-first ordering: the watermark must only persist at job end.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    def test_fan_out_endpoints_have_parent_in_primary_key(self):
        assert BITRISE_ENDPOINTS["builds"].primary_keys == ["app_slug", "slug"]
        assert BITRISE_ENDPOINTS["workflows"].primary_keys == ["app_slug", "workflow"]
        assert BITRISE_ENDPOINTS["artifacts"].primary_keys == ["app_slug", "build_slug", "slug"]
