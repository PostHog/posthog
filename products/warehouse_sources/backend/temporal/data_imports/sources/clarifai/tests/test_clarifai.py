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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)
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
    @staticmethod
    def _driver(config: ClarifaiSourceConfig) -> SourceDriver:
        return SourceDriver(ClarifaiSource(), config)

    @pytest.mark.parametrize(
        ("endpoint", "path", "data_key", "extra_params"),
        [
            ("models", "models", "models", {}),
            ("workflows", "workflows", "workflows", {}),
            ("datasets", "datasets", "datasets", {}),
            ("concepts", "concepts", "concepts", {}),
            ("inputs", "inputs", "inputs", {}),
            ("concept_relations", "concepts/relations", "concept_relations", {}),
            ("annotations", "annotations", "annotations", {"list_all_annotations": ["true"]}),
            ("evaluations", "evaluations", "eval_metrics", {"show_failed_metrics": ["true"]}),
            ("tasks", "tasks", "tasks", {"including_label_order_tasks": ["true"]}),
            ("collaborators", "collaborators", "collaborators", {"list_all_collaborators": ["true"]}),
        ],
    )
    @pytest.mark.parametrize("resume_page", [None, 4])
    def test_pagination_and_resume(
        self,
        config: ClarifaiSourceConfig,
        manager: MagicMock,
        endpoint: str,
        path: str,
        data_key: str,
        extra_params: dict[str, list[str]],
        resume_page: int | None,
    ) -> None:
        if resume_page is not None:
            manager.can_resume.return_value = True
            manager.load_state.return_value = ClarifaiResumeConfig(page=resume_page)
        first_page = resume_page or 1
        with requests_mock.Mocker() as http:
            http.get(
                BASE_URL + path,
                [
                    {"json": {"status": {"code": 10000}, data_key: [{"id": "row-1"}]}},
                    {"json": {"status": {"code": 10000}, data_key: [{"id": "row-2"}]}},
                    {"json": {"status": {"code": 10000}, data_key: []}},
                ],
            )
            response = ClarifaiClient(config, 42, "v2").source(endpoint, "test-job", manager)
            rows = [row for page in cast(Iterable[list[dict[str, Any]]], response.items()) for row in page]
            assert rows == [{"id": "row-1"}, {"id": "row-2"}]
            assert [request.qs for request in http.request_history] == [
                {"page": [str(page)], "per_page": ["128"], **extra_params} for page in range(first_page, first_page + 3)
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
        ("endpoint", "parent", "data_key", "child_row", "expected_row"),
        [
            (
                "dataset_inputs",
                "datasets",
                "dataset_inputs",
                {"input": {"id": "input-1"}},
                {"input": {"id": "input-1"}, "input_id": "input-1"},
            ),
            ("model_versions", "models", "model_versions", {"id": "version-1"}, {"id": "version-1"}),
        ],
    )
    @pytest.mark.parametrize("resumed", [False, True])
    def test_fan_out_pagination_and_resume(
        self,
        config: ClarifaiSourceConfig,
        endpoint: str,
        parent: str,
        data_key: str,
        child_row: dict[str, Any],
        expected_row: dict[str, Any],
        resumed: bool,
    ) -> None:
        parent_key = "dataset_id" if parent == "datasets" else "model_id"
        child_suffix = "inputs" if parent == "datasets" else "versions"
        prefix = "/v2/users/example-user/apps/example-app/"

        def ok(key: str, rows: list[dict[str, Any]]) -> ScriptedResponse:
            return ScriptedResponse(json={"status": {"code": 10000}, key: rows})

        script = route(
            {
                f"{prefix}{parent}": [
                    ok(
                        parent,
                        [
                            {"id": "parent-1"},
                            {"id": "main-row", "user_id": "clarifai", "app_id": "main"},
                            {"id": "parent-2", "user_id": "example-user", "app_id": "example-app"},
                        ],
                    ),
                    ok(parent, []),
                ],
                f"{prefix}{parent}/parent-1/{child_suffix}": [ok(data_key, [child_row]), ok(data_key, [])],
                f"{prefix}{parent}/parent-2/{child_suffix}": [
                    ok(data_key, [child_row]),
                    ok(data_key, [child_row]),
                    ok(data_key, []),
                ],
            }
        )
        resume_state = (
            ClarifaiResumeConfig(
                fanout_state={"completed": [f"{parent}/parent-1/{child_suffix}"], "current": None, "child_state": None}
            )
            if resumed
            else None
        )
        result = self._driver(config).run(endpoint, script, resume_state=resume_state)

        assert result.raised is None
        expected_parents = ["parent-2"] * 2 if resumed else ["parent-1", "parent-2", "parent-2"]
        assert result.rows == [{**expected_row, parent_key: parent_id} for parent_id in expected_parents]
        child_requests = [request for request in result.requests if request.path.endswith(child_suffix)]
        assert [(request.path.split("/")[-2], request.param("page")) for request in child_requests] == (
            [] if resumed else [("parent-1", "1"), ("parent-1", "2")]
        ) + [("parent-2", "1"), ("parent-2", "2"), ("parent-2", "3")]
        assert all(request.param("per_page") == "128" for request in result.requests)
        assert result.final_state is None or result.final_state.page is None

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
        self, config: ClarifaiSourceConfig, http_status: int, api_status: int, message: str
    ) -> None:
        result = self._driver(config).run(
            "models", [ScriptedResponse(status=http_status, json={"status": {"code": api_status}})]
        )
        assert isinstance(result.raised, (HTTPError, ValueError))
        assert message in str(result.raised)
        assert any(pattern in str(result.raised) for pattern in ClarifaiSource().get_non_retryable_errors())
        assert len(result.requests) == 1
        assert result.saved_states == []

    @pytest.mark.parametrize(
        ("http_status", "api_status"), [(200, 10030), (200, 11003), (200, 11005), (429, 11005), (503, 10020)]
    )
    def test_transient_errors_retry(self, config: ClarifaiSourceConfig, http_status: int, api_status: int) -> None:
        result = self._driver(config).run(
            "models", always(ScriptedResponse(status=http_status, json={"status": {"code": api_status}}))
        )
        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5
        assert result.saved_states == []

    @pytest.mark.parametrize(
        "body", [{}, {"status": {"code": 10020}}, {"status": {"code": 10010}}, {"status": {"code": 99999}}]
    )
    def test_unsuccessful_response_is_not_empty_data(
        self, config: ClarifaiSourceConfig, body: dict[str, object]
    ) -> None:
        result = self._driver(config).run("models", [ScriptedResponse(json=body)])
        assert isinstance(result.raised, ValueError)
        assert "unsuccessful response" in str(result.raised)
        assert result.saved_states == []

    def test_redirect_is_not_followed(self, config: ClarifaiSourceConfig) -> None:
        result = self._driver(config).run(
            "models", [ScriptedResponse(status=302, headers={"Location": "https://other.example.com/"})]
        )
        assert isinstance(result.raised, ValueError)
        assert "redirect" in str(result.raised)
        assert len(result.requests) == 1


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
            (200, 10000, "model_versions", True, None),
            (200, 11007, "dataset_inputs", False, "The Clarifai token lacks permission"),
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
        # Fan-out tables have no parent ID at probe time, so the probe lists their parent.
        endpoint = {"model_versions": "models", "dataset_inputs": "datasets"}.get(
            schema_name or "", schema_name or "models"
        )
        with scripted_network(
            [ScriptedResponse(status=http_status, json={"status": {"code": api_status}, endpoint: []})]
        ) as network:
            result, error = ClarifaiSource().validate_credentials(config, 42, schema_name)
            assert result is valid
            assert error is None if message is None else message in (error or "")
            assert len(network.requests_log) == 1
            assert network.requests_log[0].path == f"/v2/users/example-user/apps/example-app/{endpoint}"
            assert network.requests_log[0].param("page") == "1"
            assert network.requests_log[0].param("per_page") == "1"
            assert network.requests_log[0].headers["authorization"] == "Key fake-clarifai-pat"

    @pytest.mark.parametrize(
        "http_status,expected",
        [
            (400, HTTPError),
            (429, (False, "Couldn't reach Clarifai to check your credentials. Try again in a few minutes.")),
            (500, (False, "Couldn't reach Clarifai to check your credentials. Try again in a few minutes.")),
        ],
    )
    def test_probe_does_not_disguise_other_errors(
        self, config: ClarifaiSourceConfig, http_status: int, expected: type[Exception] | tuple[bool, str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=http_status, json={"status": {"code": 10020}}))):
            if isinstance(expected, tuple):
                assert ClarifaiSource().validate_credentials(config, 42) == expected
            else:
                with pytest.raises(expected):
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
        with scripted_network([]) as network:
            valid, error = ClarifaiSource().validate_credentials(config, 42)
            assert not valid
            assert error is not None and "public HTTPS API host" in error
            assert network.requests_log == []

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
        with scripted_network([ScriptedResponse(json={"status": {"code": 10000}})]) as network:
            assert ClarifaiSource().validate_credentials(config, 42) == (True, None)
            assert len(network.requests_log) == 1
            assert network.requests_log[0].url.startswith(
                host.rstrip("/") + "/v2/users/example-user/apps/example-app/models"
            )

    @pytest.mark.parametrize("field", ["user_id", "app_id"])
    @pytest.mark.parametrize("value", ["", "..", "../other", "user?query=yes"])
    def test_rejects_path_injection(self, config: ClarifaiSourceConfig, field: str, value: str) -> None:
        setattr(config, field, value)
        with scripted_network([]) as network:
            valid, error = ClarifaiSource().validate_credentials(config, 42)
            assert not valid
            assert error is not None and "valid Clarifai user ID" in error
            assert network.requests_log == []
