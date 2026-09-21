import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.growth.backend.api.scoring_serializers import ScoringPreviewRequestSerializer
from products.growth.backend.enrichment.icp_lists import clear_lists_cache, load_active_lists
from products.growth.backend.models import (
    EnrichmentLabelResult,
    EnrichmentPromptConfig,
    IcpScoringConfig,
    OrganizationEnrichment,
    OrganizationEnrichmentFetch,
)

_API = "/api/growth_enrichment_scoring/"
_FORMULA = (
    "return { 'status': 'scored', 'score': if(ai_pilled, 15, 0), 'components': { 'ai_pilled': if(ai_pilled, 15, 0) } };"
)


class TestScoringRequest(SimpleTestCase):
    @parameterized.expand([("empty", "", 10), ("syntax", "return {", 10), ("sample", _FORMULA, 11)])
    def test_invalid_preview_is_rejected(self, _name: str, source: str, sample: int) -> None:
        serializer = ScoringPreviewRequestSerializer(
            data={"source": source, "sample": sample, "base_config_id": "00000000-0000-4000-8000-000000000001"}
        )
        assert not serializer.is_valid()


class TestScoringAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.email = "engineer@inventory.example.com"
        self.user.save()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        clear_lists_cache()
        self.addCleanup(clear_lists_cache)
        self.config = IcpScoringConfig.objects.create(
            version="initial",
            scoring_rules={"source": "return { 'status': 'scored', 'score': 3, 'components': { 'ai_pilled': 3 } };"},
            tags=[{"tag": "Inventory", "recommendation": "software_positive"}],
            quality_investors=[{"investor": "Example Ventures", "aliases": []}],
            is_active=True,
            created_by=self.user,
        )
        self.fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"id": "synthetic-inventory", "name": "Inventory Example", "headcount": 12},
        )
        EnrichmentPromptConfig.objects.filter(name="ai_pilled").update(is_active=False)
        prompt = EnrichmentPromptConfig.objects.create(
            name="ai_pilled",
            version="test",
            prompt_text="Classify the company.",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=[{"key": "ai_pilled", "type": "boolean"}],
            is_active=True,
        )
        self.label = EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=self.fetch,
            label_name=prompt.name,
            prompt_version=prompt.version,
            prompt_hash=prompt.content_hash,
            model=prompt.model,
            output={"ai_pilled": True},
            inputs={"signup_domain": "inventory.example.com"},
        )
        self.record = OrganizationEnrichment.objects.create(
            organization=self.organization, data={"icp_fit_score": 3, "signup_role": "engineering"}
        )

    @parameterized.expand([("configs", "get"), ("preview", "post"), ("save", "post"), ("activate", "post")])
    def test_non_staff_cannot_read_or_change_scoring(self, action: str, method: str) -> None:
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        assert getattr(self.client, method)(_API + action + "/").status_code == 403

    @parameterized.expand([("positive", True), ("revoked", False)])
    def test_preview_uses_saved_inputs_without_writing_or_calling_providers(self, _name: str, approved: bool) -> None:
        self.organization.is_ai_data_processing_approved = approved
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        with (
            patch("products.growth.backend.enrichment.labels._complete") as complete,
            patch("products.growth.backend.enrichment.tools.run_tool") as tool,
        ):
            result = self.client.post(
                _API + "preview/",
                {"source": _FORMULA, "sample": 10, "base_config_id": str(self.config.id)},
                format="json",
            )
        assert result.status_code == 200, result.json()
        body = result.json()
        assert body["summary"] == {"evaluated": 1, "changed": 1, "errors": 0}
        row = body["results"][0]
        assert row["company"] == "Inventory Example"
        assert row["inputs"]["ai_pilled"] is approved
        assert row["active"]["score"] == 3
        assert row["preview"]["score"] == (15 if approved else 0)
        self.record.refresh_from_db()
        assert self.record.data == {"icp_fit_score": 3, "signup_role": "engineering"}
        assert IcpScoringConfig.objects.count() == 1
        assert EnrichmentLabelResult.objects.count() == 1
        complete.assert_not_called()
        tool.assert_not_called()

    def test_preview_uses_the_selected_lists_and_label_names(self) -> None:
        selected = IcpScoringConfig.objects.create(
            version="selected",
            tags=[{"tag": "Inventory", "recommendation": "ai_positive"}],
            scoring_rules={"ai_labels": ["experimental_ai"]},
        )
        source = """
            let points := if(has(lists.ai_positive, 'inventory'), 10, 0) + if(ai_pilled, 5, 0);
            return {'status': 'scored', 'score': points, 'components': {'custom': points}};
        """
        result = self.client.post(
            _API + "preview/", {"source": source, "base_config_id": str(selected.id)}, format="json"
        )
        assert result.status_code == 200, result.json()
        row = result.json()["results"][0]
        assert row["active"]["score"] == 3
        assert row["preview"]["score"] == 10
        assert row["inputs"]["lists"]["ai_positive"] == ["inventory"]
        assert row["inputs"]["ai_pilled"] is False
        assert result.json()["summary"] == {"evaluated": 1, "changed": 1, "errors": 0}

        unchanged = self.client.post(
            _API + "preview/",
            {"source": self.config.scoring_rules["source"], "base_config_id": str(selected.id)},
            format="json",
        )
        assert unchanged.status_code == 200, unchanged.json()
        assert unchanged.json()["summary"] == {"evaluated": 1, "changed": 0, "errors": 0}

    @parameterized.expand([("low_confidence", True, False), ("dq_reason", "role=student", "company_type=SCHOOL")])
    def test_preview_reports_metadata_changes_without_score_changes(
        self, field: str, before: bool | str, after: bool | str
    ) -> None:
        result = (
            {"status": "scored", "score": 3, "components": {"ai_pilled": 3}}
            if field == "low_confidence"
            else {"status": "disqualified", "score": 0}
        )
        IcpScoringConfig.objects.filter(pk=self.config.pk).update(
            scoring_rules={"source": f"return jsonParse('{json.dumps({**result, field: before})}');"}
        )
        response = self.client.post(
            _API + "preview/",
            {
                "source": f"return jsonParse('{json.dumps({**result, field: after})}');",
                "base_config_id": str(self.config.id),
            },
            format="json",
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["summary"] == {"evaluated": 1, "changed": 1, "errors": 0}
        row = body["results"][0]
        assert row["active"]["score"] == row["preview"]["score"]
        assert row["active"][field] == before
        assert row["preview"][field] == after

    @parameterized.expand([("draft", False), ("active", True)])
    def test_runtime_error_is_a_visible_row_failure_and_preserves_scores(self, _name: str, active_error: bool) -> None:
        if active_error:
            self.config.scoring_rules = {"source": "return 'invalid score';"}
            IcpScoringConfig.objects.filter(pk=self.config.pk).update(scoring_rules=self.config.scoring_rules)
        result = self.client.post(
            _API + "preview/",
            {"source": _FORMULA if active_error else "return 'invalid score';", "base_config_id": str(self.config.id)},
            format="json",
        )
        assert result.status_code == 200
        row = result.json()["results"][0]
        if active_error:
            assert row["active"] is None
            assert row["preview"]["score"] == 15
        else:
            assert row["active"]["score"] == 3
            assert row["preview"] is None
        assert row["error"]
        self.record.refresh_from_db()
        assert self.record.data["icp_fit_score"] == 3

    def test_invalid_formula_does_not_create_a_version(self) -> None:
        result = self.client.post(
            _API + "save/",
            {"source": "return {", "version": "bad", "base_config_id": str(self.config.id)},
            format="json",
        )
        assert result.status_code == 400
        assert IcpScoringConfig.objects.count() == 1

    def test_save_clones_lists_and_activation_changes_the_cached_formula(self) -> None:
        original = load_active_lists()
        assert original is not None and original.version == "initial"
        payload = {"source": _FORMULA, "version": "candidate", "base_config_id": str(self.config.id)}
        saved = self.client.post(_API + "save/", payload, format="json")
        assert saved.status_code == 201, saved.json()
        candidate = IcpScoringConfig.objects.get(pk=saved.json()["id"])
        assert candidate.tags == self.config.tags
        assert candidate.quality_investors == self.config.quality_investors
        assert candidate.created_by == self.user
        assert not candidate.is_active
        assert self.client.post(_API + "save/", payload, format="json").status_code == 409
        listed = self.client.get(_API + "configs/").json()
        assert listed["results"][0]["source"] == _FORMULA
        activated = self.client.post(_API + "activate/", {"config_id": str(candidate.id)}, format="json")
        assert activated.status_code == 200, activated.json()
        active = load_active_lists()
        assert active is not None and active.version == "candidate"
        assert active.rules.source == _FORMULA
        self.config.refresh_from_db()
        assert not self.config.is_active
        assert self.config.scoring_rules != candidate.scoring_rules
