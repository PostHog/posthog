from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.smartengage import (
    get_resource,
    smartengage_source,
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


class TestSmartEngageTransport:
    @parameterized.expand(
        [
            ("valid_key", 200, [{"avatar_id": "1"}], (True, None)),
            ("empty_account", 200, [], (True, None)),
            ("unauthorized", 401, {"error": "unauthorized"}, (False, "Invalid SmartEngage API key")),
            ("forbidden", 403, {"error": "forbidden"}, (False, "Invalid SmartEngage API key")),
            ("server_error", 503, {}, (False, "SmartEngage API returned status 503")),
            # An error object served with a 200 must not validate as a working key.
            (
                "error_body_with_200",
                200,
                {"error": "invalid key"},
                (False, "SmartEngage API returned an unexpected response"),
            ),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.smartengage.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, _name, status, payload, expected, mock_session) -> None:
        response = Mock(status_code=status)
        response.json.return_value = payload
        mock_session.return_value.get.return_value = response

        assert validate_credentials(api_key="se_key") == expected

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.smartengage.make_tracked_session"
    )
    def test_validate_credentials_handles_request_exception(self, mock_session) -> None:
        mock_session.return_value.get.side_effect = requests.exceptions.RequestException("boom")
        is_valid, message = validate_credentials(api_key="se_key")
        assert is_valid is False
        assert message is not None and "SmartEngage request failed" in message

    def test_get_resource_avatars_is_unpaginated_root_array(self) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint="avatars"))
        assert resource["name"] == "avatars"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/avatars/list"
        # SmartEngage returns the full collection as a bare JSON array in one response.
        assert resource["endpoint"]["data_selector"] == "$"

    @parameterized.expand([("tags",), ("custom_fields",), ("sequences",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint=endpoint)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.smartengage.rest_api_resource")
    def test_avatars_source_response(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        response = smartengage_source(api_key="se_key", endpoint="avatars", team_id=1, job_id="job-1")

        assert response.name == "avatars"
        assert response.primary_keys == ["avatar_id"]
        # No SmartEngage table has a stable timestamp, so nothing is partitioned.
        assert response.partition_mode is None

    @parameterized.expand(
        [
            ("tags", "tag_id"),
            ("custom_fields", "custom_field_id"),
            ("sequences", "sequence_id"),
        ]
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_fanout_row_format_and_composite_key(self, endpoint, child_id_field, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("avatars", [{"avatar_id": "av_1"}]),
            _FakeDltResource(endpoint, [{child_id_field: "child_1", "_avatars_avatar_id": "av_1"}]),
        ]

        response = smartengage_source(api_key="se_key", endpoint=endpoint, team_id=1, job_id="job-1")

        rows = list(cast(Any, response.items()))
        assert rows == [{child_id_field: "child_1", "avatar_id": "av_1"}]
        # Child ids are only documented per avatar, so the avatar id must stay in the key —
        # dropping it seeds duplicate rows that every later merge multi-matches.
        assert response.primary_keys == ["avatar_id", child_id_field]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_fanout_binds_avatar_id_in_path_and_sends_no_page_size(self, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("avatars", []),
            _FakeDltResource("tags", []),
        ]

        smartengage_source(api_key="se_key", endpoint="tags", team_id=1, job_id="job-1")

        config = mock_rest_api_resources.call_args.args[0]
        parent, child = config["resources"]

        # The avatar_id resolve param can only be bound via a path placeholder (the framework
        # doesn't support resolve query params), so it must ride the path's query string.
        assert child["endpoint"]["path"] == "/tags/list?avatar_id={avatar_id}"
        assert child["endpoint"]["params"]["avatar_id"] == {
            "type": "resolve",
            "resource": "avatars",
            "field": "avatar_id",
        }
        assert child["include_from_parent"] == ["avatar_id"]

        # SmartEngage endpoints are unpaginated: no undocumented page-size param may be sent.
        assert "limit" not in parent["endpoint"]["params"]
        assert "limit" not in child["endpoint"]["params"]
