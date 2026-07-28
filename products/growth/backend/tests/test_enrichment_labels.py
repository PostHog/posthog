import json
import datetime as dt
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership

from products.growth.backend.enrichment.input_query import InputQueryError, parse_input_query, rows_from_query_result
from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    OutputParseError,
    build_messages,
    classify_payload,
    classify_row,
    signup_domain_for_organization,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

_BATCH_COMMAND_MODULE = "products.growth.backend.management.commands.enrichment_label_batch"
_DRY_RUN_COMMAND_MODULE = "products.growth.backend.management.commands.enrichment_label_dry_run"


def _mock_llm_client(
    verdict: bool = True, confidence: float = 0.9, reasoning: str = "builds ai software", verdict_key: str = "is_ai"
) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = json.dumps(
        {verdict_key: verdict, "confidence": confidence, "reasoning": reasoning}
    )
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


class TestClassifyRow(SimpleTestCase):
    def _config(self, **overrides) -> EnrichmentPromptConfig:
        defaults = {
            "name": "test_label",
            "version": "test-v1",
            "prompt_text": "judge it. Email: {email}",
            "model": "gpt-5-mini",
            "output_fields": _OUTPUT_FIELDS,
        }
        defaults.update(overrides)
        return EnrichmentPromptConfig(**defaults)

    def test_uses_domain_column_and_passes_every_column_as_inputs(self):
        config = self._config()
        client = _mock_llm_client()
        row = {"company": "RowCo", "domain": "rowco.com", "headcount": 50}

        result = classify_row(config, row, client)

        assert result["is_ai"] is True
        assert result["inputs"] == {"signup_domain": "rowco.com", "fields": row}
        sent_system = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "rowco.com" in sent_system

    def test_missing_domain_column_falls_back_to_unknown_domain_in_prompt(self):
        config = self._config()
        client = _mock_llm_client()

        classify_row(config, {"company": "RowCo"}, client)

        sent_system = client.chat.completions.create.call_args.kwargs["messages"][0]["content"]
        assert "unknown" in sent_system

    def test_email_columns_are_reduced_to_a_domain_before_the_prompt_and_the_snapshot(self):
        # A query can select any column, and whatever it selects is both sent to the LLM and
        # stored on the result indefinitely - the local part carries no classification signal.
        config = self._config()
        client = _mock_llm_client()

        result = classify_row(config, {"company": "RowCo", "domain": "Alice.Secret@RowCo.com"}, client)

        sent = client.chat.completions.create.call_args.kwargs["messages"]
        rendered = sent[0]["content"] + sent[1]["content"]
        assert "alice.secret" not in rendered.lower()
        assert "rowco.com" in rendered
        assert result["inputs"] == {"signup_domain": "rowco.com", "fields": {"company": "RowCo", "domain": "rowco.com"}}


class TestConfigurableOutputFields(SimpleTestCase):
    def _config(self, output_fields: list[dict]) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig(
            name="test_label",
            version="test-v1",
            prompt_text="judge it.",
            model="gpt-5-mini",
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
        client.chat.completions.create.return_value = response

        output = classify_row(config, {"company": "Acme"}, client)

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
        client.chat.completions.create.return_value = response

        with self.assertRaises(ValueError):
            classify_row(config, {"company": "Acme"}, client)

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
        client.chat.completions.create.return_value = response

        with self.assertRaises(OutputParseError):
            classify_row(config, {"company": "Acme"}, client)

    def test_parses_a_reply_wrapped_in_a_code_fence_or_prose(self):
        config = self._config([{"key": "flag", "type": "boolean", "description": ""}])
        client = MagicMock()
        response = MagicMock()
        response.choices[0].message.content = 'Sure!\n```json\n{"flag": "yes"}\n```'
        client.chat.completions.create.return_value = response

        assert classify_row(config, {"company": "Acme"}, client)["flag"] is True


class TestInputQueryParsing(SimpleTestCase):
    def test_valid_select_parses(self):
        node = parse_input_query("SELECT event, timestamp FROM events LIMIT 10")
        assert node is not None

    def test_syntax_error_raises_input_query_error(self):
        with self.assertRaises(InputQueryError):
            parse_input_query("SELEC nonsense !!! FRM")

    def test_non_select_statement_raises_input_query_error(self):
        with self.assertRaises(InputQueryError):
            parse_input_query("INSERT INTO events (event) VALUES ('x')")


class TestRowsFromQueryResult(SimpleTestCase):
    def test_maps_columns_to_row_dicts(self):
        rows = rows_from_query_result(["company", "domain"], [["Acme", "acme.com"], ["Widgets", None]])
        assert rows == [{"company": "Acme", "domain": "acme.com"}, {"company": "Widgets", "domain": None}]

    @parameterized.expand(
        [
            ("no_columns", None, [["a"]]),
            ("no_results", ["a"], None),
            ("empty_results", ["a"], []),
        ]
    )
    def test_empty_input_returns_no_rows(self, _name, columns, results):
        assert rows_from_query_result(columns, results) == []


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
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"is_ai": True, "confidence": 0.8, "reasoning": "x"})
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

    def test_refuses_an_input_query_config_before_spending_anything(self):
        # classify_payload reads input_fields, so running a query-mode config would bill one LLM
        # call per org against an empty input dict and persist the answers under a real version.
        EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_query="SELECT 1 as x",
            output_fields=_OUTPUT_FIELDS,
            is_active=True,
        )
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_BATCH_COMMAND_MODULE}.get_llm_client", return_value=client):
            with self.assertRaises(CommandError):
                call_command("enrichment_label_batch", label="test_label", workers=1)

        client.chat.completions.create.assert_not_called()
        assert EnrichmentLabelResult.objects.count() == 0

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
        response = MagicMock()
        response.choices[0].message.content = "not json at all"
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


class TestEnrichmentPromptConfigImmutability(BaseTest):
    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_OUTPUT_FIELDS,
            is_active=True,
        )

    def _stamp_a_result(self, config: EnrichmentPromptConfig) -> None:
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name=config.name,
            prompt_version=config.version,
            prompt_hash=config.content_hash,
            model=config.model,
            output={"test_label": True, "confidence": 0.9, "reasoning": "x"},
        )

    @parameterized.expand(
        [
            ("version", "test-v2"),
            ("prompt_text", "a completely different prompt"),
            ("model", "gpt-5-nano"),
            ("input_fields", ["name", "description"]),
            ("input_query", "SELECT 1 as x"),
            ("output_fields", [{"key": "custom_field", "type": "boolean", "description": ""}]),
        ]
    )
    def test_editing_a_frozen_field_with_stored_results_raises(self, field, new_value):
        config = self._config()
        self._stamp_a_result(config)

        setattr(config, field, new_value)
        with self.assertRaises(ValidationError):
            config.save()

    def test_editing_is_active_with_stored_results_saves_fine(self):
        config = self._config()
        self._stamp_a_result(config)

        config.is_active = False
        config.save()

        config.refresh_from_db()
        assert config.is_active is False

    def test_renaming_a_label_with_stored_results_saves_fine_and_keeps_the_content_hash(self):
        # The whole point of output_fields being the output contract: a label is a human name,
        # so renaming it must not freeze on stored results, and must not move the content hash
        # (which would make the batch runner recompute every verdict under the same version).
        config = self._config()
        self._stamp_a_result(config)
        hash_before = config.content_hash

        config.name = "another_label"
        config.save()

        config.refresh_from_db()
        assert config.name == "another_label"
        assert config.content_hash == hash_before

    def test_delete_guards_on_persisted_values_not_the_stale_instance(self):
        config = self._config()
        stale = EnrichmentPromptConfig.objects.get(pk=config.pk)
        config.version = "test-v2"
        config.save()
        self._stamp_a_result(config)

        with self.assertRaises(ValidationError):
            stale.delete()
        assert EnrichmentPromptConfig.objects.filter(pk=config.pk).exists()

    def test_editing_a_frozen_field_without_results_saves_fine(self):
        config = self._config()

        config.prompt_text = "a completely different prompt"
        config.save()

        config.refresh_from_db()
        assert config.prompt_text == "a completely different prompt"


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
        response = MagicMock()
        response.choices[0].message.content = json.dumps({"is_ai": False})
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
