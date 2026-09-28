import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.cloudinary import (
    CloudinaryResumeConfig,
    base_url,
    cloudinary_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.settings import (
    CLOUDINARY_ENDPOINTS,
    MAX_RESULTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)

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


def _source(endpoint: str = "images", region: str = "global", manager: mock.MagicMock | None = None):
    return cloudinary_source("my-cloud", "key", "secret", region, endpoint, 1, "job", manager or _manager())


class TestCloudinaryRegions:
    @pytest.mark.parametrize(
        "region,expected",
        [
            ("global", "https://api.cloudinary.com/v1_1/my-cloud"),
            ("eu", "https://api-eu.cloudinary.com/v1_1/my-cloud"),
            ("ap", "https://api-ap.cloudinary.com/v1_1/my-cloud"),
            ("not-a-region", "https://api.cloudinary.com/v1_1/my-cloud"),
        ],
    )
    def test_each_region_maps_to_its_host(self, region: str, expected: str) -> None:
        assert base_url("my-cloud", region) == expected


class TestCloudinaryResources:
    @pytest.mark.parametrize("endpoint", sorted(CLOUDINARY_ENDPOINTS))
    def test_rows_are_selected_from_the_endpoints_own_envelope(self, endpoint: str) -> None:
        config = CLOUDINARY_ENDPOINTS[endpoint]
        resource = get_resource(endpoint)
        assert resource["endpoint"]["data_selector"] == f"{config.data_key}[*]"
        assert resource["primary_key"] == config.primary_key

    @pytest.mark.parametrize("endpoint", sorted(CLOUDINARY_ENDPOINTS))
    def test_every_endpoint_asks_for_the_largest_page(self, endpoint: str) -> None:
        # Cloudinary counts each call against an hourly quota, so a small page multiplies the cost.
        assert get_resource(endpoint)["endpoint"]["params"]["max_results"] == MAX_RESULTS

    @pytest.mark.parametrize("endpoint", ["images", "videos", "raw_files"])
    def test_asset_tables_ask_for_tags_and_context(self, endpoint: str) -> None:
        # Cloudinary omits both unless asked, and they are the fields users join on.
        params = get_resource(endpoint)["endpoint"]["params"]
        assert params["tags"] == "true"
        assert params["context"] == "true"


class TestCloudinarySource:
    def test_pages_are_walked_with_cloudinarys_cursor_field(self) -> None:
        with mock.patch(f"{_MODULE}.rest_api_resource") as rest_api_resource:
            _source()

        paginator = rest_api_resource.call_args.args[0]["client"]["paginator"]
        assert isinstance(paginator, JSONResponseCursorPaginator)
        assert paginator.cursor_path == "next_cursor"
        assert paginator.cursor_param == "next_cursor"

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

    def test_an_unknown_cloud_name_is_called_out(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _response(404)

        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=session):
            _, message = validate_credentials("my-cloud", "key", "secret", "global")

        assert message is not None and "cloud name" in message

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
