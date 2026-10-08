import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spot_io.spot_io import (
    SpotIoResumeConfig,
    _account_params,
    get_resource,
    spot_io_source,
    validate_credentials,
)


def _make_manager(resume_state: SpotIoResumeConfig | None = None) -> Mock:
    manager = Mock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


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


class TestSpotIoSourceTopLevel:
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
