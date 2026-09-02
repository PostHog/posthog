from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache import cache

from posthog.constants import AvailableFeature
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig

from products.access_control.backend.models.access_control import AccessControl

_FLAG_TARGET = "products.marketing_analytics.backend.api.feature_enabled_or_false"

SCHEMA_MAP = {"utm_campaign_name": "utm_campaign", "utm_source_name": "utm_source"}


def goal_payload(name: str, event: str = "sign_up", **extra) -> dict:
    return {"kind": "EventsNode", "event": event, "conversion_goal_name": name, "schema_map": SCHEMA_MAP, **extra}


class TestApplySetupOps(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/apply_setup_ops"
        cache.clear()
        # Applying writes the same admin-gated config fields the team PATCH protects.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        flag = patch(_FLAG_TARGET, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def apply(self, *ops, source="setup_tab"):
        return self.client.post(self.url, {"ops": list(ops), "source": source}, format="json")

    def config(self) -> TeamMarketingAnalyticsConfig:
        return TeamMarketingAnalyticsConfig.objects.get(team=self.team)

    # --- mapping ops -------------------------------------------------------

    def test_adds_a_custom_source_mapping_and_returns_its_inverse(self):
        response = self.apply({"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"})

        assert response.status_code == 200, response.json()
        assert self.config().custom_source_mappings == {"MetaAds": ["fb-ads"]}
        assert response.json()["undo_ops"] == [
            {"op": "remove_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}
        ]

    def test_undo_ops_round_trip_back_to_the_original_state(self):
        add = {"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}
        undo = self.apply(add).json()["undo_ops"]

        self.client.post(self.url, {"ops": undo}, format="json")

        assert self.config().custom_source_mappings == {}

    def test_reapplying_an_existing_mapping_is_a_no_op_success(self):
        add = {"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}
        self.apply(add)

        response = self.apply(add)

        # Idempotent so an MCP retry can't fail or produce a duplicate...
        assert response.status_code == 200
        assert self.config().custom_source_mappings == {"MetaAds": ["fb-ads"]}
        # ...and contributes no undo, so undoing doesn't remove the original.
        assert response.json()["undo_ops"] == []

    def test_switches_the_campaign_match_field_and_restores_the_previous_one(self):
        response = self.apply(
            {"op": "set_campaign_field_preference", "integration": "GoogleAds", "match_field": "campaign_id"}
        )

        assert self.config().campaign_field_preferences == {"GoogleAds": {"match_field": "campaign_id"}}
        # Absent means campaign_name, so the inverse restores that explicitly.
        assert response.json()["undo_ops"] == [
            {"op": "set_campaign_field_preference", "integration": "GoogleAds", "match_field": "campaign_name"}
        ]

    def test_setting_the_field_preference_it_already_has_is_a_no_op(self):
        response = self.apply(
            {"op": "set_campaign_field_preference", "integration": "GoogleAds", "match_field": "campaign_name"}
        )

        assert response.json()["undo_ops"] == []

    def test_campaign_name_mapping_undo_only_removes_what_it_added(self):
        self.apply(
            {
                "op": "add_campaign_name_mapping",
                "integration": "GoogleAds",
                "clean_name": "spring_sale",
                "raw_values": ["sprng_sale"],
            }
        )

        response = self.apply(
            {
                "op": "add_campaign_name_mapping",
                "integration": "GoogleAds",
                "clean_name": "spring_sale",
                "raw_values": ["sprng_sale", "spring_sle"],
            }
        )

        assert self.config().campaign_name_mappings == {"GoogleAds": {"spring_sale": ["sprng_sale", "spring_sle"]}}
        # Only the newly added value, so undoing doesn't strip the pre-existing one.
        assert response.json()["undo_ops"] == [
            {
                "op": "remove_campaign_name_mapping",
                "integration": "GoogleAds",
                "clean_name": "spring_sale",
                "raw_values": ["spring_sle"],
            }
        ]

    def test_removing_the_last_raw_value_prunes_the_empty_keys(self):
        add = {
            "op": "add_campaign_name_mapping",
            "integration": "GoogleAds",
            "clean_name": "spring_sale",
            "raw_values": ["sprng_sale"],
        }
        undo = self.apply(add).json()["undo_ops"]

        self.client.post(self.url, {"ops": undo}, format="json")

        # No `{"GoogleAds": {"spring_sale": []}}` litter left behind.
        assert self.config().campaign_name_mappings == {}

    # --- conversion goal ops ----------------------------------------------

    def test_creates_a_goal_with_a_server_assigned_id(self):
        response = self.apply({"op": "create_conversion_goal", "goal": goal_payload("Sign ups")})

        goals = self.config().conversion_goals
        assert [g["conversion_goal_name"] for g in goals] == ["Sign ups"]
        assert goals[0]["conversion_goal_id"]
        assert response.json()["undo_ops"] == [
            {"op": "delete_conversion_goal", "conversion_goal_id": goals[0]["conversion_goal_id"]}
        ]

    def test_a_non_restore_create_ignores_a_client_supplied_id(self):
        # Otherwise a caller could pick ids and collide with an existing goal.
        response = self.apply(
            {"op": "create_conversion_goal", "goal": goal_payload("Sign ups", conversion_goal_id="pick-me")}
        )

        assert response.status_code == 200
        assert self.config().conversion_goals[0]["conversion_goal_id"] != "pick-me"

    def test_deleting_and_undoing_restores_the_same_goal_id(self):
        self.apply({"op": "create_conversion_goal", "goal": goal_payload("Sign ups")})
        goal_id = self.config().conversion_goals[0]["conversion_goal_id"]

        undo = self.apply({"op": "delete_conversion_goal", "conversion_goal_id": goal_id}).json()["undo_ops"]
        assert self.config().conversion_goals == []

        self.client.post(self.url, {"ops": undo}, format="json")

        restored = self.config().conversion_goals
        # Same id, not a copy — anything referencing the goal keeps working.
        assert [g["conversion_goal_id"] for g in restored] == [goal_id]

    def test_update_undo_restores_only_the_patched_keys(self):
        # Already summing a property, so the `counts_as_revenue` patch below is a legal
        # one. The field is incidental here — the assertion is about the undo's shape.
        self.apply(
            {"op": "create_conversion_goal", "goal": goal_payload("Sign ups", math="sum", math_property="revenue")}
        )
        goal_id = self.config().conversion_goals[0]["conversion_goal_id"]

        response = self.apply(
            {"op": "update_conversion_goal", "conversion_goal_id": goal_id, "patch": {"counts_as_revenue": True}}
        )

        assert self.config().conversion_goals[0]["counts_as_revenue"] is True
        undo = response.json()["undo_ops"][0]
        assert undo["op"] == "update_conversion_goal"
        assert set(undo["patch"]) == {"counts_as_revenue"}

    def test_updating_a_missing_goal_is_a_404(self):
        response = self.apply(
            {"op": "update_conversion_goal", "conversion_goal_id": "nope", "patch": {"counts_as_revenue": True}}
        )

        assert response.status_code == 404

    # --- batch semantics ---------------------------------------------------

    def test_applies_a_batch_and_returns_undo_in_reverse_order(self):
        response = self.apply(
            {"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"},
            {"op": "set_campaign_field_preference", "integration": "GoogleAds", "match_field": "campaign_id"},
            source="apply_all_safe",
        )

        assert response.status_code == 200
        undo = response.json()["undo_ops"]
        # Unwind last change first.
        assert [op["op"] for op in undo] == ["set_campaign_field_preference", "remove_custom_source_mapping"]

    def test_one_bad_op_rolls_back_the_whole_batch(self):
        # A partially-applied batch has no well-defined undo, so nothing may commit.
        response = self.apply(
            {"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"},
            {"op": "update_conversion_goal", "conversion_goal_id": "nope", "patch": {"counts_as_revenue": True}},
        )

        assert response.status_code == 404
        assert self.config().custom_source_mappings == {}

    def test_returns_the_resulting_config(self):
        response = self.apply({"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb"})

        config = response.json()["marketing_analytics_config"]
        assert config["custom_source_mappings"] == {"MetaAds": ["fb"]}
        assert "conversion_goals" in config

    # --- rejections --------------------------------------------------------

    def test_rejects_navigate_only_ops(self):
        response = self.apply({"op": "open_oauth", "kind": "google-ads"})

        assert response.status_code == 400
        assert "not applicable" in str(response.json())

    def test_rejects_fix_platform_urls_which_is_advice(self):
        response = self.apply(
            {
                "op": "fix_platform_urls",
                "integration": "GoogleAds",
                "campaign_name": "spring",
                "expected_utm_campaign": "spring",
                "expected_utm_source": "google",
            }
        )

        assert response.status_code == 400

    def test_rejects_an_unknown_op(self):
        response = self.apply({"op": "drop_everything"})

        assert response.status_code == 400

    def test_rejects_an_op_with_unexpected_keys(self):
        # extra="forbid" — a malformed or hallucinated op must fail at the boundary
        # rather than being applied with defaults filled in.
        response = self.apply(
            {"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb", "sneaky": 1}
        )

        assert response.status_code == 400

    def test_rejects_ops_not_implemented_yet(self):
        response = self.apply(
            {"op": "set_customer_analytics_event", "field": "activity_event", "event_node": {"kind": "EventsNode"}}
        )

        assert response.status_code == 400
        assert "not supported by this endpoint yet" in str(response.json())

    def test_rejects_an_empty_batch(self):
        response = self.client.post(self.url, {"ops": []}, format="json")

        assert response.status_code == 400

    def test_requires_authentication(self):
        self.client.logout()

        response = self.apply({"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb"})

        assert response.status_code in (401, 403)

    # --- removal ops as the setup plan emits them --------------------------

    def test_removes_a_broken_campaign_mapping_and_can_put_it_back(self):
        # End-to-end for the plan's only subtractive suggestion: the exact op shape
        # `_bad_mapping_suggestion` produces has to survive the round trip.
        self.apply(
            {
                "op": "add_campaign_name_mapping",
                "integration": "GoogleAds",
                "clean_name": "deleted_campaign",
                "raw_values": ["old_utm"],
            }
        )

        response = self.apply(
            {
                "op": "remove_campaign_name_mapping",
                "integration": "GoogleAds",
                "clean_name": "deleted_campaign",
                "raw_values": ["old_utm"],
            }
        )

        assert response.status_code == 200, response.json()
        assert self.config().campaign_name_mappings == {}

        self.client.post(self.url, {"ops": response.json()["undo_ops"]}, format="json")
        assert self.config().campaign_name_mappings == {"GoogleAds": {"deleted_campaign": ["old_utm"]}}

    def test_removes_a_wrong_platform_source_mapping(self):
        self.apply({"op": "add_custom_source_mapping", "integration": "GoogleAds", "raw_utm_source": "facebook"})

        response = self.apply(
            {"op": "remove_custom_source_mapping", "integration": "GoogleAds", "raw_utm_source": "facebook"}
        )

        assert response.status_code == 200
        assert self.config().custom_source_mappings == {}

    def test_creates_the_count_only_goal_the_plan_proposes(self):
        # The plan sends an empty conversion_goal_id; the server assigns the real one.
        response = self.apply(
            {
                "op": "create_conversion_goal",
                "goal": {
                    "kind": "EventsNode",
                    "event": "purchase_completed",
                    "name": "purchase_completed",
                    "conversion_goal_id": "",
                    "conversion_goal_name": "purchase_completed",
                    "math": "total",
                    "schema_map": {
                        "utm_campaign_name": "utm_campaign",
                        "utm_source_name": "utm_source",
                        "timestamp_field": "timestamp",
                        "distinct_id_field": "distinct_id",
                    },
                },
            }
        )

        assert response.status_code == 200, response.json()
        goals = self.config().conversion_goals
        assert [g["conversion_goal_name"] for g in goals] == ["purchase_completed"]
        assert goals[0]["conversion_goal_id"]


class TestRevenueGoalConsistencyViaOps(APIBaseTest):
    """The same rule as the conversion-goal endpoints, on the op path. This one matters
    most: it's the path an LLM writes through, and `counts_as_revenue` is the single flag
    where a wrong value produces a plausible revenue number rather than an error."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/apply_setup_ops"
        cache.clear()
        # Applying writes the same admin-gated config fields the team PATCH protects.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        flag = patch(_FLAG_TARGET, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def apply(self, *ops):
        return self.client.post(self.url, {"ops": list(ops), "source": "setup_tab"}, format="json")

    def config(self) -> TeamMarketingAnalyticsConfig:
        return TeamMarketingAnalyticsConfig.objects.get(team=self.team)

    def test_rejects_creating_a_revenue_goal_that_counts_rows(self):
        response = self.apply(
            {"op": "create_conversion_goal", "goal": goal_payload("Revenue", counts_as_revenue=True, math="total")}
        )

        assert response.status_code == 400, response.json()
        assert self.config().conversion_goals == []

    def test_accepts_a_revenue_goal_with_an_amount(self):
        response = self.apply(
            {
                "op": "create_conversion_goal",
                "goal": goal_payload("Revenue", counts_as_revenue=True, math="sum", math_property="revenue"),
            }
        )

        assert response.status_code == 200, response.json()
        assert len(self.config().conversion_goals) == 1

    def test_rejects_patching_the_flag_onto_a_counting_goal(self):
        created = self.apply({"op": "create_conversion_goal", "goal": goal_payload("Signups", math="total")})
        goal_id = self.config().conversion_goals[0]["conversion_goal_id"]
        assert created.status_code == 200

        response = self.apply(
            {"op": "update_conversion_goal", "conversion_goal_id": goal_id, "patch": {"counts_as_revenue": True}}
        )

        # Validated against the merged goal, not the patch: the patch alone is one
        # harmless-looking boolean.
        assert response.status_code == 400, response.json()
        assert self.config().conversion_goals[0].get("counts_as_revenue") is not True

    def test_a_rejected_goal_does_not_land_half_a_batch(self):
        # Batch atomicity has to hold for this rejection too, or a plausible-looking
        # ROAS goal gets in alongside whatever else was in the request.
        response = self.apply(
            {"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"},
            {"op": "create_conversion_goal", "goal": goal_payload("Revenue", counts_as_revenue=True, math="total")},
        )

        assert response.status_code == 400, response.json()
        assert self.config().custom_source_mappings == {}


class TestApplySetupOpsFeatureFlag(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/apply_setup_ops"
        cache.clear()

    def test_the_endpoint_is_absent_when_the_flag_is_off(self):
        # The ops only ever come from a plan, so an unreleased read side means there is
        # nothing legitimate to apply — and a write that lands anyway would be a config
        # change from a surface the user cannot see.
        with patch(_FLAG_TARGET, return_value=False):
            response = self.client.post(
                self.url,
                {"ops": [{"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}]},
                format="json",
            )

        assert response.status_code == 404
        assert TeamMarketingAnalyticsConfig.objects.get(team=self.team).custom_source_mappings == {}


class TestApplySetupOpsRequiresProjectAdmin(APIBaseTest):
    """`marketing_analytics:write` resolves to `editor` (web_analytics' default level via
    RESOURCE_INHERITANCE_MAP), which every project member has. Without an explicit admin
    check this endpoint is a way around both the team PATCH gate on
    marketing_analytics_config and the admin check the sibling goal endpoints carry."""

    def setUp(self):
        super().setUp()
        self.url = f"/api/projects/{self.team.pk}/marketing_analytics/apply_setup_ops"
        cache.clear()
        flag = patch(_FLAG_TARGET, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

    def _demote_to_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=self.team.id, access_level="member"
        )

    def test_a_member_cannot_delete_a_conversion_goal(self):
        # The identical write is admin-only on conversion_goals/<id>/delete.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        created = self.client.post(
            self.url,
            {"ops": [{"op": "create_conversion_goal", "goal": goal_payload("Sign ups")}]},
            format="json",
        )
        assert created.status_code == 200, created.json()
        goal_id = TeamMarketingAnalyticsConfig.objects.get(team=self.team).conversion_goals[0]["conversion_goal_id"]

        self._demote_to_member()
        response = self.client.post(
            self.url,
            {"ops": [{"op": "delete_conversion_goal", "conversion_goal_id": goal_id}]},
            format="json",
        )

        assert response.status_code == 403, response.json()
        assert len(TeamMarketingAnalyticsConfig.objects.get(team=self.team).conversion_goals) == 1

    def test_a_member_cannot_write_a_source_mapping(self):
        # Not covered by a sibling endpoint, but marketing_analytics_config as a whole
        # sits in TEAM_CONFIG_ADMIN_FIELDS_SET, so the PATCH path refuses this too.
        self._demote_to_member()

        response = self.client.post(
            self.url,
            {"ops": [{"op": "add_custom_source_mapping", "integration": "MetaAds", "raw_utm_source": "fb-ads"}]},
            format="json",
        )

        assert response.status_code == 403, response.json()
        assert TeamMarketingAnalyticsConfig.objects.get(team=self.team).custom_source_mappings == {}
