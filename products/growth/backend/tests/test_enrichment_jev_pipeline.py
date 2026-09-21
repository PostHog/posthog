import json
from copy import deepcopy
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized

from posthog.egress.firecrawl.client import FirecrawlScrape, FirecrawlSearch

from products.growth.backend.enrichment.bridge import OrganizationBridgeInputs
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.enrichment.jev import DEFAULT_JEV_OUTPUT_FIELDS, DEFAULT_JEV_PROMPT
from products.growth.backend.enrichment.labels import MAX_INPUT_VALUE_CHARS, classify_payload, is_unknown_output
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    IcpScoringConfig,
    OrganizationEnrichment,
    OrganizationEnrichmentFetch,
)

_TOOLS = "products.growth.backend.enrichment.tools"
_BATCH = "products.growth.backend.management.commands.enrichment_label_batch"
_RECOMPUTE = "products.growth.backend.enrichment.fit_recomputation"
_WEBSITE = "https://inventory.example.org/"
_PAYLOAD = {
    "id": "synthetic-inventory-company",
    "name": "Synthetic Inventory Company",
    "description": "Inventory operations.",
    "headcount": 8,
    "website": {"url": _WEBSITE, "domain": "inventory.example.org"},
}


def _config() -> EnrichmentPromptConfig:
    return EnrichmentPromptConfig(
        name="ai_pilled",
        version="synthetic-jev-v1",
        model="jev-latest",
        prompt_text=DEFAULT_JEV_PROMPT + " Company: {email}.",
        input_fields=["name", "description"],
        output_fields=deepcopy(DEFAULT_JEV_OUTPUT_FIELDS),
        is_active=True,
    )


def _response(choice: str = "positive", status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(
        {
            "model": "jev-synthetic-resolved",
            "answers": {
                key: {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 0.8,
                    "probabilities": {
                        option: float(option == choice) for option in ("positive", "no_support", "insufficient")
                    },
                }
                for key in ("internal_ai_development", "owned_ai_product")
            },
            "usage": {"input_tokens": 71, "output_tokens": 4},
        }
    ).encode()
    return response


@override_settings(TYPESAFE_API_KEY="synthetic-typesafe-credential")
class TestJevPayloadRouting(SimpleTestCase):
    @parameterized.expand([("positive", True), ("insufficient", "unknown")])
    def test_jev_uses_company_website_and_preserves_bounded_evidence_and_unknown_status(
        self, choice: str, expected: bool | str
    ) -> None:
        payload = {**_PAYLOAD, "description": "Inventory operations. " * 400}
        limiter = MagicMock()
        limiter.consume_sync.return_value = True
        with (
            patch("posthog.egress.typesafe.limiter.get_outbound_rate_limiter", return_value=limiter),
            patch("requests.request", return_value=_response(choice)) as request,
            patch(
                f"{_TOOLS}.scrape", return_value=FirecrawlScrape(url=_WEBSITE, markdown="synthetic page " * 500)
            ) as scrape,
            patch(f"{_TOOLS}.search", return_value=FirecrawlSearch(query="synthetic", results=())),
            patch("products.growth.backend.enrichment.labels._complete") as openai_request,
        ):
            result = classify_payload(_config(), payload, "inventory.example.com", None)

        openai_request.assert_not_called()
        request.assert_called_once()
        assert is_unknown_output(result) is (expected == "unknown")
        assert scrape.call_args.args[0] == _WEBSITE
        assert set(request.call_args.kwargs["json"]["questions"]) == {"internal_ai_development", "owned_ai_product"}
        assert result["ai_pilled"] == expected
        assert result["internal_ai_development"] == expected
        assert result["owned_ai_product"] == expected
        assert result["inputs"]["signup_domain"] == "inventory.example.com"
        assert len(result["inputs"]["fields"]["description"]) <= MAX_INPUT_VALUE_CHARS + 1
        assert result["inputs"]["pages"][0]["url"] == _WEBSITE
        assert len(result["inputs"]["pages"][0]["markdown"]) <= 4001
        assert result["meta"]["response_model"] == "jev-synthetic-resolved"
        assert result["meta"]["prompt_tokens"] == 71
        assert result["meta"]["completion_tokens"] == 4
        assert result["meta"]["answers"]["owned_ai_product"]["choice"] == choice
        assert result["meta"]["tool_calls"][0]["name"] == "fetch_page"
        assert result["meta"]["tool_urls"] == [_WEBSITE]


@override_settings(TYPESAFE_API_KEY="synthetic-typesafe-credential")
class TestJevBatchScoring(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(clear_lists_cache)
        clear_lists_cache()
        self.user.email = "engineer@inventory.example.com"
        self.user.save(update_fields=["email"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        EnrichmentPromptConfig.objects.filter(name="ai_pilled").update(is_active=False)
        self.config = _config()
        self.config.save()
        IcpScoringConfig.objects.create(
            version="synthetic-hog-formula",
            is_active=True,
            scoring_rules={
                "source": (
                    "let points := if(ai_pilled, 23, 0); "
                    "return {'status': 'scored', 'score': points, 'components': {'ai_pilled': points}, "
                    "'ai_pilled_source': if(ai_pilled, 'llm', null)};"
                )
            },
        )
        self.fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload=_PAYLOAD
        )
        self.gateway = self.enterContext(patch(f"{_BATCH}.get_llm_client"))
        self.enterContext(patch(f"{_BATCH}.get_instance_region", return_value=None))
        self.enterContext(patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"))
        self.enterContext(patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True))
        self.analytics = MagicMock()
        self.enterContext(patch(f"{_RECOMPUTE}.get_regional_ph_client", return_value=self.analytics))
        self.enterContext(
            patch(f"{_RECOMPUTE}.read_organization_bridge_inputs", return_value=OrganizationBridgeInputs())
        )
        self.enterContext(
            patch(f"{_TOOLS}.scrape", return_value=FirecrawlScrape(url=_WEBSITE, markdown="Synthetic page."))
        )
        self.enterContext(patch(f"{_TOOLS}.search", return_value=FirecrawlSearch(query="synthetic", results=())))
        limiter = MagicMock()
        limiter.consume_sync.return_value = True
        self.enterContext(patch("posthog.egress.typesafe.limiter.get_outbound_rate_limiter", return_value=limiter))

    @parameterized.expand([("positive", 23), ("insufficient", 0)])
    def test_batch_saves_jev_label_and_applies_the_active_hog_formula(self, choice: str, points: int) -> None:
        with patch("requests.request", return_value=_response(choice)) as request:
            call_command("enrichment_label_batch", label="ai_pilled", workers=1, stdout=StringIO())

        self.gateway.assert_not_called()
        request.assert_called_once()
        label = EnrichmentLabelResult.objects.get(fetch=self.fetch)
        assert label.output["ai_pilled"] == (True if choice == "positive" else "unknown")
        assert label.prompt_hash == self.config.content_hash
        assert label.inputs["pages"][0]["markdown"] == "Synthetic page."
        assert label.output["meta"]["response_model"] == "jev-synthetic-resolved"
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == points
        assert record.data["icp_fit_components"] == {"ai_pilled": points}
        assert record.data["icp_fit_lists_version"] == "synthetic-hog-formula"
        assert record.data["icp_fit_ai_label_projected_result_id"] == str(label.id)
        assert self.analytics.group_identify.call_args.kwargs["properties"]["icp_fit_score"] == points

    @parameterized.expand([("missing_key",), ("vendor_busy",)])
    def test_failed_jev_classification_never_stores_a_false_label(self, failure: str) -> None:
        with (
            override_settings(TYPESAFE_API_KEY="" if failure == "missing_key" else "synthetic-typesafe-credential"),
            patch("requests.request", return_value=_response(status=529)) as request,
        ):
            if failure == "missing_key":
                with self.assertRaises(CommandError):
                    call_command("enrichment_label_batch", label="ai_pilled", workers=1, stdout=StringIO())
            else:
                call_command("enrichment_label_batch", label="ai_pilled", workers=1, stdout=StringIO())

        self.gateway.assert_not_called()
        assert request.call_count == (0 if failure == "missing_key" else 1)
        assert not EnrichmentLabelResult.objects.filter(fetch=self.fetch).exists()
        assert not OrganizationEnrichment.objects.filter(organization=self.organization).exists()
        self.analytics.group_identify.assert_not_called()
