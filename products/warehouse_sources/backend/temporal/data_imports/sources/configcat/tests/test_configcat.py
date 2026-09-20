import json
import base64
from typing import Any

import pytest
from unittest import mock
from unittest.mock import MagicMock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.configcat import configcat
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.configcat import (
    CONFIGCAT_BASE_URL,
    _headers,
    check_access,
    configcat_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import (
    CONFIGCAT_ENDPOINTS,
    ENDPOINTS,
)

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _response(body: Any) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session and capture each request's URL at send time."""
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestHeaders:
    def test_basic_auth_header_encodes_username_and_password(self) -> None:
        headers = _headers("user", "pass")
        expected = base64.b64encode(b"user:pass").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"


class TestConfigCatSource:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_yields_full_collection_in_one_request(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        urls = _wire(session, [_response([{"productId": "a"}, {"productId": "b"}])])

        rows = _rows(configcat_source("user", "pass", "products", team_id=1, job_id="j"))

        assert rows == [{"productId": "a"}, {"productId": "b"}]
        # The list endpoint returns the whole collection in a single response — no pagination.
        assert session.send.call_count == 1
        assert urls[0] == f"{CONFIGCAT_BASE_URL}/v1/products"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_collection_yields_no_rows(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response([])])

        assert _rows(configcat_source("user", "pass", "products", team_id=1, job_id="j")) == []
        assert session.send.call_count == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loud(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        _wire(session, [_response({"error": "nope"})])

        # A 200 body that isn't a bare array means the response shape changed — fail loud instead of
        # syncing the stray object as a single row.
        with pytest.raises(ValueError, match="list response body"):
            _rows(configcat_source("user", "pass", "products", team_id=1, job_id="j"))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_targets_endpoint_specific_path(self, MockSession: MagicMock) -> None:
        session = MockSession.return_value
        urls = _wire(session, [_response([{"organizationId": "o"}])])

        _rows(configcat_source("user", "pass", "organizations", team_id=1, job_id="j"))
        assert urls[0] == f"{CONFIGCAT_BASE_URL}/v1/organizations"


class _FakeSession:
    """Serves canned bodies by path and records every path the fan-out requested."""

    def __init__(self, bodies: dict[str, Any]) -> None:
        self.bodies = bodies
        self.paths: list[str] = []

    def get(self, url: str, timeout: int | None = None) -> Any:
        path = url.removeprefix(CONFIGCAT_BASE_URL)
        self.paths.append(path)
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = self.bodies[path]
        return response


class TestConfigCatFanOut:
    @staticmethod
    def _run(
        mock_make_session: MagicMock, bodies: dict[str, Any], endpoint: str
    ) -> tuple[list[dict[str, Any]], list[str]]:
        session = _FakeSession(bodies)
        mock_make_session.return_value = session
        rows = _rows(configcat_source("user", "pass", endpoint, team_id=1, job_id="j"))
        return rows, session.paths

    @parameterized.expand(
        [
            ("configs", "/v1/products/{}/configs", "configId"),
            ("environments", "/v1/products/{}/environments", "environmentId"),
        ]
    )
    @mock.patch.object(configcat, "make_tracked_session")
    def test_product_children_are_fetched_once_per_product(
        self, endpoint: str, child_path: str, id_field: str, mock_make_session: MagicMock
    ) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}, {"productId": "p2"}],
            child_path.format("p1"): [{id_field: "a"}],
            child_path.format("p2"): [{id_field: "b"}],
        }
        rows, paths = self._run(mock_make_session, bodies, endpoint)

        assert rows == [{id_field: "a"}, {id_field: "b"}]
        assert paths == ["/v1/products", child_path.format("p1"), child_path.format("p2")]

    @mock.patch.object(configcat, "make_tracked_session")
    def test_settings_walk_products_then_configs(self, mock_make_session: MagicMock) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1"}, {"configId": "c2"}],
            "/v1/configs/c1/settings": [{"settingId": 1, "configId": "c1"}],
            "/v1/configs/c2/settings": [{"settingId": 1, "configId": "c2"}],
        }
        rows, paths = self._run(mock_make_session, bodies, "settings")

        # `settingId` repeats across configs, which is why the key is composite.
        assert rows == [{"settingId": 1, "configId": "c1"}, {"settingId": 1, "configId": "c2"}]
        assert paths[-2:] == ["/v1/configs/c1/settings", "/v1/configs/c2/settings"]

    @mock.patch.object(configcat, "make_tracked_session")
    def test_setting_values_pair_configs_with_environments_of_the_same_product(
        self, mock_make_session: MagicMock
    ) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}, {"productId": "p2"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v2"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v1/products/p2/configs": [{"configId": "c2", "evaluationVersion": "v2"}],
            "/v1/products/p2/environments": [{"environmentId": "e2"}],
            "/v2/configs/c1/environments/e1/values": {
                "settingFormulas": [{"setting": {"settingId": 7}, "defaultValue": {"boolValue": True}}]
            },
            "/v2/configs/c2/environments/e2/values": {
                "settingFormulas": [{"setting": {"settingId": 7}, "defaultValue": {"boolValue": False}}]
            },
        }
        rows, paths = self._run(mock_make_session, bodies, "setting_values")

        # A config only has values in its own product's environments — c1/e2 is not a valid pair.
        assert [path for path in paths if path.startswith("/v2/")] == [
            "/v2/configs/c1/environments/e1/values",
            "/v2/configs/c2/environments/e2/values",
        ]
        # The envelope carries the config and environment, so they're lifted onto each row to
        # complete the primary key.
        assert [(row["configId"], row["environmentId"], row["settingId"]) for row in rows] == [
            ("c1", "e1", 7),
            ("c2", "e2", 7),
        ]
        assert rows[0]["defaultValue"] == {"boolValue": True}

    @mock.patch.object(configcat, "make_tracked_session")
    def test_setting_values_non_object_body_fails_loud(self, mock_make_session: MagicMock) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v2"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v2/configs/c1/environments/e1/values": [],
        }
        with pytest.raises(ValueError, match="non-object values body"):
            self._run(mock_make_session, bodies, "setting_values")

    @mock.patch.object(configcat, "make_tracked_session")
    def test_v1_setting_values_use_v1_endpoint(self, mock_make_session: MagicMock) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v1"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v1/configs/c1/environments/e1/values": {"settingValues": [{"setting": {"settingId": 7}, "value": True}]},
        }

        rows, paths = self._run(mock_make_session, bodies, "setting_values")

        assert paths[-1] == "/v1/configs/c1/environments/e1/values"
        assert rows == [
            {
                "setting": {"settingId": 7},
                "settingId": 7,
                "value": True,
                "configId": "c1",
                "environmentId": "e1",
            }
        ]

    @parameterized.expand(
        [
            ("non_object_row", [{"productId": "p1"}, "bad"], "non-object row"),
            ("missing_id", [{"name": "missing id"}], "invalid productId"),
        ]
    )
    @mock.patch.object(configcat, "make_tracked_session")
    def test_malformed_fan_out_parent_fails_loud(
        self, _name: str, products: Any, error: str, mock_make_session: MagicMock
    ) -> None:
        with pytest.raises(ValueError, match=error):
            self._run(mock_make_session, {"/v1/products": products}, "configs")

    @mock.patch.object(configcat, "make_tracked_session")
    def test_malformed_setting_formula_fails_loud(self, mock_make_session: MagicMock) -> None:
        bodies = {
            "/v1/products": [{"productId": "p1"}],
            "/v1/products/p1/configs": [{"configId": "c1", "evaluationVersion": "v2"}],
            "/v1/products/p1/environments": [{"environmentId": "e1"}],
            "/v2/configs/c1/environments/e1/values": {"settingFormulas": [{"setting": {}}]},
        }

        with pytest.raises(ValueError, match="invalid settingId"):
            self._run(mock_make_session, bodies, "setting_values")

    @mock.patch.object(configcat, "make_tracked_session")
    def test_fan_out_list_endpoint_non_list_body_fails_loud(self, mock_make_session: MagicMock) -> None:
        with pytest.raises(ValueError, match="list response body"):
            self._run(mock_make_session, {"/v1/products": {"error": "nope"}}, "configs")


class TestCheckAccess:
    @staticmethod
    def _session_for(response: Any) -> MagicMock:
        session = MagicMock()
        if isinstance(response, Exception):
            session.get.side_effect = response
        else:
            session.get.return_value = response
        return session

    @parameterized.expand(
        [
            (200, True, 200, None),
            (401, False, 401, None),
            (403, False, 403, None),
            (500, False, 500, "ConfigCat returned HTTP 500"),
        ]
    )
    @mock.patch.object(configcat, "make_tracked_session")
    def test_status_mapping(
        self,
        status: int,
        ok: bool,
        expected_status: int,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = ok
        mock_make_session.return_value = self._session_for(response)
        assert check_access("user", "pass") == (expected_status, expected_message)

    @mock.patch.object(configcat, "make_tracked_session")
    def test_connection_error_maps_to_zero(self, mock_make_session: MagicMock) -> None:
        mock_make_session.return_value = self._session_for(requests.ConnectionError("boom"))
        status, message = check_access("user", "pass")
        assert status == 0
        assert message is not None and "boom" in message

    @parameterized.expand(
        [
            (200, True, None),
            (401, False, "Invalid ConfigCat Public API credentials"),
            (403, False, "Invalid ConfigCat Public API credentials"),
            (500, False, "ConfigCat returned HTTP 500"),
        ]
    )
    @mock.patch.object(configcat, "make_tracked_session")
    def test_validate_credentials(
        self,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
        mock_make_session: MagicMock,
    ) -> None:
        response = MagicMock()
        response.status_code = status
        response.ok = status < 400
        mock_make_session.return_value = self._session_for(response)
        assert validate_credentials("user", "pass") == (expected_valid, expected_message)


class TestConfigCatSourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession: MagicMock) -> None:
        _wire(MockSession.return_value, [_response([])])
        response = configcat_source(username="user", password="pass", endpoint=endpoint, team_id=1, job_id="j")
        assert response.name == endpoint
        assert response.primary_keys == CONFIGCAT_ENDPOINTS[endpoint].primary_keys
        # The list endpoints expose no stable timestamp, so we don't partition.
        assert response.partition_mode is None

    def test_primary_keys_are_per_endpoint(self) -> None:
        assert CONFIGCAT_ENDPOINTS["products"].primary_keys == ["productId"]
        assert CONFIGCAT_ENDPOINTS["organizations"].primary_keys == ["organizationId"]
        assert set(CONFIGCAT_ENDPOINTS) == set(ENDPOINTS)

    @parameterized.expand([(name,) for name, config in CONFIGCAT_ENDPOINTS.items() if config.parent is not None])
    def test_fan_out_keys_include_every_parent_in_the_path(self, endpoint: str) -> None:
        # A fan-out table aggregates rows from every parent, so a key missing a parent id seeds
        # duplicates that every later merge multi-matches.
        config = CONFIGCAT_ENDPOINTS[endpoint]
        for placeholder in ("configId", "environmentId"):
            if f"{{{placeholder}}}" in config.path:
                assert placeholder in config.primary_keys
