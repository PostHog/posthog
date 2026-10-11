import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.cloudinary import (
    CloudinaryResumeConfig,
    cloudinary_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.cloudinary"


def _manager(resume_state: CloudinaryResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    return response


def _source(endpoint: str = "images", region: str = "global", manager: mock.MagicMock | None = None) -> SourceResponse:
    return cloudinary_source("my-cloud", "key", "secret", region, endpoint, 1, "job", manager or _manager())


class TestCloudinarySource:
    def test_the_key_and_secret_ride_basic_auth(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            _source()

        assert rest_api_resource.call_args.args[0]["client"]["auth"] == {
            "type": "http_basic",
            "username": "key",
            "password": "secret",
        }

    def test_a_saved_cursor_seeds_the_paginator(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            _source(manager=_manager(CloudinaryResumeConfig(cursor="page-2")))

        assert rest_api_resource.call_args.kwargs["initial_paginator_state"] == {"cursor": "page-2"}

    def test_only_a_real_cursor_is_checkpointed(self) -> None:
        manager = _manager()
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            _source(manager=manager)

        resume_hook = rest_api_resource.call_args.kwargs["resume_hook"]
        resume_hook({})
        resume_hook(None)
        assert manager.save_state.call_args_list == []

        resume_hook({"cursor": "next"})
        assert manager.save_state.call_args_list == [mock.call(CloudinaryResumeConfig(cursor="next"))]


class TestCloudinaryCredentials:
    @pytest.mark.parametrize(
        "status_code,expected_valid",
        [(200, True), (401, False), (403, False), (404, False), (420, False), (429, False), (500, False)],
    )
    def test_status_maps_to_a_verdict(self, status_code: int, expected_valid: bool) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(status_code)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("my-cloud", "key", "secret", "global")

        assert valid is expected_valid
        assert (message is None) is expected_valid

    def test_the_probe_costs_nothing_against_the_quota(self) -> None:
        # /ping is the one Admin API call Cloudinary does not bill to the hourly limit.
        session = mock.MagicMock()
        session.get.return_value = _response()

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            validate_credentials("my-cloud", "key", "secret", "eu")

        assert session.get.call_args.args[0] == "https://api-eu.cloudinary.com/v1_1/my-cloud/ping"
        assert session.get.call_args.kwargs["auth"] == ("key", "secret")

    def test_an_unreachable_api_is_reported_rather_than_raised(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = ConnectionError("no route")

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("my-cloud", "key", "secret", "global")

        assert valid is False
        assert message is not None
