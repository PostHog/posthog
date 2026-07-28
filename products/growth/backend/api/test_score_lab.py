import json
import uuid
import asyncio

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite

from parameterized import parameterized
from rest_framework import status

from products.growth.backend.admin import EnrichmentLabelResultAdmin
from products.growth.backend.enrichment import lab as lab_module
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch


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


# Deliberately unlike any label name used below: output keys come from output_fields, never
# from the label, and a fixture that reuses the label name would hide a regression to that.
_OUTPUT_FIELDS = [
    {"key": "is_ai", "type": "boolean", "description": ""},
    {"key": "confidence", "type": "number", "description": ""},
    {"key": "reasoning", "type": "string", "description": ""},
]


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
        # A prior test's successful gateway call would otherwise leak a cached model list into
        # this test (list_gateway_models is module-level state, see enrichment/lab.py).
        lab_module._model_list_cache.update({"models": None, "expires_at": 0.0})

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
            ("labels", "get", "/api/growth_score_lab/labels/"),
            ("models", "get", "/api/growth_score_lab/models/"),
            ("input_fields", "get", "/api/growth_score_lab/input_fields/"),
            ("configs", "get", "/api/growth_score_lab/configs/?label=test_label"),
            ("run", "post", "/api/growth_score_lab/run/"),
            ("save", "post", "/api/growth_score_lab/save/"),
            ("activate", "post", "/api/growth_score_lab/activate/"),
            ("rename", "post", "/api/growth_score_lab/rename/"),
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

        with patch("products.growth.backend.api.score_lab.get_llm_client", return_value=_mock_llm_client()):
            response = self.client.post(
                "/api/growth_score_lab/run/",
                {
                    "label": "unsaved_label",
                    "prompt_text": "a draft prompt. Email: {email}",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 10,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        verdict_rows = [row for row in rows if "summary" not in row]
        (summary_row,) = [row for row in rows if "summary" in row]

        self.assertEqual(len(verdict_rows), 1)
        self.assertEqual(verdict_rows[0]["company"], "Acme")
        self.assertEqual(
            verdict_rows[0]["outputs"], {"is_ai": True, "confidence": 0.9, "reasoning": "builds ai software"}
        )
        self.assertEqual(summary_row["summary"], {"classified": 1, "unknown": 0, "errors": 0})
        # "unsaved_label" must never touch the DB - run classifies an in-memory config only.
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="unsaved_label").count(), 0)
        self.assertEqual(EnrichmentLabelResult.objects.count(), 0)

    def test_run_rejects_sample_over_the_max(self):
        # This endpoint spends real LLM money per sampled org - the 100 cap must be enforced
        # before any candidates are fetched or any LLM client is built.
        response = self.client.post(
            "/api/growth_score_lab/run/",
            {
                "label": "test_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": _OUTPUT_FIELDS,
                "sample": 101,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "sample")

    def test_save_creates_exactly_the_submitted_bytes(self):
        payload = {
            "label": "new_label",
            "prompt_text": "a brand new experimental prompt. Email: {email}",
            "model": "gpt-5-nano",
            "input_fields": ["name", "description"],
            "output_fields": _OUTPUT_FIELDS,
        }

        response = self.client.post("/api/growth_score_lab/save/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        config = EnrichmentPromptConfig.objects.get(name="new_label")
        self.assertEqual(config.prompt_text, payload["prompt_text"])
        self.assertEqual(config.model, payload["model"])
        self.assertEqual(config.input_fields, payload["input_fields"])
        self.assertEqual(config.output_fields, payload["output_fields"])
        self.assertFalse(config.is_active)
        self.assertEqual(config.created_by, self.user)
        self.assertEqual(response.json()["id"], str(config.id))

    def test_save_assigns_the_version_and_ignores_a_client_supplied_one(self):
        # Versions are system-generated identity; a client-chosen one is what let a rename
        # collide with, or silently overwrite, an existing version.
        payload = {
            "label": "seq_label",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "output_fields": _OUTPUT_FIELDS,
            "version": "hand-picked",
        }

        first = self.client.post("/api/growth_score_lab/save/", payload, format="json")
        second = self.client.post("/api/growth_score_lab/save/", payload, format="json")

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual([first.json()["version"], second.json()["version"]], ["v1", "v2"])

    def test_save_never_reuses_a_retired_version_string(self):
        # Counting rows instead of reading the highest suffix would hand out v2 again here, and
        # every verdict already stamped v2 would then read as this new prompt's output.
        self._config(label="seq_label", version="v1", is_active=False)
        self._config(label="seq_label", version="v2", is_active=False)
        EnrichmentPromptConfig.objects.filter(name="seq_label", version="v1").delete()

        response = self.client.post(
            "/api/growth_score_lab/save/",
            {"label": "seq_label", "prompt_text": "x", "model": "gpt-5-mini", "output_fields": _OUTPUT_FIELDS},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["version"], "v3")

    def test_save_rejects_a_payload_path_outside_the_allow_list(self):
        # Every selected path is sent to the LLM and then stored on the result indefinitely, so
        # an arbitrary dotted path is an open channel for whatever the provider returned.
        response = self.client.post(
            "/api/growth_score_lab/save/",
            {
                "label": "leaky_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "input_fields": ["contact.primaryEmail"],
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="leaky_label").count(), 0)

    def test_input_fields_serves_the_allow_list_the_save_endpoint_enforces(self):
        response = self.client.get("/api/growth_score_lab/input_fields/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        served = {row["value"] for row in response.json()["results"]}
        self.assertIn("funding.fundingStage", served)

        accepted = self.client.post(
            "/api/growth_score_lab/save/",
            {
                "label": "allowed_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "input_fields": sorted(served),
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )
        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)

    def test_save_rejects_an_invalid_new_label_slug(self):
        payload = {
            "label": "Not-Valid-Slug",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "input_fields": [],
            "output_fields": _OUTPUT_FIELDS,
        }

        response = self.client.post("/api/growth_score_lab/save/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "label")
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="Not-Valid-Slug").count(), 0)

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

    def test_rename_propagates_to_every_sibling_version_and_every_stamped_result(self):
        # A label is shared by all of its versions and the batch runner looks work up by label
        # name, so a rename that moves one row but not its siblings/results silently splits the
        # label in two and orphans every historical verdict from its config.
        old_v1 = self._config(label="old_label", version="v1", is_active=False)
        old_v2 = self._config(label="old_label", version="v2", is_active=True)
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        result = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name="old_label",
            prompt_version=old_v2.version,
            prompt_hash=old_v2.content_hash,
            model=old_v2.model,
            output={"is_ai": True, "confidence": 0.9, "reasoning": "x"},
        )

        response = self.client.post(
            "/api/growth_score_lab/rename/",
            {"config_id": str(old_v1.id), "label": "new_label"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        old_v1.refresh_from_db()
        old_v2.refresh_from_db()
        result.refresh_from_db()
        self.assertEqual(old_v1.name, "new_label")
        self.assertEqual(old_v2.name, "new_label")
        self.assertEqual(result.label_name, "new_label")

    def test_rename_into_an_existing_label_name_returns_400(self):
        # Allowing this would silently merge two distinct labels' version histories.
        self._config(label="label_a", version="v1")
        target = self._config(label="label_b", version="v1")

        response = self.client.post(
            "/api/growth_score_lab/rename/",
            {"config_id": str(target.id), "label": "label_a"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "label")
        target.refresh_from_db()
        self.assertEqual(target.name, "label_b")

    def test_rename_unknown_config_id_returns_404(self):
        response = self.client.post(
            "/api/growth_score_lab/rename/",
            {"config_id": str(uuid.uuid4()), "label": "whatever"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_rename_leaves_the_admin_verdict_column_resolvable_when_label_differs_from_output_key(self):
        # Regression for a bug family where display code read a stored verdict by label_name
        # instead of by output_fields' boolean key - it survived a declared-complete fix because
        # the affected code had no tests. Label and output key are deliberately different so a
        # rename that updates label_name but leaves `output` untouched can't hide behind them
        # coincidentally matching.
        # Not "ai_pilled": a real classifier of that name ships via a seed data migration, which
        # would collide with the one-active-per-label constraint below.
        config = self._config(
            label="test_ai_pilled",
            version="v1",
            output_fields=[
                {"key": "is_ai_native", "type": "boolean", "description": ""},
                {"key": "confidence", "type": "number", "description": ""},
            ],
        )
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        result = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=fetch,
            label_name="test_ai_pilled",
            prompt_version=config.version,
            prompt_hash=config.content_hash,
            model=config.model,
            output={"is_ai_native": True, "confidence": 0.9},
        )

        response = self.client.post(
            "/api/growth_score_lab/rename/",
            {"config_id": str(config.id), "label": "ai_native_org"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        result.refresh_from_db()
        self.assertEqual(result.label_name, "ai_native_org")
        admin_verdict = EnrichmentLabelResultAdmin(EnrichmentLabelResult, AdminSite()).verdict(result)
        self.assertEqual(admin_verdict, "is_ai_native=true")

    def test_models_returns_gateway_list_when_client_works(self):
        fake_client = MagicMock()
        fake_client.models.list.return_value = [MagicMock(id="gpt-5.2"), MagicMock(id="claude-fable-5")]

        with patch("products.growth.backend.enrichment.lab.get_llm_client", return_value=fake_client):
            response = self.client.get("/api/growth_score_lab/models/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"gpt-5.2", "claude-fable-5"})

    def test_models_returns_empty_rather_than_a_stale_list_when_the_gateway_is_down(self):
        with patch("products.growth.backend.enrichment.lab.get_llm_client", side_effect=RuntimeError("gateway down")):
            response = self.client.get("/api/growth_score_lab/models/")

        # No curated mirror: a hand-maintained fallback goes stale silently.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_run_builds_rows_from_input_query_instead_of_archived_fetches(self):
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "ArchivedCo"}
        )
        canned_rows = [{"company": "RowCo", "domain": "rowco.com", "headcount": 10}]

        with (
            patch("products.growth.backend.api.score_lab.run_input_query", return_value=canned_rows) as run_query_mock,
            patch("products.growth.backend.api.score_lab.get_llm_client", return_value=_mock_llm_client()),
        ):
            response = self.client.post(
                "/api/growth_score_lab/run/",
                {
                    "label": "row_query_label",
                    "prompt_text": "judge it. Email: {email}",
                    "model": "gpt-5-mini",
                    "input_query": "SELECT 1 as x",
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 10,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        verdict_rows = [row for row in rows if "summary" not in row]
        self.assertEqual(len(verdict_rows), 1)
        self.assertEqual(verdict_rows[0]["company"], "RowCo")
        self.assertEqual(verdict_rows[0]["domain"], "rowco.com")
        self.assertEqual(verdict_rows[0]["outputs"]["is_ai"], True)
        run_query_mock.assert_called_once_with("SELECT 1 as x", 10)

    def test_run_rejects_syntax_error_input_query(self):
        response = self.client.post(
            "/api/growth_score_lab/run/",
            {
                "label": "test_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "input_query": "SELEC nonsense !!! FRM",
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "input_query")

    @parameterized.expand(
        [
            ("syntax_error", "SELEC nonsense !!! FRM"),
            ("non_select", "INSERT INTO events (event) VALUES ('x')"),
        ]
    )
    def test_save_rejects_invalid_input_query(self, _name, query):
        response = self.client.post(
            "/api/growth_score_lab/save/",
            {
                "label": "iq_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "input_query": query,
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "input_query")
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="iq_label").count(), 0)

    def test_save_persists_input_query_and_output_fields_and_configs_endpoint_returns_them(self):
        payload = {
            "label": "iq_schema_label",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "input_query": "SELECT 1 as x",
            "output_fields": [{"key": "flag", "type": "boolean", "description": "d"}],
        }

        save_response = self.client.post("/api/growth_score_lab/save/", payload, format="json")

        self.assertEqual(save_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(save_response.json()["input_query"], "SELECT 1 as x")
        self.assertEqual(save_response.json()["output_fields"], payload["output_fields"])

        configs_response = self.client.get("/api/growth_score_lab/configs/?label=iq_schema_label")
        row = configs_response.json()["results"][0]
        self.assertEqual(row["input_query"], "SELECT 1 as x")
        self.assertEqual(row["output_fields"], payload["output_fields"])

    @parameterized.expand(
        [
            ("bad_key", [{"key": "Bad-Key", "type": "boolean", "description": ""}]),
            ("bad_type", [{"key": "ok_key", "type": "float", "description": ""}]),
            ("duplicate_key", [{"key": "a", "type": "boolean"}, {"key": "a", "type": "number"}]),
            ("reserved_key", [{"key": "meta", "type": "boolean"}]),
            # output_fields is the whole output contract, so an empty one is a config that
            # asks the model for nothing and stores nothing.
            ("empty", []),
        ]
    )
    def test_save_rejects_invalid_output_fields_schema(self, _name, output_fields):
        response = self.client.post(
            "/api/growth_score_lab/save/",
            {
                "label": "schema_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": output_fields,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Per-item errors attribute to output_fields, the list-level empty check to
        # output_fields__non_field_errors.
        self.assertTrue(response.json()["attr"].startswith("output_fields"), response.json())
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="schema_label").count(), 0)

    def test_run_coerces_output_values_and_prompts_exactly_the_configured_keys(self):
        output_fields = [
            {"key": "is_enterprise", "type": "boolean", "description": "Is this an enterprise company?"},
            {"key": "employee_estimate", "type": "number", "description": "Estimated headcount"},
        ]
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = MagicMock()
        response_obj = MagicMock()
        response_obj.choices[0].message.content = json.dumps({"is_enterprise": True, "employee_estimate": 500})
        client.chat.completions.create.return_value = response_obj

        with patch("products.growth.backend.api.score_lab.get_llm_client", return_value=client):
            response = self.client.post(
                "/api/growth_score_lab/run/",
                {
                    "label": "schema_label",
                    "prompt_text": "judge it",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": output_fields,
                    "sample": 10,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        verdict_rows = [row for row in rows if "summary" not in row]
        self.assertEqual(verdict_rows[0]["outputs"], {"is_enterprise": True, "employee_estimate": 500.0})
        self.assertNotIn("verdict", verdict_rows[0])

        sent_user_message = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn("is_enterprise", sent_user_message)
        self.assertIn("employee_estimate", sent_user_message)
