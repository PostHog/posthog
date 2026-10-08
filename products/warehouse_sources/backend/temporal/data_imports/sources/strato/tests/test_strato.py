from typing import Any, cast

from unittest.mock import Mock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato import (
    get_resource,
    strato_source,
    validate_credentials,
)


def _response(status_code: int = 200, json_body: Any = None, text: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_body if json_body is not None else {}
    response.text = text
    return response


class TestValidateCredentials:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.make_tracked_session")
    def test_valid_token(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(200, ["PONG"])

        result = validate_credentials("valid-token")

        assert result == (True, None)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.make_tracked_session")
    def test_invalid_token(self, mock_make_session) -> None:
        # Verbatim error body the live API returns for a bad token.
        mock_make_session.return_value.get.return_value = _response(
            401, {"type": "UNAUTHORIZED", "message": "The Token you are using is not valid", "errors": None}
        )

        valid, message = validate_credentials("bad-token")

        assert valid is False
        assert message is not None
        assert "Invalid STRATO API token" in message

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.make_tracked_session")
    def test_ip_restricted_token_points_to_the_restriction(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(406)

        valid, message = validate_credentials("token")

        assert valid is False
        assert message is not None
        assert "IP" in message

    @parameterized.expand([(500,), (503,)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.make_tracked_session")
    def test_other_error_uses_response_message(self, status_code: int, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response(status_code, {"message": "Internal error"})

        result = validate_credentials("token")

        assert result == (False, "Internal error")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.make_tracked_session")
    def test_network_error_returns_false(self, mock_make_session) -> None:
        from requests.exceptions import ConnectionError

        mock_make_session.return_value.get.side_effect = ConnectionError("boom")

        result = validate_credentials("token")

        assert result == (False, "boom")


class TestGetResource:
    def test_rejects_fanout_endpoint(self) -> None:
        try:
            get_resource("Snapshots")
            raise AssertionError("expected ValueError for fan-out endpoint")
        except ValueError as exc:
            assert "Snapshots" in str(exc)


class TestSecretScrubbing:
    def test_server_rows_drop_the_initial_root_password(self) -> None:
        data_map = get_resource("Servers")["data_map"]
        assert data_map is not None

        row = cast(dict[str, Any], data_map({"id": "srv1", "name": "web-1", "first_password": "hunter2"}))

        assert "first_password" not in row
        assert row["id"] == "srv1"
        assert row["name"] == "web-1"

    def test_user_rows_drop_the_api_key_but_keep_other_api_settings(self) -> None:
        data_map = get_resource("Users")["data_map"]
        assert data_map is not None

        row = cast(
            dict[str, Any],
            data_map({"id": "u1", "api": {"active": True, "key": "secret-token", "allowed_ips": ["1.2.3.4"]}}),
        )

        assert row["api"] == {"active": True, "allowed_ips": ["1.2.3.4"]}

    @parameterized.expand(
        [
            ("Servers", {"id": "srv1"}),
            ("Users", {"id": "u1"}),
            ("Users", {"id": "u1", "api": None}),
        ]
    )
    def test_rows_without_secret_fields_pass_through(self, endpoint: str, row: dict[str, Any]) -> None:
        data_map = get_resource(endpoint)["data_map"]
        assert data_map is not None

        assert data_map(dict(row)) == row


class TestStratoSourceTopLevel:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.rest_api_resource")
    def test_servers_builds_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        resp = strato_source(api_token="token", endpoint="Servers", team_id=1, job_id="job-1")

        assert resp.name == "Servers"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["creation_date"]


class TestStratoFanout:
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.strato.strato.build_dependent_resource")
    def test_client_sends_token_header_and_refuses_redirects(self, mock_build) -> None:
        mock_build.return_value = iter([])

        strato_source(api_token="secret-token", endpoint="Snapshots", team_id=1, job_id="job-1")

        _, kwargs = mock_build.call_args
        client_config = kwargs["client_config"]
        assert client_config["auth"] == {
            "type": "api_key",
            "name": "X-TOKEN",
            "api_key": "secret-token",
            "location": "header",
        }
        assert client_config["allow_redirects"] is False
        assert isinstance(client_config["paginator"], SinglePagePaginator)
        # STRATO list endpoints take no page-size param; sending one would be undocumented.
        assert kwargs["page_size_param"] is None
