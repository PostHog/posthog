from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops import (
    AzureDevOpsAuthError,
    AzureDevOpsResumeConfig,
    _flatten_revision,
    _format_datetime,
    _validate_organization,
    azure_devops_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.settings import (
    AZURE_DEVOPS_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume_state: AzureDevOpsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], continuation_header: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    resp.headers = {"x-ms-continuationtoken": continuation_header} if continuation_header else {}
    return resp


class TestValidateOrganization:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("myorg", "myorg"),
            (" myorg ", "myorg"),
            ("https://dev.azure.com/myorg", "myorg"),
            ("dev.azure.com/myorg/project", "myorg"),
            ("my-org.unit_1", "my-org.unit_1"),
        ],
    )
    def test_valid_organizations(self, value, expected):
        assert _validate_organization(value) == expected

    @pytest.mark.parametrize("value", ["", "my org", "org?x=1"])
    def test_invalid_organizations_raise(self, value):
        with pytest.raises(ValueError):
            _validate_organization(value)


class TestFormatDatetime:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_datetime(value) == expected


class TestFlattenRevision:
    def test_copies_changed_date_to_top_level(self):
        item = {"id": 1, "rev": 2, "fields": {"System.ChangedDate": "2024-01-02T03:04:05Z"}}
        assert _flatten_revision(item)["changed_date"] == "2024-01-02T03:04:05Z"

    @pytest.mark.parametrize("item", [{"id": 1, "rev": 2}, {"id": 1, "fields": {}}, {"id": 1, "fields": None}])
    def test_leaves_items_without_changed_date_untouched(self, item):
        assert _flatten_revision(item) == item


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # An invalid PAT yields a 203 + HTML sign-in page, not a 401.
            (203, False),
            (401, False),
            (404, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("myorg", "pat") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_validate_credentials_rejects_bad_org_without_request(self, mock_session):
        assert validate_credentials("my org!", "pat") is False
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_projects_paginate_via_header_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}, continuation_header="tok1"),
            _response({"value": [{"id": "p2", "name": "Beta"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "pat", "projects", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["p1", "p2"]
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["continuationToken"] == ["tok1"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_builds_fan_out_per_project_with_ascending_order(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}),
            _response({"value": [{"id": 1, "queueTime": "2024-01-01T00:00:00Z"}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "pat", "builds", mock.MagicMock(), manager))

        assert batches == [[{"id": 1, "queueTime": "2024-01-01T00:00:00Z"}]]
        build_url = mock_session.return_value.get.call_args_list[1].args[0]
        parsed = urlparse(build_url)
        assert parsed.path == "/myorg/Alpha/_apis/build/builds"
        assert parse_qs(parsed.query)["queryOrder"] == ["queueTimeAscending"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_builds_incremental_includes_min_time(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}),
            _response({"value": []}),
        ]

        manager = _make_manager()
        list(
            get_rows(
                "myorg",
                "pat",
                "builds",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        build_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(build_url).query)["minTime"] == ["2024-01-02T00:00:00Z"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_pull_requests_use_skip_pagination_and_status_all(self, mock_session):
        full_page = {"value": [{"pullRequestId": i} for i in range(200)]}
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}),
            _response(full_page),
            _response({"value": [{"pullRequestId": 999}]}),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "pat", "pull_requests", mock.MagicMock(), manager))

        assert len(batches) == 2
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list[1:]]
        assert parse_qs(urlparse(urls[0]).query)["searchCriteria.status"] == ["all"]
        assert parse_qs(urlparse(urls[0]).query)["$skip"] == ["0"]
        assert parse_qs(urlparse(urls[1]).query)["$skip"] == ["200"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_revisions_walk_batches_and_flatten(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(
                {
                    "values": [{"id": 1, "rev": 1, "fields": {"System.ChangedDate": "2024-01-01T00:00:00Z"}}],
                    "continuationToken": "tok1",
                    "isLastBatch": False,
                }
            ),
            _response({"values": [{"id": 1, "rev": 2, "fields": {}}], "isLastBatch": True}),
        ]

        manager = _make_manager()
        batches = list(get_rows("myorg", "pat", "work_item_revisions", mock.MagicMock(), manager))

        assert batches[0][0]["changed_date"] == "2024-01-01T00:00:00Z"
        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].continuation_token == "tok1"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_revisions_resume_from_saved_token(self, mock_session):
        mock_session.return_value.get.return_value = _response({"values": [], "isLastBatch": True})

        manager = _make_manager(AzureDevOpsResumeConfig(continuation_token="tok_resume"))
        list(get_rows("myorg", "pat", "work_item_revisions", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["continuationToken"] == ["tok_resume"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_work_item_revisions_resume_does_not_send_start_date_time(self, mock_session):
        # A continuationToken fully encodes the stream position; pairing it with
        # startDateTime would reset the stream to the watermark on resume.
        mock_session.return_value.get.return_value = _response({"values": [], "isLastBatch": True})

        manager = _make_manager(AzureDevOpsResumeConfig(continuation_token="tok_resume"))
        list(
            get_rows(
                "myorg",
                "pat",
                "work_item_revisions",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        query = parse_qs(urlparse(mock_session.return_value.get.call_args.args[0]).query)
        assert query["continuationToken"] == ["tok_resume"]
        assert "startDateTime" not in query

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_project_enumeration_does_not_carry_endpoint_incremental_param(self, mock_session):
        # Project enumeration is independent of the data endpoint being synced,
        # so the builds incremental filter must not leak into it.
        mock_session.return_value.get.side_effect = [
            _response({"value": [{"id": "p1", "name": "Alpha"}]}),
            _response({"value": []}),
        ]

        manager = _make_manager()
        list(
            get_rows(
                "myorg",
                "pat",
                "builds",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        projects_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert urlparse(projects_url).path == "/myorg/_apis/projects"
        assert "minTime" not in parse_qs(urlparse(projects_url).query)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.azure_devops.azure_devops.make_tracked_session"
    )
    def test_sign_in_page_raises_auth_error(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 203
        response.ok = True
        mock_session.return_value.get.return_value = response

        manager = _make_manager()
        with pytest.raises(AzureDevOpsAuthError):
            list(get_rows("myorg", "pat", "projects", mock.MagicMock(), manager))


class TestAzureDevOpsSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = AZURE_DEVOPS_ENDPOINTS[endpoint]
        response = azure_devops_source("myorg", "pat", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_pull_requests_are_desc_sorted(self):
        response = azure_devops_source("myorg", "pat", "pull_requests", mock.MagicMock(), _make_manager())
        assert response.sort_mode == "desc"

    @pytest.mark.parametrize("config", list(AZURE_DEVOPS_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"queueTime", "creationDate", "changed_date"}
