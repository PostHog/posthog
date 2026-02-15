import json

import pytest
from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.streamlit_apps.backend.services.bridge import (
    BRIDGE_TOKEN_SALT,
    execute_bridge_query,
    generate_bridge_token,
    validate_bridge_token,
)


class TestBridgeToken(BaseTest):
    def test_generate_and_validate_roundtrip(self):
        token = generate_bridge_token(team_id=42, app_id="abc-123")
        claims = validate_bridge_token(token)
        assert claims.team_id == 42
        assert claims.app_id == "abc-123"

    def test_expired_token_raises(self):
        from django.core.signing import TimestampSigner

        signer = TimestampSigner(salt=BRIDGE_TOKEN_SALT)
        payload = json.dumps({"team_id": 1, "app_id": "x"}, separators=(",", ":"))
        token = signer.sign(payload)

        with pytest.raises(Exception):
            validate_bridge_token(token, max_age=0)

    def test_tampered_token_raises(self):
        from django.core.signing import BadSignature

        token = generate_bridge_token(team_id=1, app_id="x")
        tampered = token + "TAMPERED"
        with pytest.raises(BadSignature):
            validate_bridge_token(tampered)

    def test_garbage_token_raises(self):
        from django.core.signing import BadSignature

        with pytest.raises(BadSignature):
            validate_bridge_token("not-a-real-token")

    @parameterized.expand(
        [
            ("simple_ids", 1, "abc"),
            ("large_team_id", 999999, "def-456-ghi"),
            ("uuid_app_id", 7, "550e8400-e29b-41d4-a716-446655440000"),
        ]
    )
    def test_various_payloads(self, _name, team_id, app_id):
        token = generate_bridge_token(team_id=team_id, app_id=app_id)
        claims = validate_bridge_token(token)
        assert claims.team_id == team_id
        assert claims.app_id == app_id


class TestExecuteBridgeQuery(BaseTest):
    @patch("products.streamlit_apps.backend.services.bridge.execute_hogql_query")
    def test_returns_cleaned_response(self, mock_execute):
        response = MagicMock()
        response.model_dump.return_value = {
            "results": [[1, "hello"]],
            "columns": ["id", "name"],
            "clickhouse": "SELECT ...",
            "hogql": "SELECT ...",
            "timings": {"total": 0.1},
            "modifiers": {},
            "types": [["Int64"], ["String"]],
        }
        mock_execute.return_value = response

        result = execute_bridge_query(query="SELECT 1", team_id=self.team.id)

        assert "results" in result
        assert "columns" in result
        assert "clickhouse" not in result
        assert "hogql" not in result
        assert "timings" not in result
        assert "modifiers" not in result

    @patch("products.streamlit_apps.backend.services.bridge.execute_hogql_query")
    def test_passes_query_and_team(self, mock_execute):
        response = MagicMock()
        response.model_dump.return_value = {"results": [], "columns": []}
        mock_execute.return_value = response

        execute_bridge_query(query="SELECT event FROM events", team_id=self.team.id)

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args
        assert call_kwargs.kwargs["query"] == "SELECT event FROM events"
        assert call_kwargs.kwargs["team"].id == self.team.id

    def test_invalid_team_raises(self):
        with pytest.raises(Exception):
            execute_bridge_query(query="SELECT 1", team_id=999999)


class TestStreamlitBridgeView(APIBaseTest):
    def _url(self):
        return "/api/streamlit_bridge/query/"

    def _token(self):
        return generate_bridge_token(team_id=self.team.id, app_id="test-app")

    @parameterized.expand(
        [
            ("missing_header", {}, None, 401, "Missing or invalid Authorization header"),
            ("bad_prefix", {}, "Token abc", 401, "Missing or invalid Authorization header"),
        ]
    )
    def test_auth_failures(self, _name, body, auth_value, expected_status, expected_error):
        headers = {}
        if auth_value:
            headers["HTTP_AUTHORIZATION"] = auth_value
        response = self.client.post(
            self._url(),
            data=json.dumps(body),
            content_type="application/json",
            **headers,
        )
        assert response.status_code == expected_status
        assert expected_error in response.json()["error"]

    def test_expired_token(self):
        token = self._token()
        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT 1"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}TAMPERED",
        )
        assert response.status_code == 401

    def test_invalid_json_body(self):
        response = self.client.post(
            self._url(),
            data="not json",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._token()}",
        )
        assert response.status_code == 400
        assert "Invalid JSON" in response.json()["error"]

    @parameterized.expand(
        [
            ("missing_query", {}),
            ("empty_query", {"query": ""}),
            ("query_is_number", {"query": 123}),
            ("query_whitespace_only", {"query": "   "}),
        ]
    )
    def test_invalid_query_field(self, _name, body):
        response = self.client.post(
            self._url(),
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._token()}",
        )
        assert response.status_code == 400
        assert "query" in response.json()["error"].lower()

    @patch("products.streamlit_apps.backend.services.bridge.execute_hogql_query")
    def test_successful_query(self, mock_execute):
        response_obj = MagicMock()
        response_obj.model_dump.return_value = {
            "results": [[1, "test"]],
            "columns": ["id", "name"],
            "clickhouse": "SELECT ...",
            "hogql": "SELECT ...",
            "timings": {},
            "modifiers": {},
        }
        mock_execute.return_value = response_obj

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELECT id, name FROM persons"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._token()}",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == [[1, "test"]]
        assert data["columns"] == ["id", "name"]
        assert "clickhouse" not in data

    @patch("products.streamlit_apps.backend.services.bridge.execute_hogql_query")
    def test_query_execution_error_returns_400(self, mock_execute):
        mock_execute.side_effect = Exception("Parse error near 'SELCT'")

        response = self.client.post(
            self._url(),
            data=json.dumps({"query": "SELCT bad"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self._token()}",
        )
        assert response.status_code == 400
        assert "error" in response.json()
