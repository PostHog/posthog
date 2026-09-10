from datetime import UTC, datetime
from typing import Any, cast

from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd import (
    BugherdResumeConfig,
    _format_bugherd_datetime,
    _incremental_window,
    _resource,
    bugherd_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.settings import BUGHERD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class _FakeDltResource:
    """Stand-in for a DltResource returned by ``rest_api_resources``.

    ``process_parent_data_item`` injects parent fields as ``_<parent_resource>_<field>``
    (see ``make_parent_key_name``), so test rows carry those prefixed keys to exercise
    ``build_dependent_resource``'s rename mapper.
    """

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _response(status_code: int = 200, text: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.text = text
    return response


class TestFormatBugherdDatetime:
    def test_formats_naive_datetime_as_utc(self) -> None:
        assert _format_bugherd_datetime(datetime(2024, 1, 15, 9, 30, 0)) == "2024-01-15T09:30:00Z"

    def test_formats_aware_datetime_converted_to_utc(self) -> None:
        aware = datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)
        assert _format_bugherd_datetime(aware) == "2024-01-15T09:30:00Z"

    def test_caps_future_datetime_to_now(self) -> None:
        far_future = datetime(2999, 1, 1, tzinfo=UTC)
        formatted = _format_bugherd_datetime(far_future)
        assert formatted != "2999-01-01T00:00:00Z"
        assert datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%SZ") <= datetime.now(UTC).replace(tzinfo=None)

    def test_passes_through_already_formatted_string(self) -> None:
        # Our own `initial_value` seed round-trips through `convert` on the first sync.
        assert _format_bugherd_datetime("1970-01-01T00:00:00Z") == "1970-01-01T00:00:00Z"


class TestIncrementalWindow:
    @parameterized.expand(
        [
            ("updated_at", "updated_since"),
            ("created_at", "created_since"),
        ]
    )
    def test_shape(self, field_name: str, query_param: str) -> None:
        window = _incremental_window(field_name, query_param)

        assert window["cursor_path"] == field_name
        assert window["start_param"] == query_param
        assert window["initial_value"] == "1970-01-01T00:00:00Z"
        assert window["convert"] is _format_bugherd_datetime


class TestResource:
    def test_organization_uses_single_page_paginator(self) -> None:
        resource = _resource(
            BUGHERD_ENDPOINTS["Organization"], should_use_incremental_field=False, incremental_field=None
        )

        assert resource["name"] == "Organization"
        assert resource["write_disposition"] == "replace"
        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["path"] == "/api_v2/organization.json"
        assert endpoint["data_selector"] == "organization"
        assert isinstance(endpoint["paginator"], SinglePagePaginator)
        assert "incremental" not in endpoint

    def test_users_is_full_refresh_with_page_paginator(self) -> None:
        resource = _resource(BUGHERD_ENDPOINTS["Users"], should_use_incremental_field=True, incremental_field=None)

        # Users has no incremental_fields declared, so should_use_incremental_field is ignored.
        assert resource["write_disposition"] == "replace"
        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert isinstance(endpoint["paginator"], PageNumberPaginator)
        assert "incremental" not in endpoint

    def test_tasks_default_incremental_field_maps_to_updated_since(self) -> None:
        resource = _resource(BUGHERD_ENDPOINTS["Tasks"], should_use_incremental_field=True, incremental_field=None)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["incremental"]["start_param"] == "updated_since"

    def test_tasks_honours_explicit_incremental_field_choice(self) -> None:
        resource = _resource(
            BUGHERD_ENDPOINTS["Tasks"], should_use_incremental_field=True, incremental_field="created_at"
        )

        endpoint = cast(dict[str, Any], resource["endpoint"])
        assert endpoint["incremental"]["start_param"] == "created_since"

    def test_tasks_full_refresh_when_incremental_disabled(self) -> None:
        resource = _resource(BUGHERD_ENDPOINTS["Tasks"], should_use_incremental_field=False, incremental_field=None)

        assert resource["write_disposition"] == "replace"
        assert "incremental" not in cast(dict[str, Any], resource["endpoint"])


class TestValidateCredentials:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.make_tracked_session")
    def test_valid_key(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(200)

        assert validate_credentials("valid-key") == (True, None)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.make_tracked_session")
    def test_invalid_key(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(401)

        assert validate_credentials("bad-key") == (False, "Invalid BugHerd API key.")

    @parameterized.expand([(500,), (503,), (403,)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.make_tracked_session")
    def test_other_status_is_reported(self, status_code: int, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(status_code)

        result = validate_credentials("key")

        assert result == (False, f"BugHerd API returned an unexpected status ({status_code}).")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.make_tracked_session")
    def test_network_error_returns_false(self, mock_make_session) -> None:
        from requests.exceptions import ConnectionError

        mock_make_session.return_value.get.side_effect = ConnectionError("boom")

        result = validate_credentials("key")

        assert result == (False, "Could not reach the BugHerd API: boom")


class TestBugherdSourceTopLevel:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource")
    def test_organization_builds_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        resp = bugherd_source(
            api_key="key", endpoint="Organization", team_id=1, job_id="job-1", resumable_source_manager=manager
        )

        assert resp.name == "Organization"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource")
    def test_projects_partitions_on_created_at(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        resp = bugherd_source(
            api_key="key", endpoint="Projects", team_id=1, job_id="job-1", resumable_source_manager=manager
        )

        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource")
    def test_flat_endpoint_seeds_paginator_from_saved_page(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BugherdResumeConfig(page=3)

        bugherd_source(api_key="key", endpoint="Users", team_id=1, job_id="job-1", resumable_source_manager=manager)

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] == {"page": 3}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource")
    def test_flat_endpoint_does_not_load_state_when_cannot_resume(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        bugherd_source(api_key="key", endpoint="Users", team_id=1, job_id="job-1", resumable_source_manager=manager)

        manager.load_state.assert_not_called()
        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource")
    def test_flat_endpoint_saves_checkpoint_via_resume_hook(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        bugherd_source(api_key="key", endpoint="Users", team_id=1, job_id="job-1", resumable_source_manager=manager)

        _, kwargs = mock_rest_api_resource.call_args
        resume_hook = kwargs["resume_hook"]
        resume_hook({"page": 5})

        manager.save_state.assert_called_once_with(BugherdResumeConfig(page=5))

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource")
    def test_flat_endpoint_resume_hook_ignores_terminal_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        bugherd_source(api_key="key", endpoint="Users", team_id=1, job_id="job-1", resumable_source_manager=manager)

        _, kwargs = mock_rest_api_resource.call_args
        kwargs["resume_hook"](None)

        manager.save_state.assert_not_called()

    def test_client_config_uses_http_basic_auth_with_x_password(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.rest_api_resource"
        ) as mock_rest_api_resource:
            mock_rest_api_resource.return_value = Mock()
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

            bugherd_source(
                api_key="secret-key", endpoint="Projects", team_id=1, job_id="job-1", resumable_source_manager=manager
            )

            (rest_config, *_rest), _ = mock_rest_api_resource.call_args
            assert rest_config["client"]["auth"] == {
                "type": "http_basic",
                "username": "secret-key",
                "password": "x",
            }


class TestBugherdFanout:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_tasks_row_format_renames_parent_id_to_project_id(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("Projects", [{"id": "1000"}]),
            _FakeDltResource("Tasks", [{"id": "98765", "_Projects_id": "1000"}]),
        ]
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        resp = bugherd_source(
            api_key="key", endpoint="Tasks", team_id=1, job_id="job-1", resumable_source_manager=manager
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["project_id"] == "1000"
        assert "_Projects_id" not in row

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.build_dependent_resource")
    def test_tasks_fanout_has_no_page_size_param(self, mock_build) -> None:
        mock_build.return_value = iter([])
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        bugherd_source(api_key="key", endpoint="Tasks", team_id=1, job_id="job-1", resumable_source_manager=manager)

        _, kwargs = mock_build.call_args
        assert kwargs["page_size_param"] is None
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], PageNumberPaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], PageNumberPaginator)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.build_dependent_resource")
    def test_tasks_incremental_passes_window_factory_mapped_to_created_since(self, mock_build) -> None:
        mock_build.return_value = iter([])
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        bugherd_source(
            api_key="key",
            endpoint="Tasks",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )

        _, kwargs = mock_build.call_args
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "created_at"
        window = kwargs["incremental_config_factory"]("created_at")
        assert window["start_param"] == "created_since"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.bugherd.build_dependent_resource")
    def test_tasks_fanout_seeds_resume_state_and_wires_hook(self, mock_build) -> None:
        mock_build.return_value = iter([])
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BugherdResumeConfig(page=2)

        bugherd_source(api_key="key", endpoint="Tasks", team_id=1, job_id="job-1", resumable_source_manager=manager)

        _, kwargs = mock_build.call_args
        assert kwargs["initial_paginator_state"] == {"page": 2}

        kwargs["resume_hook"]({"page": 4})
        manager.save_state.assert_called_once_with(BugherdResumeConfig(page=4))
