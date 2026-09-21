import json
from copy import deepcopy

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.egress.firecrawl import FirecrawlEgressBudgetExhausted, FirecrawlNotConfigured
from posthog.egress.firecrawl.client import FirecrawlScrape, FirecrawlSearch, FirecrawlSearchResult
from posthog.egress.limiter.policies import Priority, resolve_policy
from posthog.egress.observability.observability import scope_fingerprint

from products.growth.backend.enrichment.jev import (
    DEFAULT_JEV_OUTPUT_FIELDS,
    DEFAULT_JEV_PROMPT,
    JevConfigError,
    JevRequestError,
    JevResearchUnavailable,
    JevResponseError,
    JevTransientError,
    classify_with_jev,
)

_KEY = "synthetic_typesafe_token"
_TOOLS = "products.growth.backend.enrichment.tools"


def _response(choices: tuple[str, str] = ("no_support", "positive"), status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(
        {
            "model": "jev-synthetic-version",
            "answers": {
                key: {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.0,
                    "probabilities": {"positive": 0.34, "no_support": 0.33, "insufficient": 0.33},
                }
                for key, choice in zip(("internal_ai_development", "owned_ai_product"), choices)
            },
            "usage": {"input_tokens": 123, "output_tokens": 6},
        }
    ).encode()
    return response


class TestJevClassification(SimpleTestCase):
    def setUp(self) -> None:
        self.limiter = MagicMock()
        self.limiter.consume_sync.return_value = True
        self.gate = patch("posthog.egress.typesafe.limiter.get_outbound_rate_limiter", return_value=self.limiter)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    @parameterized.expand(
        [
            ("positive", "positive", True),
            ("positive", "no_support", True),
            ("positive", "insufficient", True),
            ("no_support", "positive", True),
            ("no_support", "no_support", False),
            ("no_support", "insufficient", "unknown"),
            ("insufficient", "positive", True),
            ("insufficient", "no_support", "unknown"),
            ("insufficient", "insufficient", "unknown"),
        ]
    )
    def test_two_editable_questions_determine_the_boolean_without_a_confidence_gate(
        self, development: str, product: str, expected: bool | str
    ) -> None:
        fields = deepcopy(DEFAULT_JEV_OUTPUT_FIELDS)
        fields[1]["description"] = "Does the team use an AI coding assistant?"
        with patch("requests.request", return_value=_response((development, product))) as request:
            result = classify_with_jev(
                model="jev-latest",
                prompt_text="Use these revised classification instructions.",
                output_fields=fields,
                inputs={"description": "Synthetic inventory software."},
                signup_domain="inventory.example.com",
                website_url=None,
                api_key=_KEY,
                tools_enabled=False,
            )

        assert result.output["ai_pilled"] == expected
        assert result.model == "jev-synthetic-version"
        assert result.usage.input_tokens == 123
        assert result.answers["owned_ai_product"].confidence == 0.0
        assert result.pages == ()
        assert result.tool_calls == ()
        assert "reasoning" not in result.output
        request.assert_called_once()
        questions = request.call_args.kwargs["json"]["questions"]
        assert set(questions) == {"internal_ai_development", "owned_ai_product"}
        assert questions["internal_ai_development"]["instructions"] == (
            "Use these revised classification instructions.\n\nDoes the team use an AI coding assistant?"
        )

    def test_transport_bounds_requests_and_keeps_the_key_out_of_metrics(self) -> None:
        fingerprint = scope_fingerprint(_KEY)
        labels = {
            "credential": fingerprint,
            "method": "POST",
            "endpoint": "/v1/systemone",
            "status_code": "200",
            "source": "growth_ai_enrichment",
        }
        before = REGISTRY.get_sample_value("typesafe_api_requests_total", labels) or 0
        with patch("requests.request", return_value=_response()) as request:
            classify_with_jev(
                model="jev-latest",
                prompt_text=DEFAULT_JEV_PROMPT,
                output_fields=DEFAULT_JEV_OUTPUT_FIELDS,
                inputs={"description": "Synthetic stocktaking assistant."},
                signup_domain=None,
                website_url=None,
                api_key=_KEY,
                tools_enabled=False,
            )
        assert request.call_args.args == ("POST", "https://api.typesafe.ai/v1/systemone")
        assert request.call_args.kwargs["headers"]["Authorization"] == f"Bearer {_KEY}"
        assert request.call_args.kwargs["timeout"] == (5.0, 30.0)
        assert request.call_args.kwargs["allow_redirects"] is False
        self.limiter.consume_sync.assert_called_once_with(
            f"typesafe:credential:{fingerprint}", priority=Priority.BATCH, source="growth_ai_enrichment"
        )
        assert REGISTRY.get_sample_value("typesafe_api_requests_total", labels) == before + 1
        assert REGISTRY.get_sample_value("typesafe_api_requests_total", {**labels, "credential": _KEY}) is None

    @override_settings(TYPESAFE_EGRESS_PER_MINUTE_BUDGET=17, TYPESAFE_EGRESS_HOURLY_BUDGET=91)
    def test_operator_budget_reads_the_configured_settings(self) -> None:
        assert resolve_policy("typesafe:credential:synthetic").limits == ((17, 60.0), (91, 3600.0))

    @parameterized.expand(
        [
            (408, JevTransientError),
            (429, JevTransientError),
            (500, JevTransientError),
            (529, JevTransientError),
            (401, JevRequestError),
            (422, JevRequestError),
            (302, JevRequestError),
        ]
    )
    def test_failed_requests_never_become_negative_labels(self, status: int, error: type[Exception]) -> None:
        with patch("requests.request", return_value=_response(status=status)) as request:
            with self.assertRaises(error):
                classify_with_jev(
                    model="jev-latest",
                    prompt_text=DEFAULT_JEV_PROMPT,
                    output_fields=DEFAULT_JEV_OUTPUT_FIELDS,
                    inputs={"description": "Synthetic stocktaking assistant."},
                    signup_domain=None,
                    website_url=None,
                    api_key=_KEY,
                    tools_enabled=False,
                )
        request.assert_called_once()

    @parameterized.expand([("timeout",), ("budget",)])
    def test_transient_failures_defer_without_an_immediate_retry(self, failure: str) -> None:
        self.limiter.consume_sync.return_value = failure != "budget"
        with patch("requests.request", side_effect=requests.Timeout("synthetic timeout")) as request:
            with self.assertRaises(JevTransientError):
                classify_with_jev(
                    model="jev-latest",
                    prompt_text=DEFAULT_JEV_PROMPT,
                    output_fields=DEFAULT_JEV_OUTPUT_FIELDS,
                    inputs={"description": "Synthetic stocktaking assistant."},
                    signup_domain=None,
                    website_url=None,
                    api_key=_KEY,
                    tools_enabled=False,
                )
        assert request.call_count == (1 if failure == "timeout" else 0)

    @parameterized.expand([("invalid_json",), ("missing_component",), ("unknown_choice",)])
    def test_malformed_responses_do_not_produce_labels(self, failure: str) -> None:
        response = _response()
        body = response.json()
        if failure == "missing_component":
            del body["answers"]["owned_ai_product"]
        elif failure == "unknown_choice":
            body["answers"]["owned_ai_product"]["choice"] = "maybe"
        response._content = b"not json" if failure == "invalid_json" else json.dumps(body).encode()
        with patch("requests.request", return_value=response):
            with self.assertRaises(JevResponseError):
                classify_with_jev(
                    model="jev-latest",
                    prompt_text=DEFAULT_JEV_PROMPT,
                    output_fields=DEFAULT_JEV_OUTPUT_FIELDS,
                    inputs={"description": "Synthetic stocktaking assistant."},
                    signup_domain=None,
                    website_url=None,
                    api_key=_KEY,
                    tools_enabled=False,
                )

    @parameterized.expand([("missing_key",), ("text_output",), ("missing_question",), ("derived_field_last",)])
    def test_invalid_configuration_makes_no_provider_calls(self, failure: str) -> None:
        fields = deepcopy(DEFAULT_JEV_OUTPUT_FIELDS)
        if failure == "text_output":
            fields[1]["type"] = "string"
        elif failure == "missing_question":
            fields[1]["description"] = ""
        elif failure == "derived_field_last":
            fields.reverse()
        with patch("requests.request") as request, patch(f"{_TOOLS}.scrape") as scrape:
            with self.assertRaises(JevConfigError):
                classify_with_jev(
                    model="jev-latest",
                    prompt_text=DEFAULT_JEV_PROMPT,
                    output_fields=fields,
                    inputs={"description": "Synthetic stocktaking assistant."},
                    signup_domain="inventory.example.com",
                    website_url=None,
                    api_key="" if failure == "missing_key" else _KEY,
                )
        request.assert_not_called()
        scrape.assert_not_called()

    def test_research_uses_the_supplied_website_and_bounded_deterministic_pages(self) -> None:
        urls = [
            "https://inventory.example.org/",
            "https://inventory.example.org/product",
            "https://docs.example.org/ai",
        ]
        search_result = FirecrawlSearch(
            query="synthetic",
            results=tuple(FirecrawlSearchResult(url=url) for url in urls[1:]),
        )
        with (
            patch("requests.request", return_value=_response()) as request,
            patch(f"{_TOOLS}.search", return_value=search_result) as search,
            patch(
                f"{_TOOLS}.scrape", side_effect=[FirecrawlScrape(url=url, markdown="x" * 5000) for url in urls]
            ) as scrape,
        ):
            result = classify_with_jev(
                model="jev-latest",
                prompt_text=DEFAULT_JEV_PROMPT,
                output_fields=DEFAULT_JEV_OUTPUT_FIELDS,
                inputs={"description": "Synthetic stocktaking assistant."},
                signup_domain="inventory.example.com",
                website_url=urls[0],
                api_key=_KEY,
            )
        assert result.output["ai_pilled"] is True
        assert [page.url for page in result.pages] == urls
        assert all(len(page.markdown) <= 4001 for page in result.pages)
        assert len(result.tool_calls) == 4
        assert scrape.call_count == 3
        search.assert_called_once()
        assert search.call_args.args[0].startswith("site:inventory.example.org ")
        assert search.call_args.kwargs["limit"] == 2
        assert len(request.call_args.kwargs["json"]["state"]["pages"]) == 3

    @parameterized.expand([(FirecrawlNotConfigured,), (FirecrawlEgressBudgetExhausted,), (requests.Timeout,)])
    def test_research_outages_do_not_produce_incomplete_labels(self, error: type[Exception]) -> None:
        with patch(f"{_TOOLS}.scrape", side_effect=error("synthetic outage")), patch("requests.request") as request:
            with self.assertRaises(JevResearchUnavailable):
                classify_with_jev(
                    model="jev-latest",
                    prompt_text=DEFAULT_JEV_PROMPT,
                    output_fields=DEFAULT_JEV_OUTPUT_FIELDS,
                    inputs={"description": "Synthetic stocktaking assistant."},
                    signup_domain="inventory.example.com",
                    website_url=None,
                    api_key=_KEY,
                )
        request.assert_not_called()
