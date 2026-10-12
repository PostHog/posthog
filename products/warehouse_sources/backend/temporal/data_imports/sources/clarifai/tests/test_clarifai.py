from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.clarifai.clarifai import (
    ClarifaiClient,
    ClarifaiResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clarifai.source import ClarifaiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clarifai import (
    ClarifaiSourceConfig,
)

BASE_URL = "https://api.clarifai.com/v2/users/example-user/apps/example-app/"


@pytest.fixture
def config() -> ClarifaiSourceConfig:
    return ClarifaiSourceConfig(personal_access_token="fake-clarifai-pat", user_id="example-user", app_id="example-app")


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


class TestClarifaiTransport:
    @pytest.mark.parametrize("endpoint", ["models", "workflows", "datasets", "concepts"])
    @pytest.mark.parametrize("resume_page", [None, 4])
    def test_pagination_and_resume(
        self, config: ClarifaiSourceConfig, manager: MagicMock, endpoint: str, resume_page: int | None
    ) -> None:
        if resume_page is not None:
            manager.can_resume.return_value = True
            manager.load_state.return_value = ClarifaiResumeConfig(page=resume_page)
        first_page = resume_page or 1
        with requests_mock.Mocker() as http:
            http.get(
                BASE_URL + endpoint,
                [
                    {"json": {"status": {"code": 10000}, endpoint: [{"id": "row-1"}]}},
                    {"json": {"status": {"code": 10000}, endpoint: [{"id": "row-2"}]}},
                    {"json": {"status": {"code": 10000}, endpoint: []}},
                ],
            )
            response = ClarifaiClient(config, 42, "v2").source(endpoint, "test-job", manager)
            rows = [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]
            assert rows == [{"id": "row-1"}, {"id": "row-2"}]
            assert [request.qs for request in http.request_history] == [
                {"page": [str(page)], "per_page": ["128"]} for page in range(first_page, first_page + 3)
            ]
            assert all(request.headers["Authorization"] == "Key fake-clarifai-pat" for request in http.request_history)
            assert all(request.timeout == (10, 60) for request in http.request_history)
            assert [call.args[0] for call in manager.save_state.call_args_list] == [
                ClarifaiResumeConfig(page=first_page + 1),
                ClarifaiResumeConfig(page=first_page + 2),
            ]
            assert response.on_complete is not None
            response.on_complete()
            manager.clear_state.assert_called_once_with()

    @pytest.mark.parametrize(
        ("http_status", "api_status", "message"),
        [
            (401, 11008, "401 Client Error"),
            (403, 11007, "403 Client Error"),
            (404, 11101, "404 Client Error"),
            (200, 11001, "Clarifai rejected the token"),
            (200, 11002, "Clarifai rejected the token"),
            (200, 11008, "Clarifai rejected the token"),
            (200, 11009, "Clarifai rejected the token"),
            (200, 11200, "Clarifai rejected the token"),
            (200, 11007, "The Clarifai token lacks permission"),
            (200, 11101, "Clarifai could not find the resource"),
            (200, 11000, "Clarifai account access is limited"),
            (200, 11004, "Clarifai account access is limited"),
            (200, 11006, "Clarifai account access is limited"),
        ],
    )
    def test_permanent_errors(
        self, config: ClarifaiSourceConfig, manager: MagicMock, http_status: int, api_status: int, message: str
    ) -> None:
        with requests_mock.Mocker() as http:
            http.get(BASE_URL + "models", status_code=http_status, json={"status": {"code": api_status}})
            with pytest.raises((HTTPError, ValueError), match=message) as error:
                list(
                    cast(
                        Iterable[Any],
                        ClarifaiClient(config, 42, "v2").source("models", "test-job", manager).items(),
                    )
                )
            assert any(pattern in str(error.value) for pattern in ClarifaiSource().get_non_retryable_errors())
            assert http.call_count == 1
            manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        ("http_status", "api_status"), [(200, 10030), (200, 11003), (200, 11005), (429, 11005), (503, 10020)]
    )
    def test_transient_errors_retry(
        self, config: ClarifaiSourceConfig, manager: MagicMock, http_status: int, api_status: int
    ) -> None:
        with (
            requests_mock.Mocker() as http,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
            ),
        ):
            http.get(BASE_URL + "models", status_code=http_status, json={"status": {"code": api_status}})
            with pytest.raises(RESTClientRetryableError):
                list(
                    cast(
                        Iterable[Any],
                        ClarifaiClient(config, 42, "v2").source("models", "test-job", manager).items(),
                    )
                )
            assert http.call_count == 5
            manager.save_state.assert_not_called()

    @pytest.mark.parametrize(
        "body", [{}, {"status": {"code": 10020}}, {"status": {"code": 10010}}, {"status": {"code": 99999}}]
    )
    def test_unsuccessful_response_is_not_empty_data(
        self, config: ClarifaiSourceConfig, manager: MagicMock, body: dict[str, object]
    ) -> None:
        with requests_mock.Mocker() as http:
            http.get(BASE_URL + "models", json=body)
            with pytest.raises(ValueError, match="unsuccessful response"):
                list(
                    cast(
                        Iterable[Any],
                        ClarifaiClient(config, 42, "v2").source("models", "test-job", manager).items(),
                    )
                )
            manager.save_state.assert_not_called()

    def test_redirect_is_not_followed(self, config: ClarifaiSourceConfig, manager: MagicMock) -> None:
        with requests_mock.Mocker() as http:
            http.get(BASE_URL + "models", status_code=302, headers={"Location": "https://other.example.com/"})
            with pytest.raises(ValueError, match="redirect"):
                list(
                    cast(
                        Iterable[Any],
                        ClarifaiClient(config, 42, "v2").source("models", "test-job", manager).items(),
                    )
                )
            assert http.call_count == 1

    def test_unknown_endpoint_does_not_request(self, config: ClarifaiSourceConfig, manager: MagicMock) -> None:
        with requests_mock.Mocker() as http:
            with pytest.raises(UnknownResourceError):
                ClarifaiClient(config, 42, "v2").source("unknown", "test-job", manager)
            assert http.call_count == 0


class TestClarifaiCredentials:
    @pytest.mark.parametrize(
        ("http_status", "api_status", "schema_name", "valid", "message"),
        [
            (200, 10000, None, True, None),
            (200, 10001, None, True, None),
            (200, 10002, "datasets", True, None),
            (401, 11008, None, False, "Clarifai rejected the token"),
            (403, 11007, None, True, None),
            (403, 11007, "datasets", False, "The Clarifai token lacks permission"),
            (200, 11008, None, False, "Clarifai rejected the token"),
            (200, 11007, None, True, None),
            (200, 11007, "datasets", False, "The Clarifai token lacks permission"),
            (404, 11101, None, False, "Clarifai could not find the resource"),
        ],
    )
    def test_probe_status_mapping(
        self,
        config: ClarifaiSourceConfig,
        http_status: int,
        api_status: int,
        schema_name: str | None,
        valid: bool,
        message: str | None,
    ) -> None:
        endpoint = schema_name or "models"
        with requests_mock.Mocker() as http:
            http.get(BASE_URL + endpoint, status_code=http_status, json={"status": {"code": api_status}, endpoint: []})
            result, error = ClarifaiSource().validate_credentials(config, 42, schema_name)
            assert result is valid
            assert error is None if message is None else message in (error or "")
            assert http.call_count == 1
            assert http.last_request is not None
            assert http.last_request.qs == {"page": ["1"], "per_page": ["1"]}
            assert http.last_request.headers["Authorization"] == "Key fake-clarifai-pat"

    @pytest.mark.parametrize("http_status", [400, 429, 500])
    def test_probe_does_not_disguise_other_errors(self, config: ClarifaiSourceConfig, http_status: int) -> None:
        with (
            requests_mock.Mocker() as http,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.RESTClient._send_request.retry.sleep"
            ),
        ):
            http.get(BASE_URL + "models", status_code=http_status, json={"status": {"code": 10020}})
            with pytest.raises((HTTPError, RESTClientRetryableError)):
                ClarifaiSource().validate_credentials(config, 42)

    @pytest.mark.parametrize(
        "host",
        [
            "http://example.com",
            "https://user:password@example.com",
            "https://example.com/path",
            "https://example.com?q=x",
            "https://example.com#x",
            "https://example.com:bad",
            "https://[bad",
            "https://example.com\\@other.example.com",
            "https://exa mple.com",
        ],
    )
    def test_rejects_invalid_host(self, config: ClarifaiSourceConfig, host: str) -> None:
        config.api_host = host
        with requests_mock.Mocker() as http:
            valid, error = ClarifaiSource().validate_credentials(config, 42)
            assert not valid
            assert error is not None and "public HTTPS API host" in error
            assert http.call_count == 0

    @pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
    def test_rejects_internal_host(self, config: ClarifaiSourceConfig, address: str) -> None:
        config.api_host = "https://clarifai.example.com"
        with (
            requests_mock.Mocker() as http,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.is_cloud",
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins.get_instance_region",
                return_value="US",
            ),
            patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (address, 443))]),
        ):
            valid, error = ClarifaiSource().validate_credentials(config, 42)
            assert not valid
            assert error is not None and "public HTTPS API host" in error
            assert http.call_count == 0

    @pytest.mark.parametrize("host", ["https://clarifai.example.com", "https://clarifai.example.com:8443/"])
    def test_custom_host(self, config: ClarifaiSourceConfig, host: str) -> None:
        config.api_host = host
        with requests_mock.Mocker() as http:
            http.get(
                host.rstrip("/") + "/v2/users/example-user/apps/example-app/models", json={"status": {"code": 10000}}
            )
            assert ClarifaiSource().validate_credentials(config, 42) == (True, None)
            assert http.call_count == 1

    @pytest.mark.parametrize("field", ["user_id", "app_id"])
    @pytest.mark.parametrize("value", ["", "..", "../other", "user?query=yes"])
    def test_rejects_path_injection(self, config: ClarifaiSourceConfig, field: str, value: str) -> None:
        setattr(config, field, value)
        with requests_mock.Mocker() as http:
            valid, error = ClarifaiSource().validate_credentials(config, 42)
            assert not valid
            assert error is not None and "valid Clarifai user ID" in error
            assert http.call_count == 0
