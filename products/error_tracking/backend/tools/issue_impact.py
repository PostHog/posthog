from textwrap import dedent
from typing import Literal

from pydantic import BaseModel, Field

from posthog.schema import ErrorTrackingIssueImpactToolOutput

from ee.hogai.tool import MaxTool


class IssueImpactQueryArgs(BaseModel):
    events: list[str] = Field(
        description=dedent("""
            List of event names that relate to the user's query about issues.

            Before calling this tool, you should:
            1. Use the read_taxonomy tool to get available events if you don't know them
            2. Identify which events relate to the user's query (e.g., "issues blocking signup" → signup-related events)
            3. Pass the relevant event names to this tool

            Examples:
            - User asks about "issues blocking signup" → events: ["sign_up_started", "signup_complete"]
            - User asks about "notebook errors" → events: ["notebook_created", "notebook_updated"]
            - User asks about "checkout problems" → events: ["checkout_started", "payment_submitted", "order_completed"]
            """).strip()
    )


class ErrorTrackingIssueImpactTool(MaxTool):
    name: Literal["find_error_tracking_impactful_issue_event_list"] = "find_error_tracking_impactful_issue_event_list"
    description: str = dedent("""
        Analyze the impact of error tracking issues on product events and user flows.

        Use this tool when:
        - User asks about the "impact" of an issue or issues
        - User wants to understand how issues affect their product (features, flows, conversions)
        - User asks what events or flows are being "blocked", "affected", or "impacted" by issues
        - User wants to see correlations between issues and event occurrences

        Before calling this tool:
        1. If you don't know the available events, use read_taxonomy to retrieve them first
        2. Identify which events relate to the user's query (e.g., signup flow → signup events)
        3. Pass those event names to this tool

        The tool returns events that will be analyzed to show issue-event correlations and impact metrics.
        """).strip()
    args_schema: type[BaseModel] = IssueImpactQueryArgs

    def get_required_resource_access(self):
        return [("error_tracking", "viewer")]

    async def _arun_impl(self, events: list[str]) -> tuple[str, ErrorTrackingIssueImpactToolOutput]:
        if not events:
            return (
                "No events provided. Please specify which events you want to analyze for issue impact.",
                ErrorTrackingIssueImpactToolOutput(events=[]),
            )

        return (
            f"Searching for issues impacting {len(events)} event(s): {', '.join(events[:5])}{'...' if len(events) > 5 else ''}",
            ErrorTrackingIssueImpactToolOutput(events=events),
        )
