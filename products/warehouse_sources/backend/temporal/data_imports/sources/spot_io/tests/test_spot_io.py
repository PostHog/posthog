from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io import (
    SpotIoResumeConfig,
    _account_params,
    _cost_window_end,
    _cost_window_start,
    _format_time_value,
    get_resource,
    spot_io_source,
    validate_credentials,
)


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


def _make_manager(resume_state: SpotIoResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestSpotIoDateFormatting:
    def test_format_time_value(self) -> None:
        value = _format_time_value(datetime(2026, 3, 1, 12, 30, 45, tzinfo=UTC))
        assert value == "2026-03-01T12:30:45.000Z"

    def test_cost_window_end_is_spot_format(self) -> None:
        value = _cost_window_end()
        assert value.endswith(".000Z")
        # Round-trips using the exact format Spot documents.
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.000Z")

    def test_cost_window_start_is_before_end(self) -> None:
        start = datetime.strptime(_cost_window_start(), "%Y-%m-%dT%H:%M:%S.000Z")
        end = datetime.strptime(_cost_window_end(), "%Y-%m-%dT%H:%M:%S.000Z")
        assert start < end


class TestSpotIoAccountParams:
    @parameterized.expand(
        [
            ("with_account", "act-123", {"accountId": "act-123"}),
            ("no_account", None, {}),
            ("empty_string", "", {}),
        ]
    )
    def test_account_params(self, _name, account_id, expected) -> None:
        assert _account_params(account_id) == expected


class TestSpotIoGetResource:
    def test_elastigroups_full_refresh(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="elastigroups"))
        assert resource["name"] == "elastigroups"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/aws/ec2/group"
        assert resource["endpoint"]["data_selector"] == "response.items"
        assert isinstance(resource["endpoint"]["paginator"], SinglePagePaginator)
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["params"] == {}

    def test_includes_account_id_when_given(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="ocean_clusters", account_id="act-1"))
        assert resource["endpoint"]["params"] == {"accountId": "act-1"}

    def test_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint="elastigroup_costs")


class TestSpotIoValidateCredentials:
    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid or expired Spot by Flexera API token"),
            (403, False, "Spot by Flexera API token does not have the required permissions"),
            (500, False, "Spot by Flexera API returned an unexpected status: 500"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.make_tracked_session")
    def test_validate_credentials_status_mapping(self, status, expected_valid, expected_message, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=status)

        result = validate_credentials(api_token="token")

        assert result == (expected_valid, expected_message)
        call = mock_session.return_value.get.call_args
        assert call.args[0] == "https://api.spotinst.io/aws/ec2/group"
        assert call.kwargs["headers"]["Authorization"] == "Bearer token"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.make_tracked_session")
    def test_validate_credentials_passes_account_id(self, mock_session) -> None:
        mock_session.return_value.get.return_value = Mock(status_code=200)

        validate_credentials(api_token="token", account_id="act-9")

        call = mock_session.return_value.get.call_args
        assert call.kwargs["params"] == {"accountId": "act-9"}


class TestSpotIoSourceTopLevel:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.rest_api_resource")
    def test_top_level_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = spot_io_source(
            api_token="token",
            endpoint="elastigroups",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        assert response.name == "elastigroups"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.rest_api_resource")
    def test_resumes_from_saved_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager(SpotIoResumeConfig(paginator_state={"offset": 5}))

        spot_io_source(
            api_token="token",
            endpoint="elastigroups",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_rest_api_resource.call_args.kwargs
        assert kwargs["initial_paginator_state"] == {"offset": 5}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.rest_api_resource")
    def test_saves_checkpoints_after_batches(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_manager()

        spot_io_source(
            api_token="token",
            endpoint="elastigroups",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        resume_hook = mock_rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({"offset": 1})
        manager.save_state.assert_called_once_with(SpotIoResumeConfig(paginator_state={"offset": 1}))

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.rest_api_resource")
    def test_passes_account_id_through_resource_config(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        spot_io_source(
            api_token="token",
            account_id="act-42",
            endpoint="elastigroups",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        config = mock_rest_api_resource.call_args.args[0]
        assert config["resources"][0]["endpoint"]["params"] == {"accountId": "act-42"}


class TestSpotIoFanoutRowFormat:
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_elastigroup_costs_row_format(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("elastigroups", [{"id": "sig-1", "name": "web-fleet"}]),
            _FakeDltResource(
                "elastigroup_costs",
                [
                    {
                        "groupId": "sig-1",
                        "instanceId": "i-abc",
                        "costs": {"actual": 1.5, "potential": 3.0},
                        "_elastigroups_name": "web-fleet",
                    }
                ],
            ),
        ]

        response = spot_io_source(
            api_token="token",
            endpoint="elastigroup_costs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        rows = list(cast(Any, response.items()))
        assert rows == [
            {
                "groupId": "sig-1",
                "instanceId": "i-abc",
                "costs": {"actual": 1.5, "potential": 3.0},
                "elastigroup_name": "web-fleet",
            }
        ]
        assert response.primary_keys == ["groupId", "instanceId"]
        assert response.partition_mode is None


class TestSpotIoFanoutWiring:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.build_dependent_resource")
    def test_fanout_wiring(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])
        manager = _make_manager(SpotIoResumeConfig(paginator_state={"completed": []}))

        spot_io_source(
            api_token="token",
            account_id="act-1",
            endpoint="elastigroup_costs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] is None
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "response.items"
        assert kwargs["child_endpoint_extra"]["data_selector"] == "response.items"
        assert "fromDate" in kwargs["child_params_extra"]
        assert "toDate" in kwargs["child_params_extra"]
        assert kwargs["child_params_extra"]["accountId"] == "act-1"
        assert kwargs["fanout"].parent_params == {"accountId": "act-1"}
        assert kwargs["resume_hook"] is not None
        assert kwargs["initial_paginator_state"] == {"completed": []}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io.build_dependent_resource")
    def test_fanout_wiring_without_account_id(self, mock_build_dependent_resource) -> None:
        mock_build_dependent_resource.return_value = iter([])

        spot_io_source(
            api_token="token",
            endpoint="elastigroup_costs",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_make_manager(),
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert "accountId" not in kwargs["child_params_extra"]
        assert kwargs["fanout"].parent_params == {}
