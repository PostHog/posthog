import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import AsyncMock, MagicMock, patch

from rest_framework import exceptions, status

from posthog.clickhouse.client import sync_execute

from products.logs.backend.explain import (
    LogExplanationResponse,
    explain_log_with_openai,
    fetch_log_by_uuid,
    load_prompt_template,
)


@pytest.fixture
def valid_explanation_json():
    return json.dumps(
        {
            "headline": "PostgreSQL connection pool exhausted",
            "severity_assessment": "error",
            "impact_summary": "User authentication likely failing for api-gateway service",
            "probable_causes": [
                {
                    "hypothesis": "Connection pool size too small for current load",
                    "confidence": "high",
                    "reasoning": "Pool exhausted message indicates max connections reached",
                }
            ],
            "immediate_actions": [
                {
                    "action": "Check database connection count",
                    "priority": "now",
                    "why": "Need to confirm pool exhaustion vs database issue",
                }
            ],
            "technical_explanation": "- Connection pool exhausted at `max_connections=100`\n- Service: `api-gateway`",
            "key_fields": [
                {
                    "field": "error_code",
                    "value": "POOL_EXHAUSTED",
                    "significance": "Indicates connection limit hit",
                    "attribute_type": "log",
                }
            ],
        }
    )


@pytest.fixture
def sample_log_data():
    return {
        "uuid": "019b2664-8f9a-7091-a2e5-9795bce2f13f",
        "timestamp": datetime(2025, 12, 16, 9, 1, 22, 139425, tzinfo=ZoneInfo("UTC")),
        "body": "PostgreSQL connection pool exhausted",
        "attributes": {"error_code": "POOL_EXHAUSTED"},
        "severity_text": "error",
        "service_name": "api-gateway",
        "resource_attributes": {"k8s.pod.name": "api-gateway-abc123"},
        "trace_id": "abc123",
        "span_id": "def456",
        "event_name": "",
    }


class TestLoadPromptTemplate:
    def test_loads_system_prompt(self):
        result = load_prompt_template("explain_system.djt", {})
        assert "Site Reliability Engineer" in result
        assert "root cause analysis" in result.lower()

    def test_loads_user_prompt_with_context(self, sample_log_data):
        result = load_prompt_template("explain_user.djt", sample_log_data)
        assert "api-gateway" in result
        assert "PostgreSQL connection pool exhausted" in result


class TestExplainLogWithOpenAI:
    @pytest.mark.asyncio
    async def test_successful_explanation(self, valid_explanation_json, sample_log_data):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_explanation_json

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            result = await explain_log_with_openai(sample_log_data, team_id=1)

            assert isinstance(result, LogExplanationResponse)
            assert result.headline == "PostgreSQL connection pool exhausted"
            assert result.severity_assessment == "error"
            assert len(result.probable_causes) == 1
            assert result.probable_causes[0].confidence == "high"

    @pytest.mark.asyncio
    async def test_empty_response_raises_validation_error(self, sample_log_data):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            with pytest.raises(exceptions.ValidationError, match="empty response"):
                await explain_log_with_openai(sample_log_data, team_id=1)

    @pytest.mark.asyncio
    async def test_api_error_raises_api_exception(self, sample_log_data):
        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))

            with pytest.raises(exceptions.APIException, match="Failed to generate log explanation"):
                await explain_log_with_openai(sample_log_data, team_id=1)

    @pytest.mark.asyncio
    async def test_uses_json_schema_format(self, valid_explanation_json, sample_log_data):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_explanation_json

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            await explain_log_with_openai(sample_log_data, team_id=1)

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["response_format"]["type"] == "json_schema"
            assert call_kwargs["response_format"]["json_schema"]["strict"] is True

    @pytest.mark.asyncio
    async def test_uses_correct_model(self, valid_explanation_json, sample_log_data):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = valid_explanation_json

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            await explain_log_with_openai(sample_log_data, team_id=1)

            call_kwargs = mock_client.chat.completions.create.call_args[1]
            assert call_kwargs["model"] == "gpt-4.1"


class TestFetchLogByUuid(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)

    def test_returns_none_for_nonexistent_uuid(self):
        result = fetch_log_by_uuid(self.team.id, "nonexistent-uuid", "2025-12-16T09:01:22")
        assert result is None

    def test_returns_log_data_for_existing_uuid(self):
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = self.team.id
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        result = fetch_log_by_uuid(self.team.id, log_item["uuid"], log_item["timestamp"])
        assert result is not None
        assert result["uuid"] == log_item["uuid"]
        assert result["service_name"] == log_item["service_name"]
        assert "body" in result
        assert "attributes" in result
        assert "resource_attributes" in result

    def test_respects_team_isolation(self):
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = 99999
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        result = fetch_log_by_uuid(self.team.id, log_item["uuid"], log_item["timestamp"])
        assert result is None


class TestLogExplainAPI(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs_schema.sql")) as f:
            schema_sql = f.read()
        for sql in schema_sql.split(";"):
            if not sql.strip():
                continue
            sync_execute(sql)

    def _get_valid_explanation_response(self):
        return json.dumps(
            {
                "headline": "Test headline",
                "severity_assessment": "warning",
                "impact_summary": "Test impact",
                "probable_causes": [
                    {"hypothesis": "Test cause", "confidence": "medium", "reasoning": "Test reasoning"}
                ],
                "immediate_actions": [{"action": "Test action", "priority": "soon", "why": "Test why"}],
                "technical_explanation": "Test explanation",
                "key_fields": [
                    {"field": "test_field", "value": "test_value", "significance": "Test sig", "attribute_type": "log"}
                ],
            }
        )

    def test_requires_authentication(self):
        self.client.logout()
        response = self.client.post(
            f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
            {"uuid": "test-uuid", "timestamp": "2025-12-16T09:01:22Z"},
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_requires_ai_data_processing_approval(self):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
            {"uuid": "test-uuid", "timestamp": "2025-12-16T09:01:22Z"},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "AI data processing" in response.json()["detail"]

    def test_returns_404_for_nonexistent_log(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
            {"uuid": "nonexistent-uuid", "timestamp": "2025-12-16T09:01:22Z"},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_400_for_missing_uuid(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        response = self.client.post(
            f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
            {},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_successful_explanation(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = self.team.id
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self._get_valid_explanation_response()

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            response = self.client.post(
                f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
                {"uuid": log_item["uuid"], "timestamp": log_item["timestamp"]},
            )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["headline"] == "Test headline"
        assert data["severity_assessment"] == "warning"
        assert len(data["probable_causes"]) == 1
        assert len(data["immediate_actions"]) == 1

    def test_caches_result(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = self.team.id
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self._get_valid_explanation_response()

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            # First request
            response1 = self.client.post(
                f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
                {"uuid": log_item["uuid"], "timestamp": log_item["timestamp"]},
            )
            assert response1.status_code == status.HTTP_200_OK
            assert mock_client.chat.completions.create.call_count == 1

            # Second request should use cache
            response2 = self.client.post(
                f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
                {"uuid": log_item["uuid"], "timestamp": log_item["timestamp"]},
            )
            assert response2.status_code == status.HTTP_200_OK
            assert mock_client.chat.completions.create.call_count == 1  # Still 1, used cache

    def test_force_refresh_bypasses_cache(self):
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            line = f.readline()
            log_item = json.loads(line)
            log_item["team_id"] = self.team.id
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {json.dumps(log_item)}
            """)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self._get_valid_explanation_response()

        with patch("products.logs.backend.explain.AsyncOpenAI") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

            # First request
            response1 = self.client.post(
                f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
                {"uuid": log_item["uuid"], "timestamp": log_item["timestamp"]},
            )
            assert response1.status_code == status.HTTP_200_OK

            # Second request with force_refresh
            response2 = self.client.post(
                f"/api/environments/{self.team.id}/logs/explainLogWithAI/",
                {"uuid": log_item["uuid"], "timestamp": log_item["timestamp"], "force_refresh": True},
            )
            assert response2.status_code == status.HTTP_200_OK
            assert mock_client.chat.completions.create.call_count == 2  # Called again
