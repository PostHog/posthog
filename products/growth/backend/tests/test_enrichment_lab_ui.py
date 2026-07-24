import json
import asyncio

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import reverse

from parameterized import parameterized

# Admin registration is import-time, and under settings.TEST there is no autodiscover —
# without this the admin POSTs below 404 in catch_all_view and pass vacuously.
import products.growth.backend.admin  # noqa: F401
from products.growth.backend.admin import _suggest_next_version
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch


def _mock_llm_client(
    verdict: bool = True, confidence: float = 0.9, reasoning: str = "builds ai software", label: str = "test_label"
) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = json.dumps({label: verdict, "confidence": confidence, "reasoning": reasoning})
    client.chat.completions.create.return_value = response
    return client


class TestSuggestNextVersion(SimpleTestCase):
    @parameterized.expand(
        [
            ("dash_v_suffix", "ai-pilled-clay-v1", "ai-pilled-clay-v2"),
            ("bare_v_suffix", "v1", "v2"),
            ("multi_digit", "test-v9", "test-v10"),
            ("no_version_suffix", "ai_pilled", "ai_pilled-v2"),
            ("empty", "", "v1"),
        ]
    )
    def test_bumps_or_appends(self, _name, version, expected):
        assert _suggest_next_version(version) == expected


class TestEnrichmentLabPage(BaseTest):
    def _login_staff(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)

    def _config(
        self, version: str = "test-v1", prompt_text: str = "judge it. Email: {email}", is_active: bool = True
    ) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version=version,
            prompt_text=prompt_text,
            model="gpt-5-mini",
            input_fields=["name"],
            is_active=is_active,
        )

    def test_lab_page_renders_version_rail_and_editor_prefilled_from_active_version(self):
        self._config(version="test-v1", prompt_text="old prompt. Email: {email}", is_active=False)
        active = self._config(version="test-v2", prompt_text="active prompt. Email: {email}", is_active=True)
        self._login_staff()

        response = self.client.get(reverse("admin:growth_enrichmentpromptconfig_lab", args=["test_label"]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "test-v1" in content
        assert "test-v2" in content
        assert active.prompt_text in content
        assert "Active" in content

    def test_run_endpoint_streams_verdicts_for_edited_prompt_and_persists_nothing(self):
        self._config(version="test-v1", prompt_text="saved prompt. Email: {email}", is_active=True)
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        self._login_staff()

        async def _drain(agen):
            return b"".join([chunk async for chunk in agen])

        with patch("products.growth.backend.admin.get_llm_client", return_value=_mock_llm_client()):
            response = self.client.post(
                reverse("admin:growth_enrichmentpromptconfig_lab_run", args=["test_label"]),
                {
                    "prompt_text": "a completely different, edited prompt. Email: {email}",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "sample": "10",
                    "contains": "",
                },
            )

        assert response.status_code == 200
        streamed = asyncio.run(_drain(response.streaming_content))  # type: ignore[attr-defined]
        assert b"Acme" in streamed
        assert b"true" in streamed
        assert EnrichmentLabelResult.objects.count() == 0
        # A "lab-draft" for this label would show up here if the run endpoint ever started
        # persisting - migration 0006 seeds an unrelated ai_pilled row, so scope to the label.
        assert EnrichmentPromptConfig.objects.filter(name="test_label").count() == 1

    def test_save_endpoint_creates_version_with_submitted_bytes_and_rejects_duplicate(self):
        self._config(version="test-v1", prompt_text="saved prompt. Email: {email}", is_active=True)
        self._login_staff()
        save_url = reverse("admin:growth_enrichmentpromptconfig_lab_save", args=["test_label"])
        payload = {
            "prompt_text": "a brand new experimental prompt. Email: {email}",
            "model": "gpt-5-nano",
            "input_fields": ["name", "description"],
            "version": "test-v2",
        }

        response = self.client.post(save_url, payload)

        assert response.status_code == 302
        new_config = EnrichmentPromptConfig.objects.get(name="test_label", version="test-v2")
        assert new_config.prompt_text == payload["prompt_text"]
        assert new_config.model == payload["model"]
        assert new_config.input_fields == payload["input_fields"]
        assert new_config.is_active is False
        assert new_config.created_by == self.user
        assert EnrichmentPromptConfig.objects.filter(name="test_label").count() == 2

        duplicate_response = self.client.post(save_url, payload)

        assert duplicate_response.status_code == 200
        assert b"already exists" in duplicate_response.content
        assert EnrichmentPromptConfig.objects.filter(name="test_label").count() == 2

    def test_run_and_save_reject_models_outside_the_allowlist(self):
        self._config()
        self._login_staff()
        submission = {
            "prompt_text": "judge it. Email: {email}",
            "model": "totally-made-up-model",
            "input_fields": ["name"],
        }

        run_resp = self.client.post(
            reverse("admin:growth_enrichmentpromptconfig_lab_run", args=["test_label"]),
            {**submission, "sample": "5"},
        )
        save_resp = self.client.post(
            reverse("admin:growth_enrichmentpromptconfig_lab_save", args=["test_label"]),
            {**submission, "version": "test-v2"},
        )

        assert run_resp.status_code == 400
        assert save_resp.status_code == 200
        assert EnrichmentPromptConfig.objects.filter(name="test_label").count() == 1

    def test_run_accepts_a_legacy_model_already_persisted_on_the_label(self):
        self._config()
        EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="legacy-v0",
            prompt_text="old. Email: {email}",
            model="legacy-model-name",
            input_fields=["name"],
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        self._login_staff()

        with patch("products.growth.backend.admin.get_llm_client", return_value=_mock_llm_client()):
            resp = self.client.post(
                reverse("admin:growth_enrichmentpromptconfig_lab_run", args=["test_label"]),
                {
                    "prompt_text": "old. Email: {email}",
                    "model": "legacy-model-name",
                    "input_fields": ["name"],
                    "sample": "5",
                },
            )

        assert resp.status_code == 200

    def test_changelist_shows_lab_link(self):
        self._config()
        self._login_staff()

        response = self.client.get("/admin/growth/enrichmentpromptconfig/")

        assert response.status_code == 200
        content = response.content.decode()
        assert "Open lab" in content
        assert reverse("admin:growth_enrichmentpromptconfig_lab", args=["test_label"]) in content
