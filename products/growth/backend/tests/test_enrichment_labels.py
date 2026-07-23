import json
import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from products.growth.backend.enrichment.labels import UNKNOWN, classify_payload
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

_BATCH_COMMAND_MODULE = "products.growth.backend.management.commands.enrichment_label_batch"
_DRY_RUN_COMMAND_MODULE = "products.growth.backend.management.commands.enrichment_label_dry_run"


def _mock_llm_client(
    ai_pilled: bool = True, confidence: float = 0.9, reasoning: str = "builds ai software"
) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = json.dumps(
        {"ai_pilled": ai_pilled, "confidence": confidence, "reasoning": reasoning}
    )
    client.chat.completions.create.return_value = response
    return client


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
            temperature=1.0,
            input_fields=["name"],
        )
        client = MagicMock()

        result = classify_payload(config, payload, "signup@example.com", client)

        # Missing data must never come back as a confident false verdict.
        assert result["ai_pilled"] == UNKNOWN
        client.chat.completions.create.assert_not_called()


class TestEnrichmentLabelBatch(BaseTest):
    def _config(
        self, version: str = "ai-pilled-clay-v1", prompt_text: str = "... Email: {email}", is_active: bool = True
    ) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version=version,
            prompt_text=prompt_text,
            model="gpt-5-mini",
            temperature=1.0,
            input_fields=["name"],
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

    def test_rejects_invalid_worker_and_sample_counts(self):
        self._config()
        with self.assertRaises(CommandError):
            call_command("enrichment_label_batch", label="test_label", workers=0)
        with self.assertRaises(CommandError):
            call_command("enrichment_label_dry_run", label="test_label", sample=-1)

    def test_llm_failure_is_captured_and_counted_without_persisting(self):
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
            call_command("enrichment_label_batch", label="test_label", workers=1)

        capture_mock.assert_called_once()
        assert EnrichmentLabelResult.objects.count() == 0

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


class TestEnrichmentPromptConfigImmutability(BaseTest):
    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            temperature=1.0,
            input_fields=["name"],
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
            output={"ai_pilled": True, "confidence": 0.9, "reasoning": "x"},
        )

    @parameterized.expand(
        [
            ("name", "another_label"),
            ("version", "test-v2"),
            ("prompt_text", "a completely different prompt"),
            ("model", "gpt-5-nano"),
            ("temperature", 0.5),
            ("input_fields", ["name", "description"]),
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
            temperature=1.0,
            input_fields=["name"],
            is_active=True,
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = _mock_llm_client()

        with patch(f"{_DRY_RUN_COMMAND_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_dry_run", label="test_label")

        assert EnrichmentLabelResult.objects.count() == 0

    def test_admin_bulk_delete_cannot_remove_a_config_with_stored_results(self):
        config = EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            temperature=1.0,
            input_fields=["name"],
        )
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
            output={"ai_pilled": True, "confidence": 0.9, "reasoning": "x"},
        )
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

        self.client.post(
            "/admin/growth/enrichmentpromptconfig/",
            {"action": "delete_selected", "_selected_action": [str(config.pk)], "post": "yes"},
        )

        assert EnrichmentPromptConfig.objects.filter(pk=config.pk).exists()

    def test_admin_dry_run_action_renders_verdicts_and_persists_nothing(self):
        config = EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="test-v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            temperature=1.0,
            input_fields=["name"],
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

        with patch("products.growth.backend.admin.get_llm_client", return_value=_mock_llm_client()):
            options_page = self.client.post(
                "/admin/growth/enrichmentpromptconfig/",
                {"action": "dry_run_selected", "_selected_action": [str(config.pk)]},
            )
            results_page = self.client.post(
                "/admin/growth/enrichmentpromptconfig/",
                {"action": "dry_run_selected", "_selected_action": [str(config.pk)], "apply": "1", "sample": "5"},
            )

        assert options_page.status_code == 200
        assert b"Sample size" in options_page.content
        assert results_page.status_code == 200
        assert b"Acme" in results_page.content
        assert b"true" in results_page.content
        assert EnrichmentLabelResult.objects.count() == 0
