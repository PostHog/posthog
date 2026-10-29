from __future__ import annotations

import os
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

import httpx
from parameterized import parameterized

from products.marketing_analytics.backend.services.conversion_recommendations import RECOMMENDATION_PROMPT
from products.marketing_analytics.evals.recommendation_card_cases import recommendation_card_cases
from products.marketing_analytics.evals.recommendation_cards_runner import main, run_card_evaluation


def provider_response(
    source_ref: str = "action:4101", intent: str = "conversion", **overrides: object
) -> httpx.Response:
    payload = {
        "id": "msg_synthetic",
        "type": "message",
        "role": "assistant",
        "model": "effective-provider-model",
        "content": [
            {
                "type": "tool_use",
                "id": "tool_synthetic",
                "name": "recommendations",
                "input": {
                    "recommendations": [
                        {
                            "source_ref": source_ref,
                            "name": "Demo requested",
                            "intent": intent,
                            "reason": "A pre-sales lead.",
                            "questions": ["Which event establishes payment?"],
                        }
                    ],
                },
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 30},
        **overrides,
    }
    return httpx.Response(200, json=payload)


@override_settings(AI_GATEWAY_URL="https://synthetic-gateway.example.com/v1", AI_GATEWAY_API_KEY="synthetic-test-key")
class TestRecommendationCardsRunner(SimpleTestCase):
    def test_real_gateway_request_parser_and_action_identity(self) -> None:
        requests: list[httpx.Request] = []

        def transport(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return provider_response()

        with patch.object(httpx.HTTPTransport, "handle_request", autospec=True, side_effect=transport):
            report = run_card_evaluation(recommendation_card_cases()[:1], dry_run=False)

        assert report["status"] == "contract_passed"
        assert report["contract_passed"] is True
        assert report["semantic_review_status"] == "pending"
        assert len(requests) == 1
        request = requests[0]
        assert request.url.host == "synthetic-gateway.example.com"
        assert request.url.path == "/v1/messages"
        assert request.headers["x-posthog-privacy-mode"] == "true"
        body = json.loads(request.content)
        assert body["system"] == RECOMMENDATION_PROMPT
        assert body["tool_choice"] == {"type": "tool", "name": "recommendations"}
        assert body["tools"][0]["input_schema"]["properties"]["recommendations"]["maxItems"] == 3
        trial = report["trials"][0]
        assert trial["request_model"] == body["model"]
        assert trial["response_model"] == "effective-provider-model"
        assert trial["usage"]["output_tokens"] == 30
        recommendation = trial["results"].recommendations[0]
        assert recommendation.candidate.kind == "ActionsNode"
        assert recommendation.candidate.action_id == 4101
        assert recommendation.intent == "conversion"
        assert recommendation.amount_property is None

    def test_wrong_customer_intent_fails_contract_gate(self) -> None:
        with patch.object(httpx.HTTPTransport, "handle_request", return_value=provider_response(intent="customer")):
            report = run_card_evaluation(recommendation_card_cases()[:1], dry_run=False)

        assert report["status"] == "failed"
        assert report["contract_passed"] is False
        assert report["semantic_review_status"] == "pending"
        assert "action:4101: incorrect intent" in report["trials"][0]["failures"]

    @parameterized.expand(
        [
            ("billing", 402, "action:4101", "tool_use"),
            ("rate_limit", 429, "action:4101", "tool_use"),
            ("server_error", 500, "action:4101", "tool_use"),
            ("unknown_source", 200, "event:invented_payment", "tool_use"),
            ("truncated", 200, "action:4101", "max_tokens"),
        ]
    )
    def test_errors_stop_before_next_case_or_trial(
        self, _name: str, status: int, source_ref: str, stop_reason: str
    ) -> None:
        response = (
            provider_response(source_ref, stop_reason=stop_reason)
            if status == 200
            else httpx.Response(
                status,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "Synthetic provider failure"},
                },
            )
        )
        with patch.object(httpx.HTTPTransport, "handle_request", return_value=response) as transport:
            report = run_card_evaluation(recommendation_card_cases()[:2], trials=2, dry_run=False)

        assert report["status"] == "error"
        assert report["contract_passed"] is None
        assert report["completed_trials"] == 0
        assert len(report["trials"]) == 1
        assert transport.call_count == 1
        assert report["trials"][0]["status"] == "error"

    @override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
    def test_missing_go_gateway_fails_without_direct_provider_fallback(self) -> None:
        with patch.object(httpx.HTTPTransport, "handle_request") as transport:
            report = run_card_evaluation(recommendation_card_cases()[:1], dry_run=False)

        assert report["status"] == "error"
        assert report["completed_trials"] == 0
        transport.assert_not_called()

    def test_dry_run_exercises_all_cases_without_claiming_model_quality(self) -> None:
        cases = recommendation_card_cases()
        report = run_card_evaluation(cases)

        assert report["status"] == "dry_run_passed"
        assert report["completed_trials"] == len(cases)
        assert [trial["case"] for trial in report["trials"]] == [case.name for case in cases]
        assert report["contract_passed"] is None
        assert report["semantic_review_status"] == "not_applicable"
        assert {trial["response_model"] for trial in report["trials"]} == {"synthetic-transport-response"}

    def test_failed_checkpoint_keeps_completed_card_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            syncing = os.fsync
            checkpoint_writes = 0

            def fail_during_checkpoint(descriptor: int) -> None:
                nonlocal checkpoint_writes
                checkpoint_writes += 1
                if checkpoint_writes >= 4:
                    raise OSError("Synthetic storage failure")
                syncing(descriptor)

            with (
                patch("products.marketing_analytics.evals.recommendation_cards_runner._bootstrap"),
                patch.object(httpx.HTTPTransport, "handle_request", return_value=provider_response()) as transport,
                patch("products.marketing_analytics.evals.report_writer.os.fsync", side_effect=fail_during_checkpoint),
            ):
                with self.assertRaises(OSError):
                    main(["--live", "--case", "demo_is_a_lead", "--trials", "2", "--output", str(path)])
            report = json.loads(path.read_text())
            assert report["completed_trials"] == 1
            assert report["contract_passed"] is None
            assert report["trials"][0]["response"]["model"] == "effective-provider-model"
            assert transport.call_count == 1
            assert list(Path(directory).iterdir()) == [path]

    def test_interruption_preserves_completed_trial_in_report(self) -> None:
        with TemporaryDirectory() as directory:
            report_path = Path(directory) / "report.json"
            requests = 0

            def transport(_transport: httpx.HTTPTransport, _request: httpx.Request) -> httpx.Response:
                nonlocal requests
                checkpoint = json.loads(report_path.read_text())
                assert checkpoint["status"] == "running"
                assert checkpoint["completed_trials"] == requests
                requests += 1
                if requests == 2:
                    assert checkpoint["trials"][0]["response"]["model"] == "effective-provider-model"
                    assert checkpoint["trials"][0]["results"]["recommendations"][0]["reason"] == "A pre-sales lead."
                    raise KeyboardInterrupt
                return provider_response()

            with (
                patch("products.marketing_analytics.evals.recommendation_cards_runner._bootstrap"),
                patch.object(httpx.HTTPTransport, "handle_request", autospec=True, side_effect=transport),
            ):
                exit_code = main(["--live", "--case", "demo_is_a_lead", "--trials", "3", "--output", str(report_path)])

            report = json.loads(report_path.read_text())

        assert exit_code == 1
        assert requests == 2
        assert report["status"] == "interrupted"
        assert report["planned_trials"] == 3
        assert report["completed_trials"] == 1
        assert report["contract_passed"] is None
        assert report["semantic_review_status"] == "pending"
        assert report["trials"][0]["status"] == "passed"
        assert report["trials"][0]["response"]["model"] == "effective-provider-model"
        assert report["trials"][1]["status"] == "interrupted"
