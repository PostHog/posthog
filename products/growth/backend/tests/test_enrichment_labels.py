import json
import datetime as dt
from io import StringIO
from types import SimpleNamespace
from typing import Any, cast

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

import openai
from openai import OpenAI
from parameterized import parameterized

from posthog.egress.firecrawl import FirecrawlEgressBudgetExhausted
from posthog.egress.firecrawl.client import FirecrawlSearch, FirecrawlSearchResult
from posthog.models.organization import Organization, OrganizationMembership

from products.growth.backend.enrichment.labels import (
    MAX_INPUT_LIST_ITEMS,
    MAX_INPUT_VALUE_CHARS,
    UNKNOWN,
    OutputParseError,
    TransientToolError,
    build_messages,
    classify_payload,
    has_usable_payload,
    signup_domain_for_organization,
)
from products.growth.backend.management.commands import enrichment_label_batch as batch_command_module
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

_BATCH_COMMAND_MODULE = "products.growth.backend.management.commands.enrichment_label_batch"
_DRY_RUN_COMMAND_MODULE = "products.growth.backend.management.commands.enrichment_label_dry_run"
_LABELS_MODULE = "products.growth.backend.enrichment.labels"
_TOOLS_MODULE = "products.growth.backend.enrichment.tools"


def _mock_llm_client(
    verdict: bool = True, confidence: float = 0.9, reasoning: str = "builds ai software", verdict_key: str = "is_ai"
) -> MagicMock:
    client = MagicMock()
    # The command call sites chain .with_options(max_retries=0) onto get_llm_client(...); without
    # this, that call returns a fresh, unconfigured child mock and every assertion below silently
    # checks the wrong object.
    client.with_options.return_value = client
    response = MagicMock()
    response.choices[0].message.content = json.dumps(
        {verdict_key: verdict, "confidence": confidence, "reasoning": reasoning}
    )
    # A bare MagicMock().tool_calls is truthy, which the tool loop reads as "the model wants to
    # call a tool" - this fixture always answers in one turn.
    response.choices[0].message.tool_calls = None
    client.chat.completions.create.return_value = response
    return client


# Deliberately unlike the "test_label" label used throughout: output keys come from
# output_fields, never from the label, and a fixture that reuses the label name as a key
# would hide a regression to that.
_OUTPUT_FIELDS = [
    {"key": "is_ai", "type": "boolean", "description": ""},
    {"key": "confidence", "type": "number", "description": ""},
    {"key": "reasoning", "type": "string", "description": ""},
]


class TestClassifyPayloadMissingInput(SimpleTestCase):
    @parameterized.expand(
        [
            ("none_payload", None),
            ("empty_payload", {}),
            ("company_not_found", {"companyFound": False}),
        ]
    )
    def test_returns_unknown_without_calling_the_llm(self, _name, payload):
        config = EnrichmentPromptConfig(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[
                {"key": "is_ai", "type": "boolean", "description": ""},
                {"key": "headcount_estimate", "type": "number", "description": ""},
            ],
        )
        client = MagicMock()

        result = classify_payload(config, payload, "example.com", client)

        # Missing data must never come back as a confident false verdict.
        assert result["is_ai"] == UNKNOWN
        assert result["inputs"] == {"signup_domain": "example.com", "fields": {}}
        # The skipped path honors the schema too - it must not invent legacy confidence /
        # reasoning keys that this config never asked for.
        assert set(result) == {"is_ai", "meta", "inputs"}
        client.chat.completions.create.assert_not_called()

    def test_a_payload_with_none_of_the_configured_paths_is_unknown_without_spending(self):
        # Testing the raw payload instead of the resolved inputs meant a present-but-irrelevant
        # payload still billed a call asking the model about "Company data: {}".
        config = EnrichmentPromptConfig(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["funding.fundingStage"],
            output_fields=[{"key": "is_ai", "type": "boolean", "description": ""}],
        )
        client = MagicMock()

        result = classify_payload(config, {"companyFound": True, "unrelated": "x"}, "example.com", client)

        assert result["is_ai"] == UNKNOWN
        client.chat.completions.create.assert_not_called()


class TestClassifyPayloadEmailReduction(SimpleTestCase):
    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig(
            name="test_label",
            version="test-v1",
            prompt_text="judge it. Email: {email}",
            model="gpt-5-mini",
            input_fields=["contact"],
            output_fields=_OUTPUT_FIELDS,
        )

    @parameterized.expand(
        [
            ("top_level", "Alice.Secret@RowCo.com"),
            ("nested_in_a_list", ["alice.secret@rowco.com", "plain"]),
            ("nested_in_a_dict", {"primary": "alice.secret@rowco.com"}),
            ("nested_two_deep", [{"email": "alice.secret@rowco.com"}]),
        ]
    )
    def test_configured_input_field_emails_are_reduced_to_a_domain_at_any_depth(self, _name, value):
        # extract_input_fields is the only remaining input path now that query mode (which passed
        # every selected column through unreduced) is gone - a regression here leaks PII into the
        # prompt and into EnrichmentLabelResult.inputs indefinitely.
        config = self._config()
        client = _mock_llm_client()

        result = classify_payload(config, {"contact": value}, "example.com", client)

        sent = client.chat.completions.create.call_args.kwargs["messages"]
        rendered = json.dumps(sent) + json.dumps(result["inputs"])
        assert "alice.secret" not in rendered.lower()
        assert "rowco.com" in rendered


class TestHasUsablePayload(SimpleTestCase):
    @parameterized.expand(
        [
            ("none_payload", None, False),
            ("empty_payload", {}, False),
            ("not_found", {"companyFound": False}, False),
            ("sparse_matched", {"companyFound": True}, True),
            ("no_company_found_key", {"name": "Acme"}, True),
        ]
    )
    def test_matches_classify_payloads_own_short_circuit(self, _name, payload, expected):
        assert has_usable_payload(payload) is expected


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = call_id
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


class _FakeResponse:
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
        finish_reason: str = "stop",
        prompt_tokens: int = 10,
        completion_tokens: int = 5,
    ) -> None:
        message = SimpleNamespace(content=content, tool_calls=tool_calls)
        self.choices = [SimpleNamespace(message=message, finish_reason=finish_reason)]
        self.usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
        self.model = "gpt-5-mini-2026-07-01"
        self.system_fingerprint = "fp_test"


class _ScriptedClient:
    """Minimal OpenAI-client stand-in for the tool loop: chat.completions.create returns each
    scripted response in order and records the kwargs it was called with, so a test can see what
    the loop sent on each turn."""

    def __init__(self, *responses: _FakeResponse) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._responses[len(self.calls) - 1]


def _search_tool_call(call_id: str = "call_1", query: str = "Acme AI") -> _FakeToolCall:
    return _FakeToolCall(call_id, "web_search", {"query": query})


class TestClassifyPayloadToolLoop(SimpleTestCase):
    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig(
            name="test_label",
            version="v1",
            prompt_text="judge it. Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[
                {"key": "is_ai", "type": "boolean", "description": ""},
                {"key": "evidence_url", "type": "string", "description": ""},
            ],
        )

    def test_tool_loop_executes_web_search_and_feeds_the_result_back(self):
        config = self._config()
        client = _ScriptedClient(
            _FakeResponse(tool_calls=[_search_tool_call()]),
            _FakeResponse(content=json.dumps({"is_ai": True, "evidence_url": ""})),
        )
        found = FirecrawlSearch(
            query="Acme AI", results=(FirecrawlSearchResult(url="https://techcrunch.com/acme", title="funding"),)
        )

        with patch(f"{_TOOLS_MODULE}.search", return_value=found):
            result = classify_payload(config, {"name": "Acme"}, "example.com", cast(OpenAI, client))

        assert result["is_ai"] is True
        assert len(client.calls) == 2
        second_turn_messages = client.calls[1]["messages"]
        tool_messages = [m for m in second_turn_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert "techcrunch.com/acme" in tool_messages[0]["content"]

    def test_tool_calls_are_recorded_in_meta_and_bounded_in_stored_inputs(self):
        config = self._config()
        client = _ScriptedClient(
            _FakeResponse(tool_calls=[_search_tool_call(query="Acme AI")]),
            _FakeResponse(content=json.dumps({"is_ai": True, "evidence_url": ""})),
        )
        long_title = "x" * (MAX_INPUT_VALUE_CHARS + 500)
        found = FirecrawlSearch(
            query="Acme AI", results=(FirecrawlSearchResult(url="https://x.example", title=long_title),)
        )

        with patch(f"{_TOOLS_MODULE}.search", return_value=found):
            result = classify_payload(config, {"name": "Acme"}, "example.com", cast(OpenAI, client))

        assert result["meta"]["tool_calls"] == [
            {"name": "web_search", "arguments": {"query": "Acme AI"}, "error": None}
        ]
        assert result["meta"]["tool_urls"] == ["https://x.example"]
        [stored] = result["inputs"]["tool_calls"]
        assert stored["name"] == "web_search"
        stored_title = stored["result"]["results"][0]["title"]
        assert stored_title.endswith("…")
        assert len(stored_title) == MAX_INPUT_VALUE_CHARS + 1

    def test_usage_tokens_are_summed_across_tool_turns(self):
        config = self._config()
        client = _ScriptedClient(
            _FakeResponse(tool_calls=[_search_tool_call()], prompt_tokens=100, completion_tokens=10),
            _FakeResponse(
                content=json.dumps({"is_ai": True, "evidence_url": ""}), prompt_tokens=150, completion_tokens=20
            ),
        )
        found = FirecrawlSearch(query="Acme AI", results=(FirecrawlSearchResult(url="https://x.example"),))

        with patch(f"{_TOOLS_MODULE}.search", return_value=found):
            result = classify_payload(config, {"name": "Acme"}, "example.com", cast(OpenAI, client))

        assert result["meta"]["prompt_tokens"] == 250
        assert result["meta"]["completion_tokens"] == 30

    def test_a_fifth_tool_call_in_one_turn_gets_the_budget_error_and_the_next_turn_omits_tools(self):
        config = self._config()
        calls = [_search_tool_call(f"call_{i}", query=f"q{i}") for i in range(5)]
        client = _ScriptedClient(
            _FakeResponse(tool_calls=calls),
            _FakeResponse(content=json.dumps({"is_ai": True, "evidence_url": ""})),
        )
        found = FirecrawlSearch(query="q", results=(FirecrawlSearchResult(url="https://x.example"),))

        with patch(f"{_TOOLS_MODULE}.search", return_value=found):
            result = classify_payload(config, {"name": "Acme"}, "example.com", cast(OpenAI, client))

        # Only 4 of the 5 requested calls were actually executed.
        assert len(result["meta"]["tool_calls"]) == 4
        assert "tools" not in client.calls[1]
        assert "tool_choice" not in client.calls[1]
        rejected_message = client.calls[1]["messages"][-1]
        assert rejected_message["role"] == "tool"
        assert json.loads(rejected_message["content"]) == {"error": "tool budget exhausted"}

    def test_a_transient_tool_error_raises_before_any_further_model_call(self):
        config = self._config()
        client = _ScriptedClient(_FakeResponse(tool_calls=[_search_tool_call()]))

        with patch(f"{_TOOLS_MODULE}.search", side_effect=FirecrawlEgressBudgetExhausted("boom")):
            with self.assertRaises(TransientToolError):
                classify_payload(config, {"name": "Acme"}, "example.com", cast(OpenAI, client))

        assert len(client.calls) == 1

    def test_no_final_answer_after_max_tool_rounds_raises(self):
        config = self._config()
        calls = [_search_tool_call(f"call_{i}", query=f"q{i}") for i in range(3)]
        client = _ScriptedClient(
            _FakeResponse(tool_calls=[calls[0]]),
            _FakeResponse(tool_calls=[calls[1]]),
            _FakeResponse(tool_calls=[calls[2]]),
        )
        found = FirecrawlSearch(query="q", results=(FirecrawlSearchResult(url="https://x.example"),))

        with (
            patch(f"{_LABELS_MODULE}.MAX_TOOL_ROUNDS", 2),
            patch(f"{_LABELS_MODULE}.MAX_TOOL_CALLS", 10),
            patch(f"{_TOOLS_MODULE}.search", return_value=found),
        ):
            with self.assertRaises(OutputParseError):
                classify_payload(config, {"name": "Acme"}, "example.com", cast(OpenAI, client))

        # The third turn reveals the model still wants tools and is rejected before executing it.
        assert len(client.calls) == 3


class TestClassifyPayloadToolEvidenceUrl(SimpleTestCase):
    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig(
            name="test_label",
            version="v1",
            prompt_text="judge it. Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[
                {"key": "is_ai", "type": "boolean", "description": ""},
                {"key": "evidence_url", "type": "string", "description": ""},
            ],
        )

    def _client(self, evidence_url: str) -> _ScriptedClient:
        return _ScriptedClient(
            _FakeResponse(tool_calls=[_search_tool_call()]),
            _FakeResponse(content=json.dumps({"is_ai": True, "evidence_url": evidence_url})),
        )

    @parameterized.expand(
        [
            (
                "on_signup_domain",
                "https://acme.example/pricing",
                "https://x.example",
                "https://acme.example/pricing",
                False,
            ),
            (
                "matches_a_presented_search_result_off_domain",
                "https://techcrunch.com/acme",
                "https://techcrunch.com/acme",
                "https://techcrunch.com/acme",
                False,
            ),
            (
                "off_domain_and_unpresented",
                "https://not-acme.example/pricing",
                "https://techcrunch.com/acme",
                None,
                True,
            ),
            ("empty_string_is_left_alone", "", "https://x.example", "", False),
        ]
    )
    def test_evidence_url_is_validated_against_presented_tool_urls(
        self, _name, evidence_url, presented_url, expected, expect_rejected
    ):
        client = self._client(evidence_url)
        found = FirecrawlSearch(query="Acme AI", results=(FirecrawlSearchResult(url=presented_url),))

        with patch(f"{_TOOLS_MODULE}.search", return_value=found):
            result = classify_payload(self._config(), {"name": "Acme"}, "acme.example", cast(OpenAI, client))

        assert result["evidence_url"] == expected
        assert ("evidence_url_rejected" in result.get("meta", {})) is expect_rejected


class TestConfigurableOutputFields(SimpleTestCase):
    def _config(self, output_fields: list[dict]) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig(
            name="test_label",
            version="test-v1",
            prompt_text="judge it.",
            model="gpt-5-mini",
            input_fields=["company"],
            output_fields=output_fields,
        )

    def test_build_messages_lists_configured_keys_types_and_descriptions(self):
        config = self._config(
            [
                {"key": "is_enterprise", "type": "boolean", "description": "Enterprise flag"},
                {"key": "notes", "type": "string", "description": ""},
            ]
        )

        messages = build_messages(config, {"company": "Acme"}, None)

        user_content = messages[1]["content"]
        assert "is_enterprise" in user_content
        assert "notes" in user_content
        assert "Enterprise flag" in user_content
        # The legacy instruction (verdict/confidence/reasoning) must not leak into a custom schema.
        assert "confidence" not in user_content

    def test_stored_inputs_are_the_bounded_ones_sent_to_the_model(self):
        config = self._config([{"key": "is_enterprise", "type": "boolean", "description": ""}])
        config.input_fields = ["description", "tags", "investors"]
        client = MagicMock()
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"is_enterprise": True})
        response.choices[0].message.tool_calls = None
        response.usage = None
        client.chat.completions.create.return_value = response
        payload = {
            "description": "x" * (MAX_INPUT_VALUE_CHARS + 500),
            "tags": list(range(MAX_INPUT_LIST_ITEMS + 20)),
            # Provider fields hold lists of objects, so the cap has to reach inside them.
            "investors": [{"name": "y" * (MAX_INPUT_VALUE_CHARS + 500)}],
        }

        output = classify_payload(config, payload, None, client)

        stored = output["inputs"]["fields"]
        sent = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        assert len(stored["description"]) == MAX_INPUT_VALUE_CHARS + 1
        assert len(stored["tags"]) == MAX_INPUT_LIST_ITEMS
        assert len(stored["investors"][0]["name"]) == MAX_INPUT_VALUE_CHARS + 1
        assert json.dumps(stored, indent=2) in sent

    def test_parses_and_coerces_exactly_the_configured_keys(self):
        config = self._config(
            [
                {"key": "is_enterprise", "type": "boolean", "description": ""},
                {"key": "employee_estimate", "type": "number", "description": ""},
                {"key": "notes", "type": "string", "description": ""},
            ]
        )
        client = MagicMock()
        response = MagicMock()
        response.choices[0].message.content = json.dumps(
            {"is_enterprise": "true", "employee_estimate": "500", "notes": 42, "extra_ignored": "x"}
        )
        response.choices[0].message.tool_calls = None
        client.chat.completions.create.return_value = response

        output = classify_payload(config, {"company": "Acme"}, None, client)

        assert output["is_enterprise"] is True
        assert output["employee_estimate"] == 500.0
        assert output["notes"] == "42"
        assert "extra_ignored" not in output
        # The label name is never an output key.
        assert "test_label" not in output

    def test_raises_when_a_configured_key_is_missing_from_the_response(self):
        config = self._config([{"key": "is_enterprise", "type": "boolean", "description": ""}])
        client = MagicMock()
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"something_else": True})
        response.choices[0].message.tool_calls = None
        client.chat.completions.create.return_value = response

        with self.assertRaises(ValueError):
            classify_payload(config, {"company": "Acme"}, None, client)

    @parameterized.expand(
        [
            # "maybe" used to coerce to a confident False, which is exactly what the unknown path
            # exists to avoid.
            ("unrecognized_boolean", [{"key": "flag", "type": "boolean"}], {"flag": "maybe"}),
            # json.dumps writes bare NaN, which is invalid JSON and breaks the run stream.
            ("not_a_number", [{"key": "score", "type": "number"}], {"score": "NaN"}),
            ("out_of_range_confidence", [{"key": "confidence", "type": "number"}], {"confidence": 7.5}),
        ]
    )
    def test_rejects_a_value_it_cannot_faithfully_represent(self, _name, output_fields, content):
        config = self._config(output_fields)
        client = MagicMock()
        response = MagicMock()
        response.choices[0].message.content = json.dumps(content)
        response.choices[0].message.tool_calls = None
        client.chat.completions.create.return_value = response

        with self.assertRaises(OutputParseError):
            classify_payload(config, {"company": "Acme"}, None, client)

    def test_parses_a_reply_wrapped_in_a_code_fence_or_prose(self):
        config = self._config([{"key": "flag", "type": "boolean", "description": ""}])
        client = MagicMock()
        response = MagicMock()
        response.choices[0].message.content = 'Sure!\n```json\n{"flag": "yes"}\n```'
        response.choices[0].message.tool_calls = None
        client.chat.completions.create.return_value = response

        assert classify_payload(config, {"company": "Acme"}, None, client)["flag"] is True


class TestCallAndParseRetryAllowlist(SimpleTestCase):
    """The retry predicate is an allowlist, not a blacklist: a transient failure (connection
    error, timeout, 429, 5xx) earns tenacity's 3 attempts; anything else — most importantly
    AuthenticationError, which used to retry 3x under the old not-OutputParseError blacklist and
    stack with the SDK's own retries on top — fails on the first attempt."""

    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig(
            name="test_label",
            version="test-v1",
            prompt_text="judge it.",
            model="gpt-5-mini",
            input_fields=["company"],
            output_fields=[{"key": "flag", "type": "boolean", "description": ""}],
        )

    @parameterized.expand(
        [
            ("connection_error", lambda: openai.APIConnectionError(request=MagicMock())),
            ("timeout_error", lambda: openai.APITimeoutError(request=MagicMock())),
            ("rate_limit", lambda: openai.RateLimitError(message="rate limited", response=MagicMock(), body={})),
            (
                "server_error",
                lambda: openai.InternalServerError(message="upstream boom", response=MagicMock(), body={}),
            ),
        ]
    )
    def test_transient_failures_are_retried_to_the_full_attempt_budget(self, _name, make_error):
        config = self._config()
        client = MagicMock()
        error = make_error()
        client.chat.completions.create.side_effect = error

        with patch("tenacity.nap.time.sleep"), self.assertRaises(type(error)):
            classify_payload(config, {"company": "Acme"}, None, client)

        assert client.chat.completions.create.call_count == 3

    @parameterized.expand(
        [
            (
                "authentication_error",
                lambda: openai.AuthenticationError(message="bad key", response=MagicMock(), body={}),
            ),
            ("bad_request", lambda: openai.BadRequestError(message="bad request", response=MagicMock(), body={})),
            ("permission_denied", lambda: openai.PermissionDeniedError(message="nope", response=MagicMock(), body={})),
            ("unrelated_bug", lambda: RuntimeError("unexpected")),
        ]
    )
    def test_non_transient_failures_are_not_retried(self, _name, make_error):
        config = self._config()
        client = MagicMock()
        error = make_error()
        client.chat.completions.create.side_effect = error

        with patch("tenacity.nap.time.sleep"), self.assertRaises(type(error)):
            classify_payload(config, {"company": "Acme"}, None, client)

        assert client.chat.completions.create.call_count == 1

    def test_a_transient_failure_that_then_succeeds_is_billed_for_exactly_two_calls(self):
        config = self._config()
        client = MagicMock()
        good_response = MagicMock()
        good_response.choices[0].message.content = json.dumps({"flag": True})
        good_response.choices[0].message.tool_calls = None
        client.chat.completions.create.side_effect = [
            openai.RateLimitError(message="rate limited", response=MagicMock(), body={}),
            good_response,
        ]

        with patch("tenacity.nap.time.sleep"):
            result = classify_payload(config, {"company": "Acme"}, None, client)

        assert result["flag"] is True
        assert client.chat.completions.create.call_count == 2


class TestEnrichmentLabelBatch(BaseTest):
    def _config(
        self, version: str = "ai-pilled-clay-v1", prompt_text: str = "... Email: {email}", is_active: bool = True
    ) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version=version,
            prompt_text=prompt_text,
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_OUTPUT_FIELDS,
            is_active=is_active,
        )

    def _fetch(self, payload: dict | None = None) -> OrganizationEnrichmentFetch:
        return OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload=payload if payload is not None else {"name": "Acme"},
        )

    def test_batch_run_stamps_version_hash_model_and_fetch(self):
        config = self._config()
        fetch = self._fetch()
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        result = EnrichmentLabelResult.objects.get(organization=self.organization, label_name="test_label")
        assert result.prompt_version == config.version
        assert result.prompt_hash == config.content_hash
        assert result.model == config.model
        assert result.fetch_id == fetch.id

    def test_output_is_keyed_by_output_fields_and_stamps_response_meta(self):
        self._config()
        self._fetch()
        client = MagicMock()
        client.with_options.return_value = client
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"is_ai": True, "confidence": 0.8, "reasoning": "x"})
        response.choices[0].message.tool_calls = None
        response.model = "gpt-5-mini-2026-07-01"
        response.system_fingerprint = "fp_abc"
        response.usage.prompt_tokens = 900
        response.usage.completion_tokens = 40
        client.chat.completions.create.return_value = response

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        output = EnrichmentLabelResult.objects.get(label_name="test_label").output
        assert output["is_ai"] is True
        # Keyed by output_fields, never by the label: a stored verdict must survive a rename.
        assert "test_label" not in output
        assert "inputs" not in output
        assert output["meta"] == {
            "response_model": "gpt-5-mini-2026-07-01",
            "system_fingerprint": "fp_abc",
            "prompt_tokens": 900,
            "completion_tokens": 40,
        }

    def test_batch_run_stores_the_rendered_inputs_snapshot(self):
        self._config()
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        result = EnrichmentLabelResult.objects.get(label_name="test_label")
        assert result.inputs == {"signup_domain": "posthog.com", "fields": {"name": "Acme"}}
        assert "inputs" not in result.output

    def test_batch_run_snapshots_an_empty_unknown_verdict(self):
        self._config()
        self._fetch(payload={})
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        result = EnrichmentLabelResult.objects.get(label_name="test_label")
        assert result.output["is_ai"] == UNKNOWN
        assert result.inputs == {"signup_domain": "posthog.com", "fields": {}}
        assert "inputs" not in result.output
        client.chat.completions.create.assert_not_called()

    def test_rerun_is_idempotent_and_makes_no_further_llm_calls(self):
        self._config()
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)
            call_command("enrichment_label_batch", label="test_label", workers=1)

        assert EnrichmentLabelResult.objects.count() == 1
        assert client.chat.completions.create.call_count == 1

    def test_newer_fetch_recomputes_under_the_same_version_and_keeps_the_old_row(self):
        config = self._config()
        first_fetch = self._fetch()
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        second_fetch = self._fetch(payload={"name": "Acme v2"})
        OrganizationEnrichmentFetch.objects.filter(pk=second_fetch.pk).update(
            fetched_at=first_fetch.fetched_at + dt.timedelta(minutes=5)
        )

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        rows = EnrichmentLabelResult.objects.filter(
            organization=self.organization, prompt_version=config.version
        ).order_by("created_at")
        assert [row.fetch_id for row in rows] == [first_fetch.id, second_fetch.id]

    def test_a_rename_mid_run_stamps_the_current_label_not_the_retired_one(self):
        # Renaming deliberately leaves content_hash alone, so the mid-run config check can't
        # catch it. Stamping the captured name would strand this verdict under a label nothing
        # reads, and the next run for the renamed label would pay to recompute the same fetch.
        config = self._config()
        self._fetch()
        client = _mock_llm_client()
        renamed = {"done": False}
        original_classify = batch_command_module.classify_payload

        def rename_then_classify(*args, **kwargs):
            if not renamed["done"]:
                EnrichmentPromptConfig.objects.filter(pk=config.pk).update(name="renamed_label")
                renamed["done"] = True
            return original_classify(*args, **kwargs)

        with (
            patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client),
            patch(f"{_BATCH_COMMAND_MODULE}.classify_payload", side_effect=rename_then_classify),
        ):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        assert EnrichmentLabelResult.objects.filter(label_name="renamed_label").count() == 1
        assert EnrichmentLabelResult.objects.filter(label_name="test_label").count() == 0

    def test_rejects_invalid_worker_and_sample_counts(self):
        self._config()
        with self.assertRaises(CommandError):
            call_command("enrichment_label_batch", label="test_label", workers=0)
        with self.assertRaises(CommandError):
            call_command("enrichment_label_dry_run", label="test_label", sample=-1)

    def test_llm_failure_is_captured_exits_nonzero_and_is_not_retried(self):
        self._config()
        self._fetch()
        client = MagicMock()
        client.with_options.return_value = client
        response = MagicMock()
        response.choices[0].message.content = "not json at all"
        response.choices[0].message.tool_calls = None
        client.chat.completions.create.return_value = response

        with (
            patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client),
            patch(f"{_BATCH_COMMAND_MODULE}.capture_exception") as capture_mock,
            patch("tenacity.nap.time.sleep"),
        ):
            # Exiting 0 on a run where every item failed reads as a clean run to whatever
            # schedules this.
            with self.assertRaises(CommandError):
                call_command("enrichment_label_batch", label="test_label", workers=1)

        capture_mock.assert_called_once()
        assert EnrichmentLabelResult.objects.count() == 0
        # A reply that can't satisfy the schema fails identically every attempt, so retrying it
        # would just triple the spend.
        assert client.chat.completions.create.call_count == 1

    def test_unknown_accounting_uses_first_boolean_output_field_when_configured(self):
        # Without routing through verdict_field_key, `output.get(label)` would be None for a
        # custom output schema (whose keys are never the label name), so an unknown verdict
        # would silently vanish from the summary counts printed below.
        EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            is_active=True,
            output_fields=[
                {"key": "flag", "type": "boolean", "description": ""},
                {"key": "notes", "type": "string", "description": ""},
            ],
        )
        self._fetch(payload={})
        client = MagicMock()
        out = StringIO()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        assert "unknown 1" in out.getvalue()
        client.chat.completions.create.assert_not_called()
        result = EnrichmentLabelResult.objects.get(label_name="test_label")
        assert result.output.get("flag") == UNKNOWN

    def test_version_bump_recomputes_and_keeps_old_version_rows_intact(self):
        v1 = self._config(version="ai-pilled-clay-v1")
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        v1.is_active = False
        v1.save()
        self._config(version="ai-pilled-clay-v2", prompt_text="a different prompt entirely. Email: {email}")

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        assert EnrichmentLabelResult.objects.filter(prompt_version="ai-pilled-clay-v1").count() == 1
        assert EnrichmentLabelResult.objects.filter(prompt_version="ai-pilled-clay-v2").count() == 1


class TestSignupDomainForOrganization(BaseTest):
    @parameterized.expand(
        [
            ("normal", "founder@Acme.com", "acme.com"),
            ("uppercase_domain", "founder@ACME.COM", "acme.com"),
            ("no_at_sign", "not-an-email", None),
            ("empty", "", None),
        ]
    )
    def test_resolves_the_earliest_members_email_domain(self, _name, email, expected):
        # Every None here renders as the literal "unknown" in the prompt, so a bad address must
        # not reach the model as a domain.
        self.user.email = email
        self.user.save()

        assert signup_domain_for_organization(self.organization) == expected

    def test_returns_none_when_the_organization_has_no_members(self):
        OrganizationMembership.objects.filter(organization=self.organization).delete()

        assert signup_domain_for_organization(self.organization) is None


class TestEnrichmentLabelDryRun(BaseTest):
    def test_dry_run_does_not_persist_any_results(self):
        EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_OUTPUT_FIELDS,
            is_active=True,
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = _mock_llm_client()

        with patch(f"{_DRY_RUN_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_dry_run", label="test_label")

        assert EnrichmentLabelResult.objects.count() == 0

    def test_renaming_a_label_leaves_the_dry_run_comparison_columns_resolving(self):
        # The one test that covers the whole family: five separate display sites used to read
        # output values by the label name or by a hardcoded key, so every one of them silently
        # started printing "?" / 0.00 / "" after a rename or under a non-default schema.
        old = EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[
                {"key": "is_ai", "type": "boolean", "description": ""},
                {"key": "score", "type": "number", "description": ""},
            ],
            is_active=False,
        )
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name="test_label",
            prompt_version="v1",
            prompt_hash=old.content_hash,
            model=old.model,
            output={"is_ai": True, "score": 0.85},
        )
        EnrichmentPromptConfig.objects.filter(pk=old.pk).update(name="ai_native_teams")
        EnrichmentLabelResult.objects.filter(label_name="test_label").update(label_name="ai_native_teams")
        current = EnrichmentPromptConfig.objects.create(
            name="ai_native_teams",
            version="v2",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[{"key": "is_ai", "type": "boolean", "description": ""}],
            is_active=True,
        )
        client = MagicMock()
        client.with_options.return_value = client
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"is_ai": False})
        response.choices[0].message.tool_calls = None
        client.chat.completions.create.return_value = response
        out = StringIO()

        with patch(f"{_DRY_RUN_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command(
                "enrichment_label_dry_run",
                label="ai_native_teams",
                compare_version="v1",
                stdout=out,
            )

        printed = out.getvalue()
        assert "is_ai" in printed and "prev.is_ai" in printed and "prev.score" in printed
        # The stored v1 verdict still resolves under the new label, and v2's narrower schema
        # doesn't invent a value for a key it never asked for.
        assert "true" in printed and "0.85" in printed
        assert current.output_fields == [{"key": "is_ai", "type": "boolean", "description": ""}]


class TestEnrichmentLabelBatchConcurrency(NonAtomicBaseTest):
    """Non-atomic on purpose: worker threads get their own DB connections, so under the usual
    transactional base they would never see rows the test created and the run would classify
    nothing while still passing a naive assertion."""

    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_OUTPUT_FIELDS,
            is_active=True,
        )

    def test_concurrent_workers_pay_for_each_fetch_exactly_once(self):
        # The pre-spend existence re-check inside the worker is the only thing stopping two
        # threads paying for the same fetch, and prod runs with workers > 1 while every other
        # command test runs serially. A regression here is billed twice, not just wrong.
        self._config()
        for index in range(4):
            OrganizationEnrichmentFetch.objects.create(
                organization=Organization.objects.create(name=f"org-{index}"),
                provider="harmonic",
                payload={"name": f"Acme {index}"},
            )
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=2)

        assert client.chat.completions.create.call_count == 4
        assert EnrichmentLabelResult.objects.count() == 4

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=2)

        assert client.chat.completions.create.call_count == 4
        assert EnrichmentLabelResult.objects.count() == 4
