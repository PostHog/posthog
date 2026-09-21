import json
import datetime as dt
from types import SimpleNamespace
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from asgiref.sync import async_to_sync
from parameterized import parameterized
from posthoganalytics.client import Client
from requests import Timeout

from posthog.egress.firecrawl.client import FirecrawlScrape
from posthog.models.organization import Organization, OrganizationMembership

from products.growth.backend.enrichment.bridge import OrganizationBridgeInputs, WizardBridgeInputs
from products.growth.backend.enrichment.context import EnrichmentContext, EnrichmentPhase
from products.growth.backend.enrichment.core import enrich_organization
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_recomputation import apply_ai_pilled_label
from products.growth.backend.enrichment.icp_lists import clear_lists_cache
from products.growth.backend.enrichment.providers import ProviderLookup
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    IcpScoringConfig,
    OrganizationEnrichment,
    OrganizationEnrichmentFetch,
)

_BACKFILL = "products.growth.backend.management.commands.backfill_icp_fit_scores"


class TestAiPilledScoreApplication(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.email = "engineer@sample.example.com"
        self.user.save(update_fields=["email"])
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        EnrichmentPromptConfig.objects.filter(name="ai_pilled").update(is_active=False)
        self.config = EnrichmentPromptConfig.objects.create(
            name="ai_pilled",
            version="label-v1",
            prompt_text="Classify the company at {email}.",
            model="gpt-5-mini",
            input_fields=["description"],
            output_fields=[
                {"key": "ai_pilled", "type": "boolean"},
                {"key": "reasoning", "type": "string"},
                {"key": "evidence_url", "type": "string"},
            ],
            is_active=True,
        )
        IcpScoringConfig.objects.create(version="test-lists", tags=[], quality_investors=[], is_active=True)
        clear_lists_cache()
        self.fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"id": "synthetic-company", "headcount": 8, "description": "Tools for inventory teams."},
        )
        self.url = "https://sample.example.com/product"
        self.label = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=self.fetch,
            label_name=self.config.name,
            prompt_version=self.config.version,
            prompt_hash=self.config.content_hash,
            model=self.config.model,
            output={
                "ai_pilled": True,
                "reasoning": "The company sells an AI assistant for inventory teams.",
                "evidence_url": self.url,
            },
            inputs={
                "signup_domain": "sample.example.com",
                "fields": {"description": self.fetch.payload["description"]},
            },
        )

    def tearDown(self):
        clear_lists_cache()
        super().tearDown()

    def _backfill(self):
        client = MagicMock()
        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch(f"{_BACKFILL}.get_regional_ph_client", return_value=client),
            patch(f"{_BACKFILL}.read_organization_bridge_inputs", return_value=OrganizationBridgeInputs()),
        ):
            call_command("backfill_icp_fit_scores", delay=0)
        return OrganizationEnrichment.objects.get(organization=self.organization), client

    def _additional_label(self):
        organization = Organization.objects.create(name="Synthetic inventory team")
        Organization.objects.filter(pk=organization.pk).update(is_ai_data_processing_approved=True)
        OrganizationMembership.objects.create(organization=organization, user=self.user)
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=organization, provider="harmonic", payload=self.fetch.payload
        )
        return EnrichmentLabelResult.objects.create(
            organization=organization,
            fetch=fetch,
            label_name=self.config.name,
            prompt_version=self.config.version,
            prompt_hash=self.config.content_hash,
            model=self.config.model,
            output=self.label.output,
            inputs=self.label.inputs,
        )

    @parameterized.expand(
        [
            ("signup", EnrichmentPhase.AT_SIGNUP, True),
            ("sweep", EnrichmentPhase.SWEEP, True),
            ("recheck_before_label", EnrichmentPhase.RECHECK, False),
        ]
    )
    def test_runtime_uses_only_the_label_for_its_current_fetch(self, _name, phase, label_ready):
        record, _ = self._backfill()
        assert record.data["icp_fit_score"] == 15
        payload = {"companyFound": True, "headcount": 8, "description": "Tools for inventory teams."}
        provider = MagicMock()
        provider.name = "harmonic"
        provider.enrich_by_domain = AsyncMock(
            return_value=ProviderLookup(fields=EnrichmentFields(headcount=8), raw_payload=payload)
        )
        client = MagicMock()

        def bridge_inputs(**kwargs):
            if label_ready:
                fetch = (
                    OrganizationEnrichmentFetch.objects.filter(organization=self.organization)
                    .exclude(pk=self.fetch.pk)
                    .get()
                )
                EnrichmentLabelResult.objects.create(
                    organization=self.organization,
                    fetch=fetch,
                    label_name=self.config.name,
                    prompt_version=self.config.version,
                    prompt_hash=self.config.content_hash,
                    model=self.config.model,
                    output=self.label.output,
                    inputs=self.label.inputs,
                )
            return OrganizationBridgeInputs()

        with (
            patch("products.growth.backend.enrichment.core.read_organization_bridge_inputs", side_effect=bridge_inputs),
            patch("products.growth.backend.enrichment.core.get_person_by_distinct_id", return_value=None),
        ):
            outcome = async_to_sync(enrich_organization)(
                EnrichmentContext(
                    organization_id=str(self.organization.id),
                    domain="sample.example.com",
                    phase=phase,
                    distinct_id=self.user.distinct_id,
                ),
                provider=provider,
                pha_client=client,
            )

        assert outcome.fit is not None and outcome.fit.score == (15 if label_ready else 0)
        record.refresh_from_db()
        assert ("icp_fit_ai_label_result_id" in record.data) is label_ready
        client.flush.assert_not_called()

    @parameterized.expand([("delivered", False), ("timed_out", True)])
    def test_label_projection_uses_bounded_synchronous_requests(self, _name, timed_out):
        clients = []
        session = MagicMock()
        session.post.return_value.status_code = 200
        if timed_out:
            session.post.side_effect = Timeout("synthetic delivery timeout")

        def regional_client(**kwargs):
            kwargs.setdefault("max_retries", 0)
            client = Client("phc_synthetic", host="https://sdk.example.com", **kwargs)
            clients.append(client)
            return client

        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client",
                side_effect=regional_client,
            ),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
            patch("posthoganalytics.request._get_session", return_value=session),
        ):
            if timed_out:
                with self.assertRaises(RuntimeError):
                    apply_ai_pilled_label(self.label)
            else:
                assert apply_ai_pilled_label(self.label)

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert ("icp_fit_ai_label_projected_result_id" in record.data) is not timed_out
        assert clients[0].sync_mode is True
        assert session.post.call_count == (1 if timed_out else 2)
        assert all(call.kwargs["timeout"] == 10 for call in session.post.call_args_list)

    @parameterized.expand([("matched", None), ("latest_not_found", {"companyFound": False}), ("latest_empty", {})])
    def test_batch_retries_score_projection_without_reclassifying(self, _name, missing_payload):
        if missing_payload is not None:
            self.fetch.payload["description"] = "An AI assistant for shelf audits."
            self.fetch.save(update_fields=["payload"])
            self.label.delete()
            self.fetch = OrganizationEnrichmentFetch.objects.create(
                organization=self.organization, provider="harmonic", payload=missing_payload
            )
            self.label = EnrichmentLabelResult.objects.create(
                organization=self.organization,
                fetch=self.fetch,
                label_name=self.config.name,
                prompt_version=self.config.version,
                prompt_hash=self.config.content_hash,
                model=self.config.model,
                output={"ai_pilled": "unknown", "meta": {"skipped": "missing or empty archived payload"}},
                inputs={"signup_domain": "sample.example.com", "fields": {}},
            )
        gateway = MagicMock()
        gateway.with_options.return_value = gateway
        client = MagicMock()
        fail_delivery = True

        def regional_client(**kwargs):
            def deliver(*_args, **_kwargs):
                if fail_delivery:
                    kwargs["on_error"](RuntimeError("synthetic transport failure"), [])
                return "event"

            client.group_identify.side_effect = deliver
            return client

        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client",
                side_effect=regional_client,
            ),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
            patch(
                "products.growth.backend.management.commands.enrichment_label_batch.get_llm_client",
                return_value=gateway,
            ),
        ):
            with self.assertRaises(CommandError):
                call_command("enrichment_label_batch", label="ai_pilled", workers=1)
            record = OrganizationEnrichment.objects.get(organization=self.organization)
            assert record.data["icp_fit_score"] == 15
            assert "icp_fit_ai_label_projected_result_id" not in record.data

            fail_delivery = False
            call_command("enrichment_label_batch", label="ai_pilled", workers=1)
            record.refresh_from_db()
            assert record.data["icp_fit_ai_label_projected_result_id"] == str(self.label.id)
            assert record.data["icp_fit_evaluation_kind"] == "ai_label"
            if missing_payload is not None:
                assert "ai_pilled_label" not in record.data["icp_fit_flags"]

        assert EnrichmentLabelResult.objects.filter(organization=self.organization).count() == 1
        gateway.chat.completions.create.assert_not_called()
        assert client.group_identify.call_count == 2

    @parameterized.expand([("ai_pilled",), ("reviewed_ai",)])
    def test_batch_classifies_and_applies_positive_result(self, label_name):
        self.config.name = label_name
        self.config.save(update_fields=["name"])
        IcpScoringConfig.objects.filter(is_active=True).update(scoring_rules={"ai_labels": [label_name]})
        clear_lists_cache()
        output = self.label.output.copy()
        self.label.delete()
        gateway = MagicMock()
        gateway.with_options.return_value = gateway
        tool_call = SimpleNamespace(
            id="read-evidence",
            function=SimpleNamespace(name="fetch_page", arguments=json.dumps({"url": self.url})),
        )
        responses = [MagicMock(), MagicMock()]
        responses[0].choices[0].message.tool_calls = [tool_call]
        responses[0].choices[0].message.content = None
        responses[1].choices[0].message.tool_calls = None
        responses[1].choices[0].message.content = json.dumps(output)
        gateway.chat.completions.create.side_effect = responses

        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client", return_value=MagicMock()
            ),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
            patch(
                "products.growth.backend.management.commands.enrichment_label_batch.get_llm_client",
                return_value=gateway,
            ),
            patch(
                "products.growth.backend.enrichment.tools.scrape",
                return_value=FirecrawlScrape(url=self.url, markdown=output["reasoning"], status_code=200),
            ),
        ):
            call_command("enrichment_label_batch", label=label_name, workers=1)

        label = EnrichmentLabelResult.objects.get(organization=self.organization)
        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert label.output["reasoning"] == output["reasoning"]
        assert record.data["icp_fit_score"] == 15
        assert record.data["icp_fit_ai_label_projected_result_id"] == str(label.id)
        assert OrganizationEnrichmentFetch.objects.filter(organization=self.organization).count() == 1
        assert gateway.chat.completions.create.call_count == 2

    @parameterized.expand([("before_retry", False), ("during_delivery", True)])
    def test_reapplies_a_label_after_scoring_configuration_changes(self, _name, during_delivery):
        client = MagicMock()

        def activate_new_configuration(**kwargs):
            IcpScoringConfig.objects.filter(is_active=True).update(is_active=False)
            IcpScoringConfig.objects.create(version="test-lists-v2", tags=[], quality_investors=[], is_active=True)
            clear_lists_cache()
            return "event"

        if during_delivery:
            client.set.side_effect = activate_new_configuration
        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch("products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client", return_value=client),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
        ):
            assert apply_ai_pilled_label(self.label) is (not during_delivery)
            if not during_delivery:
                activate_new_configuration()
            client.set.side_effect = None
            assert apply_ai_pilled_label(self.label)

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_lists_version"] == "test-lists-v2"
        assert record.data["icp_fit_ai_label_projected_result_id"] == str(self.label.id)
        assert client.group_identify.call_count == 2

    @parameterized.expand([("nondefault_label", "reviewed_ai", 15), ("disallowed_label", "ai_pilled", 0)])
    def test_scoring_configuration_selects_eligible_label_names(self, _name, label_name, expected_score):
        self.config.name = label_name
        self.config.save(update_fields=["name"])
        self.label.label_name = label_name
        self.label.save(update_fields=["label_name"])
        IcpScoringConfig.objects.filter(is_active=True).update(scoring_rules={"ai_labels": ["reviewed_ai"]})
        clear_lists_cache()

        record, _ = self._backfill()

        assert record.data["icp_fit_score"] == expected_score
        assert ("ai_pilled_label" in record.data["icp_fit_flags"]) is (expected_score > 0)

    def test_positive_second_label_prevents_alternating_score_repair(self):
        second_config = EnrichmentPromptConfig.objects.create(
            name="reviewed_ai",
            version=self.config.version,
            prompt_text=self.config.prompt_text,
            model=self.config.model,
            input_fields=self.config.input_fields,
            output_fields=self.config.output_fields,
            is_active=True,
        )
        positive = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=self.fetch,
            label_name=second_config.name,
            prompt_version=second_config.version,
            prompt_hash=second_config.content_hash,
            model=second_config.model,
            output=self.label.output,
            inputs=self.label.inputs,
        )
        self.label.output = {"ai_pilled": False}
        self.label.save(update_fields=["output"])
        IcpScoringConfig.objects.filter(is_active=True).update(
            scoring_rules={"ai_labels": ["ai_pilled", "reviewed_ai"]}
        )
        clear_lists_cache()
        client = MagicMock()
        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch("products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client", return_value=client),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
        ):
            assert not apply_ai_pilled_label(self.label)
            assert apply_ai_pilled_label(positive)
            assert not apply_ai_pilled_label(self.label)
            assert not apply_ai_pilled_label(positive)

        record = OrganizationEnrichment.objects.get(organization=self.organization)
        assert record.data["icp_fit_score"] == 15
        assert record.data["icp_fit_ai_label_projected_result_id"] == str(positive.id)
        assert record.data["icp_fit_flags"]["ai_pilled_label"]["result_id"] == str(positive.id)
        assert client.group_identify.call_count == 1

    @parameterized.expand([("limit", 1, 25), ("failure_streak", None, 1)])
    def test_existing_result_reconciliation_is_bounded(self, _name, limit, max_failures):
        self._additional_label()
        gateway = MagicMock()
        gateway.with_options.return_value = gateway
        client = MagicMock()
        client.group_identify.side_effect = RuntimeError("synthetic projection outage")

        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch("products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client", return_value=client),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
            patch(
                "products.growth.backend.management.commands.enrichment_label_batch.get_llm_client",
                return_value=gateway,
            ),
        ):
            with self.assertRaises(CommandError):
                call_command(
                    "enrichment_label_batch", label="ai_pilled", workers=1, limit=limit, max_failures=max_failures
                )

        assert client.group_identify.call_count == 1
        gateway.chat.completions.create.assert_not_called()

    @parameterized.expand([("consent",), ("signup_user_left",), ("domain",)])
    def test_ineligible_stored_result_does_not_exhaust_repair_limit(self, reason):
        eligible = self._additional_label()
        if reason == "consent":
            Organization.objects.filter(pk=self.organization.pk).update(is_ai_data_processing_approved=False)
        elif reason == "signup_user_left":
            OrganizationMembership.objects.filter(organization=self.organization).update(
                joined_at=self.organization.created_at + dt.timedelta(minutes=6)
            )
        else:
            self.label.inputs["signup_domain"] = "another.example.com"
            self.label.save(update_fields=["inputs"])
        gateway = MagicMock()
        gateway.with_options.return_value = gateway

        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client", return_value=MagicMock()
            ),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                return_value=OrganizationBridgeInputs(),
            ),
            patch(
                "products.growth.backend.management.commands.enrichment_label_batch.get_llm_client",
                return_value=gateway,
            ),
            patch("products.growth.backend.management.commands.enrichment_label_batch._ID_BATCH_SIZE", 1),
        ):
            call_command("enrichment_label_batch", label="ai_pilled", workers=1, limit=1)

        record = OrganizationEnrichment.objects.get(organization=eligible.organization)
        assert record.data["icp_fit_ai_label_projected_result_id"] == str(eligible.id)
        gateway.chat.completions.create.assert_not_called()

    @parameterized.expand([("delivered", False), ("partial_failure", True)])
    def test_stale_delivery_reopens_the_current_projection(self, _name, fail_delivery):
        self.label.output["ai_pilled"] = False
        self.label.save(update_fields=["output"])
        clients = [MagicMock() for _ in range(3)]
        delivered: dict[str, dict[str, Any]] = {}

        def deliver_event(target: str, properties: dict[str, Any]) -> str:
            delivered[target] = properties
            return "event"

        for client in clients:
            client.group_identify.side_effect = lambda *args, **kwargs: deliver_event("group", kwargs["properties"])
            client.set.side_effect = lambda *args, **kwargs: deliver_event("person", kwargs["properties"])

        def deliver_stale(*args, **kwargs):
            assert apply_ai_pilled_label(self.label)
            deliver_event("group", kwargs["properties"])
            if fail_delivery:
                raise RuntimeError("synthetic partial delivery")
            return "event"

        clients[0].group_identify.side_effect = deliver_stale
        with (
            patch("products.growth.backend.enrichment.gates.get_instance_region", return_value="US"),
            patch("products.growth.backend.enrichment.gates.enrichment_enabled", return_value=True),
            patch("products.growth.backend.enrichment.fit_recomputation.get_regional_ph_client", side_effect=clients),
            patch(
                "products.growth.backend.enrichment.fit_recomputation.read_organization_bridge_inputs",
                side_effect=[OrganizationBridgeInputs()]
                + [OrganizationBridgeInputs(wizard=WizardBridgeInputs(ai_sdk_detected=True))] * 2,
            ),
        ):
            if fail_delivery:
                with self.assertRaises(RuntimeError):
                    apply_ai_pilled_label(self.label)
            else:
                assert not apply_ai_pilled_label(self.label)
            record = OrganizationEnrichment.objects.get(organization=self.organization)
            assert record.data["icp_fit_score"] == 15
            assert "icp_fit_ai_label_projected_result_id" not in record.data
            assert delivered["group"]["icp_fit_score"] == 0

            assert apply_ai_pilled_label(self.label)

        assert delivered["group"]["icp_fit_score"] == 15
        assert delivered["person"]["icp_fit_score"] == 15

    def test_positive_label_changes_only_ai_component(self):
        record, client = self._backfill()

        assert record.data["icp_fit_score"] == 15
        assert record.data["icp_fit_components"]["ai_pilled"] == 15
        assert record.data["icp_fit_ai_label_result_id"] == str(self.label.id)
        assert record.data["icp_fit_flags"]["ai_pilled_label"] == {
            "result_id": str(self.label.id),
            "fetch_id": str(self.fetch.id),
            "prompt_version": self.config.version,
            "prompt_hash": self.config.content_hash,
        }
        assert "icp_score" not in record.data
        assert client.group_identify.call_args.kwargs["properties"]["icp_fit_score"] == 15
        record.data["icp_fit_ai_label_projected_result_id"] = str(self.label.id)
        record.save(update_fields=["data"])
        record, _ = self._backfill()
        assert "icp_fit_ai_label_projected_result_id" not in record.data

    @parameterized.expand(
        [
            ("alternate_domain", {"evidence_url": "https://another.example.com/company"}),
            ("encoded_quote", {"evidence_quote": "Build &amp; review", "meta": {"evidence_quote_verified": False}}),
            ("missing_citation", None),
            ("research_metadata", {"evidence_status": "insufficient", "evidence_type": "none"}),
        ]
    )
    def test_positive_label_scores_without_citation_checks(self, _name, details):
        if details is None:
            self.label.output = {"ai_pilled": True}
        else:
            self.label.output.update(details)
        self.label.save(update_fields=["output"])

        record, _ = self._backfill()

        assert record.data["icp_fit_score"] == 15
        assert record.data["icp_fit_flags"]["ai_pilled_label"]["result_id"] == str(self.label.id)
        self.label.refresh_from_db()
        if details is not None:
            assert all(self.label.output[key] == value for key, value in details.items())

    @parameterized.expand(
        [
            ("inactive",),
            ("hash_changed",),
            ("new_fetch",),
            ("domain_changed",),
            ("no_consent",),
            ("negative",),
            ("skipped",),
            ("version_changed",),
        ]
    )
    def test_invalidated_label_stops_contributing(self, invalidation):
        record, _ = self._backfill()
        assert record.data["icp_fit_score"] == 15

        if invalidation == "inactive":
            self.config.is_active = False
            self.config.save(update_fields=["is_active"])
        elif invalidation == "hash_changed":
            self.label.prompt_hash = "v2:retired"
        elif invalidation == "new_fetch":
            OrganizationEnrichmentFetch.objects.create(
                organization=self.organization, provider="harmonic", payload=self.fetch.payload
            )
        elif invalidation == "domain_changed":
            self.label.inputs["signup_domain"] = "another.example.com"
        elif invalidation == "no_consent":
            type(self.organization).objects.filter(pk=self.organization.pk).update(is_ai_data_processing_approved=False)
        elif invalidation == "negative":
            self.label.output["ai_pilled"] = False
        elif invalidation == "skipped":
            self.label.output["meta"] = {"skipped": "missing input"}
        elif invalidation == "version_changed":
            self.config.version = "label-v2"
            self.config.save(update_fields=["version"])
        self.label.save(update_fields=["prompt_hash", "inputs", "output"])

        record, _ = self._backfill()

        assert record.data["icp_fit_score"] == 0
        assert "ai_pilled_label" not in record.data["icp_fit_flags"]
