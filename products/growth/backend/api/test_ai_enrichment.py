import json
import uuid
import asyncio
from typing import Any

from posthog.test.base import APIBaseTest, NonAtomicAPIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import Organization

from products.growth.backend.api.ai_enrichment_serializers import (
    OutputFieldSerializer,
    RunRequestSerializer,
    SaveRequestSerializer,
)
from products.growth.backend.enrichment import lab as lab_module
from products.growth.backend.enrichment.labels import (
    MAX_OUTPUT_FIELD_DESCRIPTION_CHARS,
    MAX_OUTPUT_FIELDS,
    MAX_PROMPT_TEXT_CHARS,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

# Deliberately unlike any label name used below: output keys come from output_fields, never
# from the label, and a fixture that reuses the label name would hide a regression to that.
_OUTPUT_FIELDS = [
    {"key": "is_ai", "type": "boolean", "description": ""},
    {"key": "confidence", "type": "number", "description": ""},
    {"key": "reasoning", "type": "string", "description": ""},
]


def _mock_llm_client(
    verdict: bool = True, confidence: float = 0.9, reasoning: str = "builds ai software", verdict_key: str = "is_ai"
) -> MagicMock:
    client = MagicMock()
    # The run action chains .with_options(max_retries=0) onto get_llm_client(...); without this,
    # that call returns a fresh, unconfigured child mock and every assertion below silently
    # checks the wrong object (see enrichment_label_batch.py for the same pattern).
    client.with_options.return_value = client
    response = MagicMock()
    response.choices[0].message.content = json.dumps(
        {verdict_key: verdict, "confidence": confidence, "reasoning": reasoning}
    )
    client.chat.completions.create.return_value = response
    return client


async def _drain(agen) -> bytes:
    return b"".join([chunk async for chunk in agen])


def _drain_ndjson(streaming_content) -> list[dict]:
    raw = asyncio.run(_drain(streaming_content))
    return [json.loads(line) for line in raw.decode().splitlines() if line]


class TestAIEnrichmentAPI(APIBaseTest):
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
            ("labels", "get", "/api/growth_ai_enrichment/labels/"),
            ("models", "get", "/api/growth_ai_enrichment/models/"),
            ("configs", "get", "/api/growth_ai_enrichment/configs/?label=test_label"),
            ("save", "post", "/api/growth_ai_enrichment/save/"),
            ("run", "post", "/api/growth_ai_enrichment/run/"),
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

    def test_models_returns_gateway_list_when_client_works(self):
        fake_client = MagicMock()
        fake_client.models.list.return_value = [MagicMock(id="gpt-5.2"), MagicMock(id="claude-fable-5")]

        with patch("products.growth.backend.enrichment.lab.get_llm_client", return_value=fake_client):
            response = self.client.get("/api/growth_ai_enrichment/models/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {row["id"] for row in response.json()["results"]}
        self.assertEqual(ids, {"gpt-5.2", "claude-fable-5"})

    def test_models_returns_empty_rather_than_a_stale_list_when_the_gateway_is_down(self):
        with patch("products.growth.backend.enrichment.lab.get_llm_client", side_effect=RuntimeError("gateway down")):
            response = self.client.get("/api/growth_ai_enrichment/models/")

        # No curated mirror: a hand-maintained fallback goes stale silently.
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_save_creates_exactly_the_submitted_bytes(self):
        payload = {
            "label": "new_label",
            "prompt_text": "a brand new experimental prompt. Email: {email}",
            "model": "gpt-5-nano",
            "input_fields": ["name", "description"],
            "output_fields": _OUTPUT_FIELDS,
        }

        response = self.client.post("/api/growth_ai_enrichment/save/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        config = EnrichmentPromptConfig.objects.get(name="new_label")
        self.assertEqual(config.prompt_text, payload["prompt_text"])
        self.assertEqual(config.model, payload["model"])
        self.assertEqual(config.input_fields, payload["input_fields"])
        self.assertEqual(config.output_fields, payload["output_fields"])
        self.assertFalse(config.is_active)
        self.assertEqual(config.created_by, self.user)
        self.assertEqual(response.json()["id"], str(config.id))

    def test_save_assigns_the_suggested_version_when_none_supplied(self):
        payload = {
            "label": "seq_label",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "output_fields": _OUTPUT_FIELDS,
        }

        first = self.client.post("/api/growth_ai_enrichment/save/", payload, format="json")
        second = self.client.post("/api/growth_ai_enrichment/save/", payload, format="json")

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
            "/api/growth_ai_enrichment/save/",
            {"label": "seq_label", "prompt_text": "x", "model": "gpt-5-mini", "output_fields": _OUTPUT_FIELDS},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["version"], "v3")

    def test_save_suggests_the_next_version_from_a_v_suffix_anywhere_in_a_legacy_name(self):
        # "ai-pilled-clay-v1" doesn't fullmatch v<n>, but it still means v1 was taken - suggesting
        # v1 again here would let the new row collide in spirit (if not in DB uniqueness) with an
        # already-shipped classifier version.
        self._config(label="legacy_label", version="ai-pilled-clay-v1", is_active=True)

        response = self.client.post(
            "/api/growth_ai_enrichment/save/",
            {"label": "legacy_label", "prompt_text": "x", "model": "gpt-5-mini", "output_fields": _OUTPUT_FIELDS},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["version"], "v2")

    def test_save_falls_back_to_the_row_count_when_no_version_has_a_v_suffix_at_all(self):
        self._config(label="odd_label", version="alpha", is_active=True)
        self._config(label="odd_label", version="beta", is_active=False)

        response = self.client.post(
            "/api/growth_ai_enrichment/save/",
            {"label": "odd_label", "prompt_text": "x", "model": "gpt-5-mini", "output_fields": _OUTPUT_FIELDS},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["version"], "v3")

    def test_save_rejects_the_run_endpoints_draft_sentinel_as_a_version(self):
        # RunRequestSerializer stamps every unsaved test-run draft "lab-draft"; accepting it here
        # would let a real saved row collide in meaning with an in-flight, unpersisted test run.
        response = self.client.post(
            "/api/growth_ai_enrichment/save/",
            {
                "label": "sentinel_label",
                "version": "lab-draft",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="sentinel_label").count(), 0)

    def test_save_accepts_a_caller_supplied_version(self):
        payload = {
            "label": "manual_version_label",
            "version": "hand-picked-v1",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "output_fields": _OUTPUT_FIELDS,
        }

        response = self.client.post("/api/growth_ai_enrichment/save/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["version"], "hand-picked-v1")

    def test_save_rejects_a_version_that_collides_with_an_existing_one(self):
        # (name, version) must be unique - and this is the API's only surface for creating a
        # version, so a 500 here would be a real request path, not an edge case.
        self._config(label="collide_label", version="v1", is_active=False)

        response = self.client.post(
            "/api/growth_ai_enrichment/save/",
            {
                "label": "collide_label",
                "version": "v1",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="collide_label").count(), 1)

    @parameterized.expand(
        [
            ("bad_key", [{"key": "Bad-Key", "type": "boolean", "description": ""}]),
            ("bad_type", [{"key": "ok_key", "type": "float", "description": ""}]),
            ("duplicate_key", [{"key": "a", "type": "boolean"}, {"key": "a", "type": "number"}]),
            ("reserved_key", [{"key": "meta", "type": "boolean"}]),
            # output_fields is the whole output contract, so an empty one is a config that
            # asks the model for nothing and stores nothing.
            ("empty", []),
            ("too_many_fields", [{"key": f"f{i}", "type": "boolean"} for i in range(MAX_OUTPUT_FIELDS + 1)]),
            (
                "description_too_long",
                [{"key": "flag", "type": "boolean", "description": "x" * (MAX_OUTPUT_FIELD_DESCRIPTION_CHARS + 1)}],
            ),
        ]
    )
    def test_save_rejects_invalid_output_fields_schema(self, _name, output_fields):
        response = self.client.post(
            "/api/growth_ai_enrichment/save/",
            {
                "label": "schema_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": output_fields,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="schema_label").count(), 0)

    def test_save_rejects_input_fields_over_the_column_limit(self):
        # validate_input_fields (enrichment/labels.py), reused rather than reimplemented: more
        # input_fields than bound_inputs will carry means the tail is silently dropped from both
        # the prompt and the stored record on every future run of this version.
        response = self.client.post(
            "/api/growth_ai_enrichment/save/",
            {
                "label": "too_many_fields_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "input_fields": [f"field_{i}" for i in range(41)],
                "output_fields": _OUTPUT_FIELDS,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="too_many_fields_label").count(), 0)

    def test_save_has_no_mutation_endpoint_for_an_existing_version(self):
        # Versions are immutable: the freeze is enforced by this viewset simply never defining
        # update/partial_update/destroy, not by any runtime check, so there is no detail route
        # at all to send a mutation to.
        config = self._config(label="frozen_label", version="v1")

        for method in ("put", "patch", "delete"):
            response = getattr(self.client, method)(
                f"/api/growth_ai_enrichment/{config.id}/", {"prompt_text": "changed"}, format="json"
            )
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, method)
        config.refresh_from_db()
        self.assertEqual(config.prompt_text, "judge it. Email: {email}")

    def test_run_rechecks_consent_immediately_before_classification_and_skips_a_mid_run_revocation(self):
        # The sample is consent-filtered once, up front, at prefetch (_build_run_inputs) - but a
        # run streams over seconds to minutes, long enough for an admin to revoke consent after
        # that filter already ran. This organization passes the prefetch filter (consent approved
        # by default in APIBaseTest), so only classify_fetch_for_run's own recheck can catch it.
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = _mock_llm_client()

        with (
            patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=client),
            patch("products.growth.backend.enrichment.lab.ai_processing_approved", return_value=False),
        ):
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "mid_run_revoke_label",
                    "prompt_text": "x",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 1,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        verdict_rows = [row for row in rows if "summary" not in row]
        client.chat.completions.create.assert_not_called()
        self.assertTrue(verdict_rows[0]["meta"]["skipped"])

    @parameterized.expand(
        [
            ("too_many_fields", [{"key": f"f{i}", "type": "boolean"} for i in range(MAX_OUTPUT_FIELDS + 1)]),
            (
                "description_too_long",
                [{"key": "flag", "type": "boolean", "description": "x" * (MAX_OUTPUT_FIELD_DESCRIPTION_CHARS + 1)}],
            ),
        ]
    )
    def test_run_rejects_output_fields_over_the_caps(self, _name, output_fields):
        # Wiring guard for RunRequestSerializer: the boundary logic itself is proven in
        # TestSaveAndRunSerializerCaps without a request round trip, this only confirms the
        # viewset still surfaces that as a 400 on this endpoint too, same as /save/ above.
        response = self.client.post(
            "/api/growth_ai_enrichment/run/",
            {
                "label": "run_cap_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": output_fields,
                "sample": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_run_rejects_sample_over_the_max(self):
        # This endpoint spends real LLM money per sampled org - the max (10) must be enforced
        # before any candidates are fetched or any LLM client is built.
        response = self.client.post(
            "/api/growth_ai_enrichment/run/",
            {
                "label": "test_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "output_fields": _OUTPUT_FIELDS,
                "sample": 11,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "sample")

    def test_run_rejects_an_invalid_draft_config_with_400_not_500(self):
        # A config error (too many input_fields for bound_inputs to carry) must surface as a
        # normal 400 raised before streaming starts, not an unhandled 500 - and definitely not a
        # 200 stream that only reveals the problem mid-flight.
        response = self.client.post(
            "/api/growth_ai_enrichment/run/",
            {
                "label": "bad_config_label",
                "prompt_text": "x",
                "model": "gpt-5-mini",
                "input_fields": [f"field_{i}" for i in range(41)],
                "output_fields": _OUTPUT_FIELDS,
                "sample": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_run_constructs_its_client_with_max_retries_zero(self):
        # tenacity already owns retries inside classify_payload; the SDK's own retries stacking
        # on top would multiply spend on every 429 tenacity is already backing off from.
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = _mock_llm_client()

        with patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=client) as get_client:
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "test_label",
                    "prompt_text": "x",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 1,
                },
                format="json",
            )
            _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]

        get_client.assert_called_once_with(product="growth")
        client.with_options.assert_called_once_with(max_retries=0)

    def test_run_is_throttled_for_session_auth(self):
        # The global throttles are PersonalApiKeyRateThrottle subclasses, a structural no-op for
        # session-authenticated requests with no personal API key - this endpoint needs its own,
        # since each allowed call can cost several real LLM completions.
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        payload = {
            "label": "throttle_label",
            "prompt_text": "x",
            "model": "gpt-5-mini",
            "input_fields": ["name"],
            "output_fields": _OUTPUT_FIELDS,
            "sample": 1,
        }

        with patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=_mock_llm_client()):
            statuses = []
            for _ in range(11):
                response = self.client.post("/api/growth_ai_enrichment/run/", payload, format="json")
                if response.status_code == status.HTTP_200_OK:
                    _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
                statuses.append(response.status_code)

        self.assertEqual(statuses.count(status.HTTP_200_OK), 10)
        self.assertEqual(statuses[-1], status.HTTP_429_TOO_MANY_REQUESTS)


class TestAIEnrichmentRunClassification(NonAtomicAPIBaseTest):
    """/run/ hands each sampled fetch to a real ThreadPoolExecutor worker (classify_fetch_for_run,
    enrichment/lab.py), which opens its own DB connection to recheck consent. Under plain
    APIBaseTest (TestCase), that worker connection cannot see this test's own DB writes - they
    sit in TestCase's outer, never-committed transaction, invisible to any other connection - so
    a fresh query from the worker thread finds no such organization at all and the consent
    recheck false-negatives on every row. NonAtomicAPIBaseTest (TransactionTestCase) commits for
    real instead. Tests here are the ones whose assertions depend on classify_fetch_for_run
    actually reaching classify_payload; pure-validation and pre-streaming /run/ tests stay on the
    faster TestAIEnrichmentAPI above.

    CLASS_DATA_LEVEL_SETUP = False: TransactionTestCase flushes every table between tests (see
    _fixture_teardown), including the org/team/user setUpTestData creates - fixtures made once in
    setUpClass would only exist for this class's first test. Per-test setup recreates them fresh
    each time instead.
    """

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        lab_module._model_list_cache.update({"models": None, "expires_at": 0.0})

    def test_run_streams_ndjson_verdicts_for_an_unsaved_draft_and_persists_nothing(self):
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"name": "Acme", "contactEmail": "person@example.com"},
        )

        with patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=_mock_llm_client()):
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "unsaved_label",
                    "prompt_text": "a draft prompt. Email: {email}",
                    "model": "gpt-5-mini",
                    "input_fields": ["name", "contactEmail"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 5,
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
        # Only the domain reaches the prompt/stored record - to_domain/bound_inputs (labels.py)
        # must not be bypassed by this endpoint's own request-shape handling.
        self.assertEqual(verdict_rows[0]["inputs"], {"name": "Acme", "contactEmail": "example.com"})
        self.assertEqual(summary_row["summary"], {"classified": 1, "unknown": 0, "errors": 0})
        # "unsaved_label" must never touch the DB - run classifies an in-memory config only.
        self.assertEqual(EnrichmentPromptConfig.objects.filter(name="unsaved_label").count(), 0)
        self.assertEqual(EnrichmentLabelResult.objects.count(), 0)

    def test_run_reports_no_inputs_for_a_not_found_archived_payload(self):
        # classify_payload short-circuits on the miss sentinel before ever extracting a field -
        # a row for one must not display inputs the classifier never touched, even though "name"
        # is present in the raw payload and configured as an input field.
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"companyFound": False, "name": "Acme"},
        )

        with patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=_mock_llm_client()):
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "miss_label",
                    "prompt_text": "x",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 1,
                },
                format="json",
            )

        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        verdict_rows = [row for row in rows if "summary" not in row]
        self.assertEqual(verdict_rows[0]["inputs"], {})

    def test_run_reports_meta_skipped_for_a_skipped_row(self):
        # The frontend prefers meta.skipped over sniffing individual values for the literal
        # "unknown" string - this is the wire contract it depends on.
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"companyFound": False}
        )

        with patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=_mock_llm_client()):
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "skip_meta_label",
                    "prompt_text": "x",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 1,
                },
                format="json",
            )

        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        verdict_rows = [row for row in rows if "summary" not in row]
        self.assertTrue(verdict_rows[0]["meta"]["skipped"])
        self.assertEqual(verdict_rows[0]["outputs"]["is_ai"], "unknown")

    @parameterized.expand([("declined", False), ("unset", None)])
    def test_run_excludes_orgs_without_ai_processing_consent(self, _name, consent_value):
        # Matches the gate the batch runner and dry-run command apply per row
        # (ai_processing_approved) - a lab test run must not be a side door that sends an
        # unconsented org's data to the LLM just because it's a smaller sample.
        consented_org = self.organization
        OrganizationEnrichmentFetch.objects.create(
            organization=consented_org, provider="harmonic", payload={"name": "Acme"}
        )
        declined_org = Organization.objects.create(name="Declined Co", is_ai_data_processing_approved=consent_value)
        OrganizationEnrichmentFetch.objects.create(
            organization=declined_org, provider="harmonic", payload={"name": "Declined Co"}
        )
        client = _mock_llm_client()

        with patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=client):
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "consent_check_label",
                    "prompt_text": "x",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 10,
                },
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]
        companies = {row["company"] for row in rows if "summary" not in row}
        self.assertEqual(companies, {"Acme"})
        # Not just absent from the output - the declined org's payload must never have reached
        # the client at all.
        sent_payloads = [
            call.kwargs["messages"][1]["content"] for call in client.chat.completions.create.call_args_list
        ]
        self.assertTrue(all("Declined Co" not in payload for payload in sent_payloads))

    def test_run_captures_and_reports_a_per_row_failure_without_500ing_the_whole_stream(self):
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        failing_client = MagicMock()
        failing_client.with_options.return_value = failing_client
        failing_client.chat.completions.create.side_effect = RuntimeError("gateway timeout")

        # The patch must still be active while the stream is drained, not just during the POST:
        # classify_fetch_for_run runs in a thread-pool worker that only executes (and only then
        # calls capture_exception) once something actually iterates streaming_content.
        with (
            patch("products.growth.backend.api.ai_enrichment.get_llm_client", return_value=failing_client),
            patch("products.growth.backend.enrichment.lab.capture_exception") as mock_capture,
            patch("tenacity.nap.time.sleep"),
        ):
            response = self.client.post(
                "/api/growth_ai_enrichment/run/",
                {
                    "label": "flaky_label",
                    "prompt_text": "x",
                    "model": "gpt-5-mini",
                    "input_fields": ["name"],
                    "output_fields": _OUTPUT_FIELDS,
                    "sample": 1,
                },
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            rows = _drain_ndjson(response.streaming_content)  # type: ignore[attr-defined]

        verdict_rows = [row for row in rows if "summary" not in row]
        (summary_row,) = [row for row in rows if "summary" in row]
        self.assertIsNone(verdict_rows[0]["outputs"])
        self.assertIn("RuntimeError", verdict_rows[0]["error"])
        # Extraction happens before the LLM call, so a row that fails it still reports what would
        # have been sent - an empty "inputs sent" here would be a lie about what was attempted.
        self.assertEqual(verdict_rows[0]["inputs"], {"name": "Acme"})
        self.assertEqual(summary_row["summary"], {"classified": 0, "unknown": 0, "errors": 1})
        mock_capture.assert_called_once()


class TestRunError(SimpleTestCase):
    """No DB needed: _run_error is pure string formatting plus a capture_exception call."""

    def test_does_not_truncate_the_error_message_at_the_old_120_char_cap(self):
        long_message = "x" * 500
        config = EnrichmentPromptConfig(name="test_label", model="gpt-5-mini")

        with patch("products.growth.backend.enrichment.lab.capture_exception"):
            formatted = lab_module._run_error(config, RuntimeError(long_message), "test")

        self.assertIn(long_message, formatted)


class TestSaveAndRunSerializerCaps(SimpleTestCase):
    """Field-level max_length/count caps run inside is_valid()'s to_internal_value phase, before
    the object-level validate() that needs a request context - no DB needed. The /save/ and
    /run/ 400 tests above are the wiring guard that each viewset still calls is_valid() at all;
    these are the boundary tests themselves, run once per request serializer since
    SaveRequestSerializer and RunRequestSerializer each declare prompt_text's max_length and
    output_fields independently, even though both delegate to the same shared helpers."""

    def _valid_payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "label": "cap_test_label",
            "prompt_text": "judge it.",
            "model": "gpt-5-mini",
            "output_fields": [{"key": "flag", "type": "boolean", "description": ""}],
        }
        payload.update(overrides)
        return payload

    @parameterized.expand([("save", SaveRequestSerializer), ("run", RunRequestSerializer)])
    def test_prompt_text_over_the_char_cap_is_rejected(self, _name, serializer_class):
        serializer = serializer_class(data=self._valid_payload(prompt_text="x" * (MAX_PROMPT_TEXT_CHARS + 1)))

        self.assertFalse(serializer.is_valid())
        self.assertEqual(serializer.errors["prompt_text"][0].code, "max_length")

    @parameterized.expand([("save", SaveRequestSerializer), ("run", RunRequestSerializer)])
    def test_prompt_text_at_the_char_cap_is_accepted(self, _name, serializer_class):
        serializer = serializer_class(data=self._valid_payload(prompt_text="x" * MAX_PROMPT_TEXT_CHARS))

        self.assertTrue(serializer.is_valid(), serializer.errors)

    @parameterized.expand([("save", SaveRequestSerializer), ("run", RunRequestSerializer)])
    def test_output_fields_over_the_count_cap_is_rejected(self, _name, serializer_class):
        too_many = [{"key": f"field_{i}", "type": "boolean", "description": ""} for i in range(MAX_OUTPUT_FIELDS + 1)]
        serializer = serializer_class(data=self._valid_payload(output_fields=too_many))

        self.assertFalse(serializer.is_valid())
        self.assertIn(f"At most {MAX_OUTPUT_FIELDS}", str(serializer.errors["output_fields"]))

    @parameterized.expand([("save", SaveRequestSerializer), ("run", RunRequestSerializer)])
    def test_output_fields_at_the_count_cap_is_accepted(self, _name, serializer_class):
        exactly_max = [{"key": f"field_{i}", "type": "boolean", "description": ""} for i in range(MAX_OUTPUT_FIELDS)]
        serializer = serializer_class(data=self._valid_payload(output_fields=exactly_max))

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_output_field_description_over_the_char_cap_is_rejected(self):
        serializer = OutputFieldSerializer(
            data={"key": "flag", "type": "boolean", "description": "x" * (MAX_OUTPUT_FIELD_DESCRIPTION_CHARS + 1)}
        )

        self.assertFalse(serializer.is_valid())
        self.assertEqual(serializer.errors["description"][0].code, "max_length")

    def test_output_field_description_at_the_char_cap_is_accepted(self):
        serializer = OutputFieldSerializer(
            data={"key": "flag", "type": "boolean", "description": "x" * MAX_OUTPUT_FIELD_DESCRIPTION_CHARS}
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    @parameterized.expand([("save", SaveRequestSerializer), ("run", RunRequestSerializer)])
    def test_output_field_description_cap_propagates_through_the_nested_list(self, _name, serializer_class):
        # OutputFieldSerializer is nested (many=True) under both request serializers - this
        # confirms the cap actually reaches a caller through that nesting, not just when
        # OutputFieldSerializer is exercised standalone above.
        too_long = [{"key": "flag", "type": "boolean", "description": "x" * (MAX_OUTPUT_FIELD_DESCRIPTION_CHARS + 1)}]
        serializer = serializer_class(data=self._valid_payload(output_fields=too_long))

        self.assertFalse(serializer.is_valid())
        self.assertIn("description", serializer.errors["output_fields"][0])
