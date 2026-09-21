import io
import json
import tempfile
from pathlib import Path

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin import AdminSite
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory

from parameterized import parameterized

from products.growth.backend.admin import IcpScoringConfigAdmin
from products.growth.backend.enrichment.icp_lists import clear_lists_cache, load_active_lists
from products.growth.backend.enrichment.scoring_rules import default_scoring_rules
from products.growth.backend.models import IcpScoringConfig, OrganizationEnrichment, OrganizationEnrichmentFetch


class TestIcpScoringConfigLifecycle(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(clear_lists_cache)
        clear_lists_cache()
        self.config = IcpScoringConfig.objects.create(
            version="initial",
            tags=[{"tag": "Invented category", "recommendation": "software_positive"}],
            quality_investors=[{"investor": "Example Ventures", "aliases": []}],
            scoring_rules={"ai_sources": ["wizard"]},
            is_active=True,
        )
        self.admin = IcpScoringConfigAdmin(IcpScoringConfig, AdminSite())
        self.request = RequestFactory().get("/admin/growth/icpscoringconfig/add/")
        self.user.is_staff = True
        self.request.user = self.user

    @parameterized.expand(
        [
            ("version", "replaced"),
            ("tags", []),
            ("quality_investors", []),
            ("scoring_rules", {}),
            ("is_active", False),
        ]
    )
    def test_saved_versions_cannot_be_changed(self, field: str, value: object) -> None:
        setattr(self.config, field, value)
        with self.assertRaises(ValidationError):
            self.config.save()
        self.config.refresh_from_db()
        assert self.config.version == "initial"
        assert self.config.scoring_rules == {"ai_sources": ["wizard"]}
        assert self.config.is_active is True

    def test_activation_replaces_the_active_config_and_clears_cached_policy(self) -> None:
        active = load_active_lists()
        assert active is not None and active.version == "initial"
        candidate = IcpScoringConfig.objects.create(version="candidate", scoring_rules={"ai_sources": []})

        candidate.activate()

        active = load_active_lists()
        assert active is not None and active.version == "candidate"
        self.config.refresh_from_db()
        assert self.config.is_active is False
        assert IcpScoringConfig.objects.filter(is_active=True).count() == 1

    def test_invalid_rules_cannot_be_created_or_activated(self) -> None:
        invalid = {"ai_sources": ["unrecognized"]}
        with self.assertRaises(ValidationError):
            IcpScoringConfig.objects.create(version="invalid", scoring_rules=invalid)
        candidate = IcpScoringConfig.objects.create(version="candidate")
        IcpScoringConfig.objects.filter(pk=candidate.pk).update(scoring_rules=invalid)

        with self.assertRaises(ValidationError):
            candidate.activate()

        self.config.refresh_from_db()
        assert self.config.is_active is True

    def test_admin_clones_policy_into_an_inactive_new_version(self) -> None:
        assert self.admin.has_add_permission(self.request)
        initial = self.admin.get_changeform_initial_data(self.request)
        assert initial["tags"] == self.config.tags
        assert initial["quality_investors"] == self.config.quality_investors
        expected_rules = {**default_scoring_rules(), **self.config.scoring_rules}
        assert initial["scoring_rules"] == expected_rules
        assert not initial.get("version")
        candidate = IcpScoringConfig(
            version="copy", **{key: initial[key] for key in ("tags", "quality_investors", "scoring_rules")}
        )
        candidate.is_active = True

        self.admin.save_model(
            self.request, candidate, form=self.admin.get_form(self.request)(instance=candidate), change=False
        )

        candidate.refresh_from_db()
        assert candidate.is_active is False
        assert candidate.created_by_id == self.user.id
        assert candidate.scoring_rules == expected_rules

    def test_list_import_preserves_active_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tags = Path(directory) / "tags.csv"
            investors = Path(directory) / "investors.csv"
            tags.write_text("tag,recommendation\nNew category,software_positive\n")
            investors.write_text("investor,aliases\nNew Example Ventures,NEV\n")
            call_command(
                "sync_icp_scoring_lists", tags_csv=str(tags), investors_csv=str(investors), list_version="new-lists"
            )
        copied = IcpScoringConfig.objects.get(version="new-lists")
        assert copied.scoring_rules == self.config.scoring_rules
        assert copied.is_active is False

    def test_preview_compares_rules_without_changing_scores_or_contacting_providers(self) -> None:
        candidate = IcpScoringConfig.objects.create(version="include-harmonic", scoring_rules={})
        fetch = OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"companyFound": True, "headcount": 8, "description": "AI assistant for stocktaking."},
        )
        record = OrganizationEnrichment.objects.create(
            organization=self.organization, data={"signup_role": "engineering", "icp_fit_score": 4}
        )
        output = io.StringIO()
        with (
            patch("products.growth.backend.enrichment.labels._complete") as complete,
            patch("products.growth.backend.enrichment.tools.run_tool") as web_tool,
            patch("products.growth.backend.enrichment.bridge.read_organization_bridge_inputs") as bridge,
        ):
            call_command("preview_icp_scoring_config", config_version=candidate.version, limit=1, stdout=output)
        preview = json.loads(output.getvalue())
        assert preview["samples"][0]["fetch_id"] == str(fetch.id)
        assert preview["samples"][0]["active"]["score"] == 0
        assert preview["samples"][0]["candidate"]["score"] == 15
        assert preview["changed"] == 1
        record.refresh_from_db()
        assert record.data == {"signup_role": "engineering", "icp_fit_score": 4}
        assert IcpScoringConfig.objects.get(is_active=True).pk == self.config.pk
        complete.assert_not_called()
        web_tool.assert_not_called()
        bridge.assert_not_called()

    def test_preview_counts_a_confidence_change_without_a_score_change(self) -> None:
        candidate = IcpScoringConfig.objects.create(
            version="confidence", scoring_rules={"ai_sources": ["wizard"], "coverage": {"low_confidence_maximum": 0}}
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization,
            provider="harmonic",
            payload={"companyFound": True, "headcount": 8, "description": "Inventory support."},
        )
        output = io.StringIO()

        call_command("preview_icp_scoring_config", config_version=candidate.version, limit=1, stdout=output)

        preview = json.loads(output.getvalue())
        assert preview["changed"] == 1
        assert preview["samples"][0]["score_delta"] == 0
        assert preview["samples"][0]["active"]["low_confidence"] is True
        assert preview["samples"][0]["candidate"]["low_confidence"] is False
