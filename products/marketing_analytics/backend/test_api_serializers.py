from dataclasses import asdict

from django.test import SimpleTestCase

from products.marketing_analytics.backend.api import UtmAuditResponseSerializer
from products.marketing_analytics.backend.services.types import Campaign, TeamMappings, UtmAuditResponse
from products.marketing_analytics.backend.services.utm_audit import _build_known_sources, _cross_reference

NO_MAPPINGS = TeamMappings(source_to_integration={}, campaign_aliases={}, field_preferences={})


class TestUtmAuditResponseSerializer(SimpleTestCase):
    def _serialize(self, campaigns: list[Campaign], utm_events: dict[tuple[str, str], int]) -> dict:
        results = _cross_reference(campaigns, utm_events, NO_MAPPINGS, _build_known_sources(NO_MAPPINGS))
        response = UtmAuditResponse(
            total_campaigns=len(results),
            campaigns_with_issues=len([r for r in results if r.issues]),
            campaigns_without_issues=len([r for r in results if not r.issues]),
            total_spend_at_risk=0.0,
            results=results,
            all_utm_events=[],
        )
        return UtmAuditResponseSerializer(asdict(response)).data

    def test_exposes_remediation_detail_for_an_unknown_source(self):
        # The audit knows this campaign's events exist under a source nothing claims, and that a
        # custom source mapping would fix it. All of that has to survive serialization — dropping
        # it leaves the UI with a tag and nothing to act on.
        data = self._serialize(
            [Campaign("Brand Campaign", "789", "google", 200.0, 80, 2000)],
            {("brand campaign", "newsletter"): 30},
        )

        issue = data["results"][0]["issues"][0]
        assert issue["kind"] == "unknown_source"
        assert issue["suggested_actions"] == ["fix_platform_urls", "add_source_mapping"]
        assert issue["alternative_sources"] == [{"utm_source": "newsletter", "event_count": 30}]

    def test_exposes_colliding_integrations_for_a_name_collision(self):
        data = self._serialize(
            [
                Campaign("Survey", "1", "bing", 100.0, 10, 100),
                Campaign("Survey", "2", "google", 200.0, 20, 200),
            ],
            {("survey", "google"): 29},
        )

        bing = next(r for r in data["results"] if r["source_name"] == "bing")
        issue = bing["issues"][0]
        assert issue["kind"] == "name_collision"
        assert issue["shared_with_integrations"] == ["google"]
        assert "switch_to_id_match" in issue["suggested_actions"]
