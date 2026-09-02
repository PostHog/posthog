"""Team configuration for the demo world: conversion goals, mappings, flags."""

from posthog.models import Team, User

from products.actions.backend.models.action import Action
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.marketing_analytics.backend.demo.warehouse import STRIPE_INVOICES_TABLE
from products.marketing_analytics.backend.demo.world import EVENT_DEMO_BOOKED, EVENT_PURCHASE, EVENT_SIGNUP

MARKETING_FEATURE_FLAGS = (
    "marketing-analytics",
    "marketing-analytics-utm-audit",
    "marketing-analytics-drill-down",
    "marketing-analytics-extended-drill-down",
    "marketing-analytics-multi-touch-attribution",
    "marketing-analytics-ai",
    "advance-marketing-analytics-settings",
    # Gate the Setup tab and the ROAS / cost-per-customer columns. Without these the
    # seeded world renders as if none of this work existed, which is the opposite of
    # what a seeder is for.
    "marketing-analytics-setup",
    "marketing-analytics-return-metrics",
)

_DEFAULT_SCHEMA_MAP = {
    "utm_campaign_name": "utm_campaign",
    "utm_source_name": "utm_source",
    "timestamp_field": "timestamp",
    "distinct_id_field": "distinct_id",
}


def _ensure_demo_action(team: Team) -> Action:
    action = Action.objects.filter(team=team, name="Demo booked (marketing demo)", deleted=False).first()
    if action:
        return action
    return Action.objects.create(
        team=team,
        name="Demo booked (marketing demo)",
        steps_json=[{"event": EVENT_DEMO_BOOKED}],
    )


def build_conversion_goals(team: Team) -> list[dict]:
    action = _ensure_demo_action(team)
    return [
        {
            "kind": "EventsNode",
            "event": EVENT_SIGNUP,
            "conversion_goal_id": "cg_signups",
            "name": EVENT_SIGNUP,
            "conversion_goal_name": "Sign ups",
            "math": "dau",
            "schema_map": _DEFAULT_SCHEMA_MAP,
        },
        {
            "kind": "EventsNode",
            "event": EVENT_PURCHASE,
            "conversion_goal_id": "cg_purchases",
            "name": EVENT_PURCHASE,
            "conversion_goal_name": "Purchase revenue",
            "math": "sum",
            "math_property": "revenue",
            "counts_as_customer": True,
            "counts_as_revenue": True,
            "schema_map": _DEFAULT_SCHEMA_MAP,
        },
        {
            "kind": "ActionsNode",
            "id": action.pk,
            "conversion_goal_id": "cg_demos",
            "name": "Demo booked (marketing demo)",
            "conversion_goal_name": "Demos booked",
            "math": "total",
            "schema_map": _DEFAULT_SCHEMA_MAP,
        },
        {
            "kind": "DataWarehouseNode",
            "id": STRIPE_INVOICES_TABLE,
            "table_name": STRIPE_INVOICES_TABLE,
            "conversion_goal_id": "cg_invoices",
            "name": STRIPE_INVOICES_TABLE,
            "conversion_goal_name": "Paid invoices",
            "math": "sum",
            "math_property": "amount",
            "counts_as_customer": True,
            "counts_as_revenue": True,
            "timestamp_field": "created_at",
            "distinct_id_field": "distinct_id",
            "id_field": "id",
            "schema_map": {
                "utm_campaign_name": "utm_campaign",
                "utm_source_name": "utm_source",
                "timestamp_field": "created_at",
                "distinct_id_field": "distinct_id",
            },
        },
        # Sums money and is flagged as neither, so the settings checkboxes have a goal
        # to turn on. It does not produce mark_goal_as_revenue / mark_goal_as_customer:
        # those ask "is there any flagged goal at all", and the two below are, which is
        # what keeps ROAS and cost per customer unlocked here. A fixture can show the
        # metrics working or the nudge to enable them, not both.
        {
            "kind": "EventsNode",
            "event": EVENT_PURCHASE,
            "conversion_goal_id": "cg_unflagged_revenue",
            "name": EVENT_PURCHASE,
            "conversion_goal_name": "Checkout value (unflagged)",
            "math": "sum",
            "math_property": "revenue",
            "schema_map": _DEFAULT_SCHEMA_MAP,
        },
        # Deliberately broken goals: exercise is_misconfigured in the inspector
        # and the dashboard's validation warnings.
        {
            "kind": "ActionsNode",
            "id": 999999,
            "conversion_goal_id": "cg_ghost_action",
            "name": "Ghost action",
            "conversion_goal_name": "Ghost action (broken)",
            "math": "total",
            "schema_map": _DEFAULT_SCHEMA_MAP,
        },
        {
            "kind": "EventsNode",
            "event": None,
            "conversion_goal_id": "cg_all_events",
            "name": "All events",
            "conversion_goal_name": "All events (misconfigured)",
            "math": "total",
            "schema_map": _DEFAULT_SCHEMA_MAP,
        },
    ]


def apply_marketing_config(team: Team, *, bigquery_sources_map: dict[str, dict[str, str]]) -> None:
    config = team.marketing_analytics_config
    config.conversion_goals = build_conversion_goals(team)
    config.sources_map = bigquery_sources_map
    config.campaign_name_mappings = {
        "GoogleAds": {"Spring Sale 2026": ["spring_sale_2026", "spring-sale-2026"]},
    }
    config.custom_source_mappings = {"GoogleAds": ["partner_blog"]}
    config.campaign_field_preferences = {"BingAds": {"match_field": "campaign_id"}}
    # 30 days: keeps the goals inspector non-approximate and lets the
    # out-of-window journey actually fall outside the window within 60 days.
    config.attribution_window_days = 30
    config.attribution_mode = "last_touch"
    config.save()


def enable_feature_flags(team: Team, user: User) -> list[str]:
    """Enable the marketing flags at 100% on the target team and on the local
    self-capture team (the one whose flags the local PostHog UI evaluates)."""
    teams = {team.pk: team}
    self_capture_team = Team.objects.filter(api_token="phc_localposthogprojecttoken").first()
    if self_capture_team:
        teams[self_capture_team.pk] = self_capture_team
    enabled = []
    for target in teams.values():
        for key in MARKETING_FEATURE_FLAGS:
            FeatureFlag.objects.update_or_create(
                team=target,
                key=key,
                defaults={
                    "name": key,
                    "active": True,
                    "deleted": False,
                    "created_by": user,
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                },
            )
            enabled.append(f"{target.pk}:{key}")
    return enabled
