import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from posthog.test.base import APIBaseTest
from unittest import mock

from openai import OpenAI
from rest_framework import status

from products.endpoints.backend.logic.ai_materialization_fix import (
    MaterializationFixResult,
    suggest_materialization_fix,
)
from products.endpoints.backend.tests.conftest import create_endpoint_with_version

# A variable inside an OR — rejected by the live materialization checks.
UNMATERIALIZABLE_QUERY = {
    "kind": "HogQLQuery",
    "query": "SELECT count() FROM events WHERE event = {variables.event_name} OR 1 = 1",
    "variables": {"v1": {"code_name": "event_name", "value": "$pageview"}},
}
# Keeps the placeholder and passes the checks (equivalence is the model's job, not the validator's).
PASSING_REWRITE = "SELECT count() FROM events WHERE event = {variables.event_name}"
DROPS_VARIABLE_REWRITE = "SELECT count() FROM events"


def _reply(suggested_query, explanation="Rewrote the query."):
    return json.dumps({"suggested_query": suggested_query, "explanation": explanation})


class FakeLLMClient:
    """Scripted gateway client: returns each canned response text in order."""

    def __init__(self, responses):
        self.calls: list[dict[str, Any]] = []
        self._responses = list(responses)

        def create(**kwargs):
            self.calls.append(kwargs)
            content = self._responses.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    def with_options(self, **kwargs):
        return self


def _suggest(client: FakeLLMClient, **kwargs: Any) -> MaterializationFixResult:
    kwargs.setdefault("team_id", 1)
    kwargs.setdefault("query", UNMATERIALIZABLE_QUERY)
    return suggest_materialization_fix(client=cast(OpenAI, client), **kwargs)


class TestSuggestMaterializationFixEngine:
    def test_valid_suggestion_first_attempt(self):
        client = FakeLLMClient([_reply(PASSING_REWRITE)])
        result = _suggest(client)
        assert result.status == "ok"
        assert result.suggested_query == PASSING_REWRITE
        assert result.attempts == 1
        assert "OR conditions" in result.original_reason

    def test_repairs_after_validation_failure(self):
        client = FakeLLMClient([_reply(DROPS_VARIABLE_REWRITE), _reply(PASSING_REWRITE)])
        result = _suggest(client)
        assert result.status == "ok"
        assert result.suggested_query == PASSING_REWRITE
        assert result.attempts == 2

        assert "event_name" in client.calls[1]["messages"][1]["content"]

    def test_model_declines_returns_cannot_fix(self):
        client = FakeLLMClient([_reply(None, explanation="No equivalent rewrite exists.")])
        result = _suggest(client)
        assert result.status == "cannot_fix"
        assert result.suggested_query is None
        assert result.explanation == "No equivalent rewrite exists."

    def test_exhausted_attempts_returns_invalid_with_last_attempt(self):
        client = FakeLLMClient([_reply(DROPS_VARIABLE_REWRITE)] * 3)
        result = _suggest(client)
        assert result.status == "invalid"
        assert result.suggested_query == DROPS_VARIABLE_REWRITE
        assert result.error is not None
        assert result.attempts == 3

    def test_unparseable_responses_return_model_error(self):
        client = FakeLLMClient(["not json"] * 3)
        result = _suggest(client)
        assert result.status == "model_error"
        assert result.suggested_query is None

    def test_parseable_but_malformed_replies_exhaust_to_model_error(self):
        # Parseable JSON that never yields a usable suggestion is a model failure, not an
        # "invalid suggestion" — there is no last attempt to hand the user.
        client = FakeLLMClient([json.dumps({"explanation": "here you go"})] * 3)
        result = _suggest(client)
        assert result.status == "model_error"
        assert result.suggested_query is None
        assert result.attempts == 3
        assert result.error == "The AI model did not return a usable suggestion."

    def test_rejects_already_materializable_query(self):
        materializable = {**UNMATERIALIZABLE_QUERY, "query": PASSING_REWRITE}
        with pytest.raises(ValueError):
            _suggest(FakeLLMClient([]), query=materializable)

    def test_missing_suggested_query_key_is_retried_not_cannot_fix(self):
        # Parseable JSON without the key is a malformed reply, not the explicit-null "no fix" signal
        client = FakeLLMClient(
            [json.dumps({"explanation": "here you go", "query": PASSING_REWRITE}), _reply(PASSING_REWRITE)]
        )
        result = _suggest(client)
        assert result.status == "ok"
        assert result.attempts == 2
        assert "suggested_query" in client.calls[1]["messages"][1]["content"]

    def test_rewrite_changing_output_columns_is_rejected(self):
        original_columns = [{"name": "count()", "type": "integer"}]
        renamed_column = "SELECT count() AS cnt FROM events WHERE event = {variables.event_name}"
        client = FakeLLMClient([_reply(renamed_column), _reply(PASSING_REWRITE)])
        with mock.patch(
            "products.endpoints.backend.logic.ai_materialization_fix.EndpointVersion.extract_columns",
            side_effect=[[{"name": "cnt", "type": "integer"}], original_columns],
        ):
            result = _suggest(client, original_columns=original_columns)
        assert result.status == "ok"
        assert result.suggested_query == PASSING_REWRITE
        assert result.attempts == 2
        assert "same output columns" in client.calls[1]["messages"][1]["content"]

    def test_rewrite_that_does_not_compile_is_rejected(self):
        original_columns = [{"name": "count()", "type": "integer"}]
        client = FakeLLMClient([_reply(PASSING_REWRITE), _reply(PASSING_REWRITE)])
        with mock.patch(
            "products.endpoints.backend.logic.ai_materialization_fix.EndpointVersion.extract_columns",
            side_effect=[Exception("Unknown column 'foo'"), original_columns],
        ):
            result = _suggest(client, original_columns=original_columns)
        assert result.status == "ok"
        assert result.attempts == 2
        assert "failed to compile" in client.calls[1]["messages"][1]["content"]

    def test_stops_retrying_past_time_budget(self):
        client = FakeLLMClient([_reply(DROPS_VARIABLE_REWRITE)] * 3)
        with mock.patch(
            "products.endpoints.backend.logic.ai_materialization_fix.time.monotonic",
            side_effect=[0.0, 1000.0, 2000.0, 3000.0],
        ):
            result = _suggest(client)
        assert result.status == "invalid"
        assert result.attempts == 1
        assert len(client.calls) == 1


class TestMaterializationSuggestionAPI(APIBaseTest):
    def _post_suggestion(self, name):
        return self.client.post(
            f"/api/projects/{self.team.id}/endpoints/{name}/materialization_suggestion/",
            {},
            format="json",
        )

    def _create_endpoint(self, name, query):
        return create_endpoint_with_version(name=name, team=self.team, query=query, created_by=self.user)

    def setUp(self):
        super().setUp()
        # The suggestion action is behind a rollout flag; treat it as on for these tests
        flag_patcher = mock.patch(
            "products.endpoints.backend.presentation.views.api.materialization_fix_enabled",
            return_value=True,
        )
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def test_requires_rollout_flag(self):
        self._create_endpoint("blocked-endpoint", UNMATERIALIZABLE_QUERY)
        with mock.patch(
            "products.endpoints.backend.presentation.views.api.materialization_fix_enabled",
            return_value=False,
        ):
            response = self._post_suggestion("blocked-endpoint")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_requires_ai_data_processing_approval(self):
        self._create_endpoint("blocked-endpoint", UNMATERIALIZABLE_QUERY)
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        response = self._post_suggestion("blocked-endpoint")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_rejects_insight_queries(self):
        self._create_endpoint(
            "insight-endpoint", {"kind": "TrendsQuery", "series": [], "compareFilter": {"compare": True}}
        )
        response = self._post_suggestion("insight-endpoint")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "SQL endpoints" in response.json()["error"]

    def test_rejects_already_materializable_query(self):
        self._create_endpoint("fine-endpoint", {**UNMATERIALIZABLE_QUERY, "query": PASSING_REWRITE})
        response = self._post_suggestion("fine-endpoint")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "already" in response.json()["error"]

    def test_returns_suggestion_payload(self):
        self._create_endpoint("blocked-endpoint", UNMATERIALIZABLE_QUERY)
        fix_result = MaterializationFixResult(
            status="ok",
            suggested_query=PASSING_REWRITE,
            explanation="Removed the OR by lifting the variable into a column.",
            attempts=1,
            error=None,
            original_reason="Variables in OR conditions are not supported for materialization",
        )
        with mock.patch(
            "products.endpoints.backend.presentation.views.api.suggest_materialization_fix",
            return_value=fix_result,
        ) as suggest_mock:
            response = self._post_suggestion("blocked-endpoint")
        assert response.status_code == status.HTTP_200_OK
        assert suggest_mock.call_args.kwargs["query"] == UNMATERIALIZABLE_QUERY
        data = response.json()
        assert data["suggestion_status"] == "ok"
        assert data["suggested_query"] == PASSING_REWRITE
        assert data["explanation"] == "Removed the OR by lifting the variable into a column."
        assert data["original_reason"] == "Variables in OR conditions are not supported for materialization"

    def test_gateway_unreachable_returns_503(self):
        from openai import APIConnectionError

        self._create_endpoint("blocked-endpoint", UNMATERIALIZABLE_QUERY)
        with mock.patch(
            "products.endpoints.backend.presentation.views.api.suggest_materialization_fix",
            side_effect=APIConnectionError(request=mock.Mock()),
        ):
            response = self._post_suggestion("blocked-endpoint")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    def test_materialization_conditions_returns_live_source(self):
        response = self.client.get(f"/api/projects/{self.team.id}/endpoints/materialization_conditions/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert "def analyze_variables_for_materialization" in data["conditions_source"]
        assert "def can_materialize_query" in data["conditions_source"]
        assert "{variables.<code_name>}" in data["rewrite_contract"]
