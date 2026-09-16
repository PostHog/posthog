from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig


class TestMarketingAnalyticsConfigValidation(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def patch_config(self, config: dict):
        return self.client.patch(
            f"/api/projects/{self.team.pk}/", {"marketing_analytics_config": config}, format="json"
        )

    @parameterized.expand(
        [
            ("sources_map_is_a_string", {"sources_map": "campaign_id"}),
            ("sources_map_entry_is_a_string", {"sources_map": {"src-1": "campaign_id"}}),
            ("sources_map_value_is_a_number", {"sources_map": {"src-1": {"campaign": 1}}}),
            ("conversion_goals_is_a_string", {"conversion_goals": "sign_up"}),
            ("conversion_goals_entry_is_a_string", {"conversion_goals": ["sign_up"]}),
            ("campaign_name_mappings_is_a_string", {"campaign_name_mappings": "GoogleAds"}),
            ("campaign_name_mappings_raw_values_is_a_string", {"campaign_name_mappings": {"GoogleAds": {"x": "y"}}}),
            ("custom_source_mappings_is_a_string", {"custom_source_mappings": "partner_a"}),
            ("custom_source_mappings_entry_is_a_string", {"custom_source_mappings": {"GoogleAds": "partner_a"}}),
            (
                "campaign_field_preferences_entry_is_a_string",
                {"campaign_field_preferences": {"GoogleAds": "campaign_id"}},
            ),
            (
                "campaign_field_preferences_match_field_is_unknown",
                {"campaign_field_preferences": {"GoogleAds": {"match_field": "nope"}}},
            ),
            ("campaign_field_preferences_has_no_match_field", {"campaign_field_preferences": {"GoogleAds": {}}}),
        ]
    )
    def test_malformed_config_is_rejected_with_a_message(self, _name: str, config: dict):
        # Each of these used to reach the model setter and raise Django's ValidationError,
        # which DRF returns as a 500 instead of a 400.
        response = self.patch_config(config)

        assert response.status_code == 400, response.json()
        assert response.json()["detail"]

    def test_a_rejected_config_leaves_the_stored_config_untouched(self):
        good = {
            "sources_map": {"src-1": {"campaign": "campaign_name"}},
            "campaign_field_preferences": {"GoogleAds": {"match_field": "campaign_id"}},
        }
        assert self.patch_config(good).status_code == 200

        assert self.patch_config({"campaign_field_preferences": {"GoogleAds": "campaign_id"}}).status_code == 400

        stored = TeamMarketingAnalyticsConfig.objects.get(team=self.team)
        assert stored.campaign_field_preferences == good["campaign_field_preferences"]
        assert stored.sources_map == good["sources_map"]
