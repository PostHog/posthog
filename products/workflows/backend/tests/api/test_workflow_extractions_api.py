from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import httpx
import anthropic
from parameterized import parameterized
from rest_framework import status

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.redis import TEST_clear_clients
from posthog.test.authentication_checks import covers_authentication
from posthog.token_bucket import Budget, TEST_reset_scripts

from products.workflows.backend.presentation.views.workflow_extractions import (
    WorkflowExtractionRequestSerializer,
    WorkflowExtractJWTAuthentication,
)

SECRET = "test-workflow-extract-jwt"
_BUILD_CLIENT = "products.workflows.backend.services.ai_extraction.build_ai_gateway_anthropic_client"
_BUDGET = "products.workflows.backend.services.ai_extraction.EXTRACTION_BUDGET"
_READ_TASK_REPORT = (
    "products.workflows.backend.presentation.views.workflow_extractions.get_workflow_task_run_final_message"
)
FIELDS = [
    {"name": "pr_url", "type": "string", "instruction": "The URL of the pull request the agent opened"},
    {"name": "files_changed", "type": "number", "instruction": "How many files the pull request changes"},
    {"name": "needs_review", "type": "boolean", "instruction": "True if the agent asks a person to review"},
]
AGENT_MESSAGE = "Opened https://github.com/example/repo/pull/7 touching 3 files. Please take a look."


def _token(
    team_id: int, audience: PosthogJwtAudience = PosthogJwtAudience.WORKFLOW_EXTRACT, hog_flow_id: str | None = None
) -> str:
    return encode_jwt(
        {"team_id": team_id, "hog_flow_id": hog_flow_id or str(uuid4())},
        timedelta(minutes=5),
        audience,
        signing_key=SECRET,
    )


def _tool_reply(values: Any) -> SimpleNamespace:
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="record_fields", input=values)])


def _fake_client(reply: Any = None, error: Exception | None = None) -> MagicMock:
    client = MagicMock()
    create = client.with_options.return_value.messages.create
    create.return_value = reply
    create.side_effect = error
    return client


def _status_error(status_code: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://gateway.example.com/v1/messages")
    return anthropic.APIStatusError("error", response=httpx.Response(status_code, request=request), body=None)


@override_settings(WORKFLOW_EXTRACT_JWT_SECRETS=[SECRET], WORKFLOW_CLASSIFY_JWT_SECRETS=[SECRET])
class TestWorkflowExtractionsAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.client.logout()
        self.url = f"/api/projects/{self.team.id}/workflow_extractions/"
        flag_patch = patch("posthoganalytics.feature_enabled", return_value=True)
        self.feature_flag = flag_patch.start()
        self.addCleanup(flag_patch.stop)
        TEST_clear_clients()
        TEST_reset_scripts()

    def _post(self, body: dict | None = None, token: str | None = None) -> Any:
        return self.client.post(
            self.url,
            {"context": {"agent_message": AGENT_MESSAGE}, "output_fields": FIELDS, **(body or {})},
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token or _token(self.team.id)}",
        )

    @covers_authentication(WorkflowExtractJWTAuthentication)
    def test_returns_one_typed_value_per_field(self) -> None:
        client = _fake_client(
            _tool_reply({"pr_url": "https://github.com/example/repo/pull/7", "files_changed": 3, "needs_review": True})
        )
        with patch(_BUILD_CLIENT, return_value=client) as build_client:
            response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {
            "values": {"pr_url": "https://github.com/example/repo/pull/7", "files_changed": 3, "needs_review": True}
        }
        assert build_client.call_args.kwargs["ai_product"] == "workflows"
        assert build_client.call_args.kwargs["team_id"] == self.team.id
        sent = client.with_options.return_value.messages.create.call_args.kwargs
        assert sent["extra_headers"] == {"X-PostHog-Privacy-Mode": "true"}
        # Each instruction rides in the tool schema; the earlier step's output stays in the user message as data.
        schema = sent["tools"][0]["input_schema"]
        assert schema["properties"]["needs_review"]["description"] == "True if the agent asks a person to review"
        assert schema["properties"]["files_changed"]["type"] == ["number", "null"]
        assert AGENT_MESSAGE in sent["messages"][0]["content"]
        assert AGENT_MESSAGE not in sent["system"]

    def test_a_value_the_text_does_not_hold_comes_back_empty(self) -> None:
        client = _fake_client(_tool_reply({"pr_url": None, "files_changed": None, "needs_review": False}))
        with patch(_BUILD_CLIENT, return_value=client):
            response = self._post()

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json() == {"values": {"pr_url": None, "files_changed": None, "needs_review": False}}

    @parameterized.expand(
        [
            ("flag_off", False, True),
            ("ai_processing_not_approved", True, False),
        ]
    )
    def test_refuses_without_the_feature_flag_or_ai_approval(self, _name: str, flag: bool, approved: bool) -> None:
        self.feature_flag.return_value = flag
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save()
        with patch(_BUILD_CLIENT) as build_client:
            response = self._post()

        assert response.status_code == status.HTTP_403_FORBIDDEN
        build_client.assert_not_called()

    @parameterized.expand(
        [
            ("rate_limited", _status_error(429), status.HTTP_503_SERVICE_UNAVAILABLE),
            ("gateway_down", _status_error(502), status.HTTP_503_SERVICE_UNAVAILABLE),
            (
                "timeout",
                anthropic.APITimeoutError(request=httpx.Request("POST", "https://gateway.example.com")),
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
            ("refused", _status_error(400), status.HTTP_422_UNPROCESSABLE_ENTITY),
        ]
    )
    def test_a_model_failure_maps_onto_a_status_the_step_can_retry_or_fail_on(
        self, _name: str, error: Exception, expected: int
    ) -> None:
        with patch(_BUILD_CLIENT, return_value=_fake_client(error=error)):
            response = self._post()

        assert response.status_code == expected

    @parameterized.expand(
        [
            ("spent_by_a_model_call", "model call", status.HTTP_429_TOO_MANY_REQUESTS, 1),
            ("refunded_when_no_gateway_ran", "no gateway", status.HTTP_200_OK, 2),
        ]
    )
    def test_charges_the_team_budget_only_for_model_calls(
        self, _name: str, first_attempt: str, second_status: int, model_clients_built: int
    ) -> None:
        reply = _tool_reply({"pr_url": None, "files_changed": 3, "needs_review": True})
        first = _fake_client(reply) if first_attempt == "model call" else ValueError("AI_GATEWAY_URL is not set")
        with (
            patch(_BUDGET, Budget(burst=1, per_hour=1)),
            patch(_BUILD_CLIENT, side_effect=[first, _fake_client(reply)]) as build_client,
        ):
            self._post()
            response = self._post()

        assert response.status_code == second_status, response.json()
        assert build_client.call_count == model_clients_built

    def test_reports_a_deployment_without_a_gateway(self) -> None:
        with patch(_BUILD_CLIENT, side_effect=ValueError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured")):
            response = self._post()

        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED

    @parameterized.expand(
        [
            (
                "no_tool_call",
                SimpleNamespace(content=[SimpleNamespace(type="text", text="pr_url is ...")]),
                "did not return the fields",
            ),
            ("missing_field", _tool_reply({"pr_url": "https://example.com", "files_changed": 3}), "needs_review"),
            (
                "text_for_a_number",
                _tool_reply({"pr_url": None, "files_changed": "three", "needs_review": True}),
                "files_changed",
            ),
            (
                "number_for_a_boolean",
                _tool_reply({"pr_url": None, "files_changed": 3, "needs_review": 1}),
                "needs_review",
            ),
            (
                "boolean_for_a_number",
                _tool_reply({"pr_url": None, "files_changed": True, "needs_review": True}),
                "files_changed",
            ),
            (
                "long_text_for_a_number",
                _tool_reply({"pr_url": None, "files_changed": "x" * 1001, "needs_review": True}),
                "files_changed that is not a number",
            ),
            (
                "text_over_the_cap",
                _tool_reply({"pr_url": "x" * 1001, "files_changed": 3, "needs_review": True}),
                "more than 1000 characters for pr_url",
            ),
        ]
    )
    def test_fails_the_step_rather_than_store_a_value_it_cannot_trust(
        self, _name: str, reply: Any, reason: str
    ) -> None:
        with patch(_BUILD_CLIENT, return_value=_fake_client(reply)):
            response = self._post()

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert reason in response.json()["detail"]

    def test_reads_the_full_report_of_an_ai_task_run_in_place_of_the_text(self) -> None:
        hog_flow_id, run_id = str(uuid4()), str(uuid4())
        report = "Fixed the parser. " * 400 + "Opened https://github.com/example/repo/pull/7"
        client = _fake_client(
            _tool_reply({"pr_url": "https://github.com/example/repo/pull/7", "files_changed": 3, "needs_review": True})
        )
        with patch(_READ_TASK_REPORT, return_value=report) as read_report, patch(_BUILD_CLIENT, return_value=client):
            response = self._post(
                {"context": None, "task_run_id": run_id}, token=_token(self.team.id, hog_flow_id=hog_flow_id)
            )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert read_report.call_args.kwargs == {
            "team_id": self.team.id,
            "hog_flow_id": UUID(hog_flow_id),
            "run_id": UUID(run_id),
        }
        assert report in client.with_options.return_value.messages.create.call_args.kwargs["messages"][0]["content"]

    @parameterized.expand(
        [
            ("not_from_this_workflow", None),
            ("longer_than_the_context_limit", "x" * 65_536),
        ]
    )
    def test_fails_the_step_when_the_ai_task_report_cannot_be_read(self, _name: str, report: str | None) -> None:
        with patch(_READ_TASK_REPORT, return_value=report), patch(_BUILD_CLIENT) as build_client:
            response = self._post({"task_run_id": str(uuid4())})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, response.json()
        build_client.assert_not_called()

    def test_rejects_invalid_fields_before_calling_the_model(self) -> None:
        with patch(_BUILD_CLIENT) as build_client:
            response = self._post({"output_fields": []})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        build_client.assert_not_called()

    def test_rejects_a_token_minted_for_another_workflow_action(self) -> None:
        response = self._post(token=_token(self.team.id, audience=PosthogJwtAudience.WORKFLOW_CLASSIFY))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestWorkflowExtractionRequestValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_fields", {"output_fields": []}),
            ("too_many_fields", {"output_fields": [{**FIELDS[0], "name": f"f{i}"} for i in range(21)]}),
            ("duplicate_names", {"output_fields": [FIELDS[0], FIELDS[0]]}),
            ("name_with_spaces", {"output_fields": [{**FIELDS[0], "name": "pr url"}]}),
            ("name_starting_with_a_digit", {"output_fields": [{**FIELDS[0], "name": "1st"}]}),
            ("name_with_surrounding_spaces", {"output_fields": [{**FIELDS[0], "name": " pr_url "}]}),
            ("name_with_a_trailing_newline", {"output_fields": [{**FIELDS[0], "name": "pr_url\n"}]}),
            ("unknown_type", {"output_fields": [{**FIELDS[0], "type": "date"}]}),
            ("blank_instruction", {"output_fields": [{**FIELDS[0], "instruction": " "}]}),
            ("long_instruction", {"output_fields": [{**FIELDS[0], "instruction": "x" * 501}]}),
            ("oversized_context", {"context": {"message": "x" * 65_536}}),
            ("no_text_and_no_task_run", {"context": None}),
            ("task_run_that_is_not_an_id", {"task_run_id": "latest"}),
        ]
    )
    def test_rejects_inputs_the_model_cannot_answer(self, _name: str, body: dict) -> None:
        serializer = WorkflowExtractionRequestSerializer(
            data={"context": {"message": "hi"}, "output_fields": FIELDS, **body}
        )

        assert not serializer.is_valid()
