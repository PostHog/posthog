import json

import pytest
from unittest.mock import MagicMock, patch

import requests

from products.enterprise.backend.vercel.client import ExperimentationResult, VercelAPIClient


class TestVercelAPIClient:
    class ErrorFactory:
        @staticmethod
        def http(status_code: int, text: str = "Error"):
            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_response.text = text
            mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
            return mock_response

        @staticmethod
        def timeout():
            return requests.Timeout("Request timed out")

        @staticmethod
        def network(msg: str = "Network error"):
            return requests.RequestException(msg)

        @staticmethod
        def json_error():
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "", 0)
            return mock_response

    @pytest.fixture
    def client(self):
        return VercelAPIClient("test_token")

    @pytest.fixture
    def test_ids(self):
        return {
            "integration_config_id": "config_123",
            "resource_id": "resource_456",
            "item_id": "item_789",
        }

    def assert_successful_request(self, mock_request, method, url, callable_func, args, expected_result, **kwargs):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_request.return_value = mock_response

        result = callable_func(*args)
        assert result == expected_result

        expected_kwargs = {"timeout": 30}
        expected_kwargs.update(kwargs)
        mock_request.assert_called_once_with(method, url, **expected_kwargs)

    def test_client_initialization(self):
        client = VercelAPIClient("my_token")
        assert client.bearer_token == "my_token"
        assert client.base_url == "https://api.vercel.com/v1"
        assert client.session.headers["Authorization"] == "Bearer my_token"
        assert client.session.headers["Content-Type"] == "application/json"
        assert client.timeout == 30

    def test_client_allows_empty_token_for_sso(self):
        client = VercelAPIClient("")
        assert client.bearer_token == ""
        assert "Authorization" not in client.session.headers

    def test_client_allows_none_token_for_sso(self):
        client = VercelAPIClient(None)
        assert client.bearer_token is None
        assert "Authorization" not in client.session.headers

    def test_client_allows_whitespace_token_for_sso(self):
        client = VercelAPIClient("   ")
        assert client.bearer_token == "   "
        assert "Authorization" not in client.session.headers

    def test_client_with_custom_timeout(self):
        client = VercelAPIClient("test_token", timeout=60)
        assert client.timeout == 60

    def test_client_with_custom_base_url(self):
        client = VercelAPIClient("test_token", base_url="https://staging.vercel.com/v1")
        assert client.base_url == "https://staging.vercel.com/v1"

    @patch("products.enterprise.backend.vercel.client.requests.Session.request")
    def test_create_experimentation_items(self, mock_request, client, test_ids):
        items = [{"id": "test", "slug": "test-slug", "origin": "test-origin"}]
        self.assert_successful_request(
            mock_request,
            "POST",
            f"{client.base_url}/installations/{test_ids['integration_config_id']}/resources/{test_ids['resource_id']}/experimentation/items",
            client.create_experimentation_items,
            (test_ids["integration_config_id"], test_ids["resource_id"], items),
            ExperimentationResult(success=True, item_count=1),
            json={"items": items},
        )

    @patch("products.enterprise.backend.vercel.client.requests.Session.request")
    def test_update_experimentation_item(self, mock_request, client, test_ids):
        data = {"slug": "updated-slug", "origin": "updated-origin"}
        self.assert_successful_request(
            mock_request,
            "PATCH",
            f"{client.base_url}/installations/{test_ids['integration_config_id']}/resources/{test_ids['resource_id']}/experimentation/items/{test_ids['item_id']}",
            client.update_experimentation_item,
            (test_ids["integration_config_id"], test_ids["resource_id"], test_ids["item_id"], data),
            ExperimentationResult(success=True, item_id=test_ids["item_id"]),
            json=data,
        )

    @patch("products.enterprise.backend.vercel.client.requests.Session.request")
    def test_delete_experimentation_item(self, mock_request, client, test_ids):
        self.assert_successful_request(
            mock_request,
            "DELETE",
            f"{client.base_url}/installations/{test_ids['integration_config_id']}/resources/{test_ids['resource_id']}/experimentation/items/{test_ids['item_id']}",
            client.delete_experimentation_item,
            (test_ids["integration_config_id"], test_ids["resource_id"], test_ids["item_id"]),
            ExperimentationResult(success=True, item_id=test_ids["item_id"]),
        )

    @pytest.mark.parametrize(
        "method_name,args_func,error_setup,expected_error,expected_status",
        [
            (
                "create_experimentation_items",
                lambda ids: (ids["integration_config_id"], ids["resource_id"], [{"test": "item"}]),
                ("return_value", lambda self: self.ErrorFactory.http(400, "Bad Request")),
                "HTTP error",
                400,
            ),
            (
                "update_experimentation_item",
                lambda ids: (ids["integration_config_id"], ids["resource_id"], ids["item_id"], {"test": "data"}),
                ("return_value", lambda self: self.ErrorFactory.http(404, "Not Found")),
                "HTTP error",
                404,
            ),
            (
                "delete_experimentation_item",
                lambda ids: (ids["integration_config_id"], ids["resource_id"], ids["item_id"]),
                ("return_value", lambda self: self.ErrorFactory.http(404, "Not Found")),
                "HTTP error",
                404,
            ),
            (
                "create_experimentation_items",
                lambda ids: (ids["integration_config_id"], ids["resource_id"], [{"test": "item"}]),
                ("side_effect", lambda self: self.ErrorFactory.timeout()),
                "Request timed out",
                None,
            ),
            (
                "create_experimentation_items",
                lambda ids: (ids["integration_config_id"], ids["resource_id"], [{"test": "item"}]),
                ("side_effect", lambda self: self.ErrorFactory.network("Connection failed")),
                "Network error",
                None,
            ),
        ],
    )
    @patch("products.enterprise.backend.vercel.client.requests.Session.request")
    def test_experimentation_method_errors(
        self, mock_request, client, test_ids, method_name, args_func, error_setup, expected_error, expected_status
    ):
        attr_name, error_factory = error_setup
        error_value = error_factory(self) if callable(error_factory) else error_factory
        setattr(mock_request, attr_name, error_value)

        method = getattr(client, method_name)
        args = args_func(test_ids)
        result = method(*args)

        assert not result.success
        assert result.error == expected_error
        if expected_status:
            assert result.status_code == expected_status
        assert result.error_detail is not None

    @pytest.mark.parametrize(
        "test_name,kwargs,expected_data",
        [
            (
                "minimal_params",
                {"code": "auth_code", "client_id": "client_123", "client_secret": "secret_456"},
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "authorization_code",
                },
            ),
            (
                "with_state",
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "state": "random_state",
                },
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "authorization_code",
                    "state": "random_state",
                },
            ),
            (
                "with_redirect_uri",
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "redirect_uri": "https://example.com/callback",
                },
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "authorization_code",
                    "redirect_uri": "https://example.com/callback",
                },
            ),
            (
                "custom_grant_type",
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "refresh_token",
                },
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "refresh_token",
                },
            ),
            (
                "all_params",
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "state": "random_state",
                    "redirect_uri": "https://example.com/callback",
                    "grant_type": "custom_grant",
                },
                {
                    "code": "auth_code",
                    "client_id": "client_123",
                    "client_secret": "secret_456",
                    "grant_type": "custom_grant",
                    "state": "random_state",
                    "redirect_uri": "https://example.com/callback",
                },
            ),
        ],
    )
    @patch("products.enterprise.backend.vercel.client.requests.Session.request")
    def test_sso_token_exchange_success(self, mock_request, test_name, kwargs, expected_data, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "test_access_token",
            "id_token": "test_id_token",
            "token_type": "Bearer",
        }
        mock_request.return_value = mock_response

        result = client.sso_token_exchange(**kwargs)

        assert result.access_token == "test_access_token"
        assert result.id_token == "test_id_token"
        assert result.token_type == "Bearer"
        from urllib.parse import urlencode

        mock_request.assert_called_once_with(
            "POST",
            f"{client.base_url}/integrations/sso/token",
            data=urlencode(expected_data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

    @pytest.mark.parametrize(
        "error_setup",
        [
            ("return_value", lambda self: self.ErrorFactory.http(400, "Bad Request")),
            ("side_effect", lambda self: self.ErrorFactory.timeout()),
            ("return_value", lambda self: self.ErrorFactory.json_error()),
        ],
    )
    @patch("products.enterprise.backend.vercel.client.requests.Session.request")
    def test_sso_token_exchange_errors(self, mock_request, client, error_setup):
        attr_name, error_factory = error_setup
        error_value = error_factory(self) if callable(error_factory) else error_factory
        setattr(mock_request, attr_name, error_value)

        result = client.sso_token_exchange("code", "client_id", "client_secret")
        assert result is None

    def test_create_experimentation_items_validates_items_not_empty(self, client):
        with pytest.raises(ValueError, match="items list cannot be empty"):
            client.create_experimentation_items("config_id", "resource_id", [])

    def test_update_experimentation_item_validates_parameters(self, client):
        with pytest.raises(ValueError):
            client.update_experimentation_item("config_id", "resource_id", "item_id", {})
