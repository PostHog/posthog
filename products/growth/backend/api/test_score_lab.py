import json
import uuid
import asyncio

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from rest_framework import status

from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch


def _mock_llm_client(
    verdict: bool = True, confidence: float = 0.9, reasoning: str = "builds ai software", label: str = "test_label"
) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = json.dumps({label: verdict, "confidence": confidence, "reasoning": reasoning})
    client.chat.completions.create.return_value = response
    return client


async def _drain(agen) -> bytes:
    return b"".join([chunk async for chunk in agen])


def _drain_ndjson(streaming_content) -> list[dict]:
    raw = asyncio.run(_drain(streaming_content))
    return [json.loads(line) for line in raw.decode().splitlines() if line]


class TestScoreLabAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def _config(
        self,
        label: str = "test_label",
        version: str = "test-v1",
        is_active: bool = True,
        created_by=None,
    ) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name=label,
            version=version,
            prompt_text="judge it. Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            is_active=is_active,
            created_by=self.user if created_by is None else created_by,
        )

    @parameterized.expand(
        [
            ("labels", "get", "/api/growth_score_lab/labels/"),
            ("configs", "get", "/api/growth_score_lab/configs/?label=test_label"),
            ("run", "post", "/api/growth_score_lab/run/"),
            ("save", "post", "/api/growth_score_lab/save/"),
            ("activate", "post", "/api/growth_score_lab/activate/"),
        ]
    )
    def test_non_staff_user_gets_403(self, _name, method, url):
        # The defining security behavior: this whole API is gated by IsStaffUser, not by any
        # personal-API-key scope, since it's registered scope_object = "INTERNAL".
        self.user.is_staff = False
        self.user.save()

        response = getattr(self.client, method)(url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_labels_lists_distinct_labels_with_version_counts_and_active_version(self):
        self._config(label="test_label", version="v1", is_active=False)
        self._config(label="test_label", version="v2", is_active=True)
        self._config(label="other_test_label", version="v1", is_active=True)

        response = self.client.get("/api/growth_score_lab/labels/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_label = {row["label"]: row for row in response.json()["results"]}
        self.assertEqual(by_label["test_label"]["version_count"], 2)
        self.assertEqual(by_label["test_label"]["active_version"], "v2")
        self.assertEqual(by_label["other_test_label"]["version_count"], 1)
        self.assertEqual(by_label["other_test_label"]["active_version"], "v1")

    def test_configs_lists_versions_for_label_with_has_results_and_created_by(self):
        with_results = self._config(label="test_label", version="test-v1", is_active=False)
        self._config(label="test_label", version="test-v2", is_active=True)
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name="test_label",
            prompt_version=with_results.version,
            prompt_hash=with_results.content_hash,
            model=with_results.model,
            output={"test_label": True, "confidence": 0.9, "reasoning": "x"},
        )

        response = self.client.get("/api/growth_score_lab/configs/?label=test_label")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_version = {row["version"]: row for row in response.json()["results"]}
        self.assertEqual(set(by_version), {"test-v1", "test-v2"})
        self.assertTrue(by_version["test-v1"]["has_results"])
        self.assertFalse(by_version["test-v2"]["has_results"])
        self.assertTrue(by_version["test-v2"]["is_active"])
        self.assertEqual(by_version["test-v1"]["created_by_email"], self.user.email)

    def test_run_streams_ndjson_verdicts_for_an_unsaved_config_and_persists_nothing(self):
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )

        with patch(
            "products.growth.backend.api.score_lab.get_llm_client",
            return_value=_mock_llm_client(label="unsaved_label"),
        ):
            response = self.client.post(
                "/api/growth_score_lab/run/",
                {
                    "label": "unsaved_label",
                    "prompt_text": "a draft prompt. Email: {email}",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "sample": 10,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = _drain_ndjson(response.streaming_content)
        verdict_rows = [row for row in rows if "summary" not in row]
        (summary_row,) = [row for row in rows if "summary" in row]

        self.assertEqual(len(verdict_rows), 1)
        self.assertEqual(verdict_rows[0]["company"], "Acme")
        self.assertEqual(verdict_rows[0]["verdict"], "true")
        self.assertEqual(summary_row["summary"], {"classified": 1, "unknown": 0, "errors": 0})
        # "unsaved_label" must never touch the DB - run classifies an in-memory config only.
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="unsaved_label").count(), 0)
        self.assertEqual(EnrichmentLabelResult.objects.count(), 0)

    def test_run_rejects_sample_over_the_max(self):
        # This endpoint spends real LLM money per sampled org - the 100 cap must be enforced
        # before any candidates are fetched or any LLM client is built.
        response = self.client.post(
            "/api/growth_score_lab/run/",
            {"label": "test_label", "prompt_text": "x", "model": "gpt-5-mini", "sample": 101},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "sample")

    def test_save_creates_exactly_the_submitted_bytes(self):
        payload = {
            "label": "new_label",
            "version": "v1",
            "prompt_text": "a brand new experimental prompt. Email: {email}",
            "model": "gpt-5-nano",
            "input_fields": ["name", "description"],
        }

        response = self.client.post("/api/growth_score_lab/save/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        config = EnrichmentPromptConfig.objects.get(name="new_label", version="v1")
        self.assertEqual(config.prompt_text, payload["prompt_text"])
        self.assertEqual(config.model, payload["model"])
        self.assertEqual(config.input_fields, payload["input_fields"])
        self.assertFalse(config.is_active)
        self.assertEqual(config.created_by, self.user)
        self.assertEqual(response.json()["id"], str(config.id))

    @parameterized.expand(
        [
            ("duplicate_label_version", True, {"label": "test_label", "version": "test-v1"}, "version"),
            ("invalid_new_label_slug", False, {"label": "Not-Valid-Slug", "version": "v1"}, "label"),
            ("invalid_model", False, {"model": "not-a-real-gateway-model"}, "model"),
        ]
    )
    def test_save_rejects_invalid_payload_with_400(self, _name, seed_existing, overrides, expected_attr):
        if seed_existing:
            self._config(label="test_label", version="test-v1")
        payload = {
            "label": "test_label",
            "version": "test-v1",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "input_fields": [],
        }
        payload.update(overrides)
        count_before = EnrichmentPromptConfig.objects.count()

        response = self.client.post("/api/growth_score_lab/save/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], expected_attr)
        # A rejected save must never create a row, whether it's the duplicate-version case
        # (nothing new) or the invalid-slug/model cases (seed_existing is False, so still 0).
        self.assertEqual(EnrichmentPromptConfig.objects.count(), count_before)

    def test_activate_flips_active_flag_and_deactivates_previous(self):
        old_active = self._config(label="test_label", version="test-v1", is_active=True)
        target = self._config(label="test_label", version="test-v2", is_active=False)

        response = self.client.post("/api/growth_score_lab/activate/", {"config_id": str(target.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_active"])
        target.refresh_from_db()
        old_active.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertFalse(old_active.is_active)

    def test_activate_unknown_config_returns_404(self):
        response = self.client.post("/api/growth_score_lab/activate/", {"config_id": str(uuid.uuid4())}, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
