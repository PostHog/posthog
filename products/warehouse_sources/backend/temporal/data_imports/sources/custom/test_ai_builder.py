import json
from typing import cast

from django.test import SimpleTestCase

from openai import OpenAI
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.custom.ai_builder import (
    build_system_prompt,
    build_user_prompt,
    draft_manifest_sync,
    extract_manifest_json,
)


def _valid_manifest(base_url: str = "https://api.example.com") -> dict:
    return {
        "client": {"base_url": base_url, "auth": {"type": "bearer"}},
        "resources": [{"name": "users", "primary_key": "id", "endpoint": {"path": "/users", "data_selector": "data"}}],
    }


class _FakeCompletions:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> object:
        index = min(len(self.calls), len(self._responses) - 1)
        self.calls.append(kwargs)
        content = self._responses[index]
        return type(
            "Resp",
            (),
            {"choices": [type("Choice", (), {"message": type("Msg", (), {"content": content})})]},
        )


class _FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(responses)})

    def with_options(self, **kwargs: object) -> "_FakeClient":
        # Mirror the OpenAI client's per-call options override, which returns a configured client.
        return self


def _client(responses: list[str]) -> OpenAI:
    return cast(OpenAI, _FakeClient(responses))


class TestExtractManifestJson(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", '{"client": {}}', {"client": {}}),
            ("fenced_json", '```json\n{"a": 1}\n```', {"a": 1}),
            ("fenced_bare", '```\n{"a": 1}\n```', {"a": 1}),
            ("prose_wrapped", 'Here you go:\n{"a": 1}\nDone.', {"a": 1}),
        ]
    )
    def test_parses_object(self, _name: str, content: str, expected: dict) -> None:
        self.assertEqual(extract_manifest_json(content), expected)

    @parameterized.expand(
        [
            ("not_json", "this is not json at all"),
            ("array", "[1, 2, 3]"),
            ("empty", ""),
        ]
    )
    def test_returns_none(self, _name: str, content: str) -> None:
        self.assertIsNone(extract_manifest_json(content))


class TestPrompts(SimpleTestCase):
    def test_system_prompt_embeds_reference_and_rules(self) -> None:
        prompt = build_system_prompt("THE-GRAMMAR-REFERENCE")
        self.assertIn("THE-GRAMMAR-REFERENCE", prompt)
        self.assertIn("ONLY", prompt)
        self.assertIn("auth_*", prompt)
        self.assertIn("untrusted", prompt)

    def test_user_prompt_includes_docs_and_name(self) -> None:
        prompt = build_user_prompt(source_name="Acme", docs_text="DOCS-BODY")
        self.assertIn("Acme", prompt)
        self.assertIn("DOCS-BODY", prompt)
        self.assertNotIn("previous manifest", prompt.lower())

    def test_repair_prompt_includes_prior_failure(self) -> None:
        prompt = build_user_prompt(
            source_name="Acme",
            docs_text="DOCS-BODY",
            prior_manifest_json='{"bad": true}',
            prior_error="resources: must not be empty",
        )
        self.assertIn('{"bad": true}', prompt)
        self.assertIn("resources: must not be empty", prompt)

    def test_repair_prompt_includes_error_when_prior_json_unparseable(self) -> None:
        # Unparseable reply → no prior manifest, but the error must still reach the model.
        prompt = build_user_prompt(
            source_name="Acme",
            docs_text="DOCS-BODY",
            prior_manifest_json=None,
            prior_error="response was not valid JSON",
        )
        self.assertIn("response was not valid JSON", prompt)


class TestDraftManifestSync(SimpleTestCase):
    def test_happy_path_returns_ok_first_attempt(self) -> None:
        client = _client([json.dumps(_valid_manifest())])
        result = draft_manifest_sync(
            team_id=1, source_name="Acme", docs_text="docs", client=client, reference_text="ref"
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.resource_names, ["users"])
        self.assertEqual(result.attempts, 1)
        self.assertIsNotNone(result.manifest_json)

    def test_repairs_invalid_then_succeeds(self) -> None:
        # First reply is missing the required `resources` key, second is valid — the loop should
        # feed the validation error back and recover on the second attempt.
        client = _client(
            [json.dumps({"client": {"base_url": "https://api.example.com"}}), json.dumps(_valid_manifest())]
        )
        result = draft_manifest_sync(
            team_id=1, source_name="Acme", docs_text="docs", client=client, reference_text="ref"
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.attempts, 2)

    def test_model_error_when_never_valid_json(self) -> None:
        client = _client(["not json"])
        result = draft_manifest_sync(
            team_id=1, source_name="Acme", docs_text="docs", max_attempts=2, client=client, reference_text="ref"
        )
        self.assertEqual(result.status, "model_error")
        self.assertEqual(result.attempts, 2)
        self.assertIsNone(result.manifest_json)

    def test_invalid_when_manifest_never_validates(self) -> None:
        client = _client([json.dumps({"client": {"base_url": "https://api.example.com"}})])
        result = draft_manifest_sync(
            team_id=1, source_name="Acme", docs_text="docs", max_attempts=3, client=client, reference_text="ref"
        )
        self.assertEqual(result.status, "invalid")
        self.assertEqual(result.attempts, 3)
        self.assertIsNotNone(result.manifest_json)
        self.assertIsNotNone(result.error)

    def test_invalid_keeps_last_parseable_draft_when_final_reply_unparseable(self) -> None:
        # Attempt 1 parses but fails validation; the final attempt is unparseable. The result must
        # still carry the earlier draft — `invalid` promises a manifest_json to fix by hand — rather
        # than nulling it because the last reply happened to be garbage.
        client = _client([json.dumps({"client": {"base_url": "https://api.example.com"}}), "not json at all"])
        result = draft_manifest_sync(
            team_id=1, source_name="Acme", docs_text="docs", max_attempts=2, client=client, reference_text="ref"
        )
        self.assertEqual(result.status, "invalid")
        self.assertIsNotNone(result.manifest_json)
