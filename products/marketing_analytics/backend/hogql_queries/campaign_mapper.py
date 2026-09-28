from typing import TYPE_CHECKING

from posthog.hogql import ast

from posthog.dataclasses import frozen

from .adapters.factory import MarketingSourceFactory

if TYPE_CHECKING:
    from posthog.models.team.team import Team


@frozen
class CampaignMappingExpressions:
    campaign: ast.Expr
    campaign_id: ast.Expr
    match_key: ast.Expr


class CampaignMapper:
    def __init__(self, team: "Team") -> None:
        self.team = team

    def _get_campaign_field_preference(self, external_source: str) -> str:
        """
        Get campaign field matching preference for a given integration from team config.

        Returns: "campaign_name" or "campaign_id"

        Defaults to campaign_name if no preference set (backward compatible).
        """
        team = self.team

        try:
            preferences = team.marketing_analytics_config.campaign_field_preferences
            integration_prefs = preferences.get(external_source, {})
            return integration_prefs.get("match_field", "campaign_name")
        except Exception:
            return "campaign_name"

    def get_campaign_mapping_expressions(
        self, campaign_expr: ast.Expr, id_expr: ast.Expr, source_expr: ast.Expr
    ) -> CampaignMappingExpressions:
        """
        Apply campaign name mappings from team config.

        Keep the display name, campaign ID, and cost-join key distinct.

        When a source is configured to match on campaign_id, the mapping will:
        - Map utm_campaign values to campaign_id values
        - Keep campaign_name unchanged (from the original data)

        When a source is configured to match on campaign_name (default), the mapping will:
        - Map utm_campaign values to campaign_name values
        - Keep campaign_id unchanged
        """
        unmapped = CampaignMappingExpressions(campaign=campaign_expr, campaign_id=id_expr, match_key=campaign_expr)
        team = self.team

        try:
            campaign_mappings = team.marketing_analytics_config.campaign_name_mappings
        except Exception:
            return unmapped

        if not campaign_mappings:
            return unmapped

        # Build separate mapping expressions for campaign_name and campaign_id
        campaign_name_conditions: list[ast.Expr] = []
        campaign_id_conditions: list[ast.Expr] = []
        match_key_conditions: list[ast.Expr] = []

        lowercase_campaign = ast.Call(name="lower", args=[campaign_expr])
        lowercase_source = ast.Call(name="lower", args=[source_expr])

        for external_source, source_mappings in campaign_mappings.items():
            if not source_mappings:
                continue

            # Get utm_source values for this adapter
            adapter_class = MarketingSourceFactory._adapter_registry.get(external_source)
            if not adapter_class:
                continue

            source_mapping = adapter_class.get_source_identifier_mapping()
            utm_sources = []
            for alternatives in source_mapping.values():
                utm_sources.extend(alternatives)

            if not utm_sources:
                continue

            # Get the match field preference for this source
            match_field = self._get_campaign_field_preference(external_source)

            # Build source condition once for this adapter
            source_condition = ast.Call(
                name="in",
                args=[
                    lowercase_source,
                    ast.Array(exprs=[ast.Constant(value=s.lower()) for s in utm_sources]),
                ],
            )

            # Add condition/result pairs for each campaign mapping
            for clean_name, raw_values in source_mappings.items():
                if not raw_values:
                    continue

                # The raw_values are utm_campaign values that should be mapped to clean_name
                campaign_condition = ast.Call(
                    name="in",
                    args=[
                        lowercase_campaign,
                        ast.Array(exprs=[ast.Constant(value=val.lower()) for val in raw_values]),
                    ],
                )

                # Combine source and campaign conditions
                combined_condition = ast.Call(name="and", args=[source_condition, campaign_condition])
                match_key_conditions.extend([combined_condition, ast.Constant(value=clean_name)])

                if match_field == "campaign_id":
                    # When matching on campaign_id, map utm_campaign -> campaign_id
                    # The clean_name is the campaign_id value
                    campaign_id_conditions.append(combined_condition)
                    campaign_id_conditions.append(ast.Constant(value=clean_name))
                else:
                    # When matching on campaign_name (default), map utm_campaign -> campaign_name
                    # The clean_name is the campaign_name value
                    campaign_name_conditions.append(combined_condition)
                    campaign_name_conditions.append(ast.Constant(value=clean_name))

        # Build final expressions
        mapped_campaign_expr = campaign_expr
        mapped_id_expr = id_expr

        if campaign_name_conditions:
            campaign_name_conditions.append(campaign_expr)
            mapped_campaign_expr = ast.Call(name="multiIf", args=campaign_name_conditions)

        if campaign_id_conditions:
            campaign_id_conditions.append(id_expr)
            mapped_id_expr = ast.Call(name="multiIf", args=campaign_id_conditions)

        return CampaignMappingExpressions(
            campaign=mapped_campaign_expr,
            campaign_id=mapped_id_expr,
            match_key=ast.Call(name="multiIf", args=[*match_key_conditions, campaign_expr])
            if match_key_conditions
            else campaign_expr,
        )
