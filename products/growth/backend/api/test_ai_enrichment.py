import uuid

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

# Deliberately unlike any label name used below: output keys come from output_fields, never
# from the label, and a fixture that reuses the label name would hide a regression to that.
_OUTPUT_FIELDS = [
    {"key": "is_ai", "type": "boolean", "description": ""},
    {"key": "confidence", "type": "number", "description": ""},
    {"key": "reasoning", "type": "string", "description": ""},
]


class TestAIEnrichmentAPI(APIBaseTest):
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
        output_fields: list[dict[str, str]] | None = None,
    ) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name=label,
            version=version,
            prompt_text="judge it. Email: {email}",
            output_fields=_OUTPUT_FIELDS if output_fields is None else output_fields,
            model="gpt-5-mini",
            input_fields=["name"],
            is_active=is_active,
            created_by=self.user if created_by is None else created_by,
        )

    @parameterized.expand(
        [
            ("labels", "get", "/api/growth_ai_enrichment/labels/"),
            ("configs", "get", "/api/growth_ai_enrichment/configs/?label=test_label"),
            ("activate", "post", "/api/growth_ai_enrichment/activate/"),
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

        response = self.client.get("/api/growth_ai_enrichment/labels/")

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

        response = self.client.get("/api/growth_ai_enrichment/configs/?label=test_label")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        by_version = {row["version"]: row for row in response.json()["results"]}
        self.assertEqual(set(by_version), {"test-v1", "test-v2"})
        self.assertTrue(by_version["test-v1"]["has_results"])
        self.assertFalse(by_version["test-v2"]["has_results"])
        self.assertTrue(by_version["test-v2"]["is_active"])
        self.assertEqual(by_version["test-v1"]["created_by_email"], self.user.email)

    def test_activate_flips_active_flag_and_deactivates_previous(self):
        old_active = self._config(label="test_label", version="test-v1", is_active=True)
        target = self._config(label="test_label", version="test-v2", is_active=False)

        response = self.client.post("/api/growth_ai_enrichment/activate/", {"config_id": str(target.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_active"])
        target.refresh_from_db()
        old_active.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertFalse(old_active.is_active)

    def test_activate_reads_the_label_under_the_row_lock_not_before_it(self):
        # Reading config.name before the transaction meant a rename landing in between aimed the
        # deactivation at the retired name, matched no siblings, and left two rows active under
        # the new one - which growth_prompt_config_one_active rejects as an unhandled 500.
        old_active = self._config(label="old_label", version="v1", is_active=True)
        target = self._config(label="old_label", version="v2", is_active=False)
        EnrichmentPromptConfig.objects.filter(name="old_label").update(name="new_label")

        response = self.client.post("/api/growth_ai_enrichment/activate/", {"config_id": str(target.id)}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        target.refresh_from_db()
        old_active.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertFalse(old_active.is_active)

    def test_activate_unknown_config_returns_404(self):
        response = self.client.post(
            "/api/growth_ai_enrichment/activate/", {"config_id": str(uuid.uuid4())}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
