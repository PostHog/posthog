from posthog.api.routing import RouterRegistry

import products.signals.backend.views as signals
from products.signals.backend.plan_mode.views import InboxPlanViewSet
from products.signals.backend.scout_harness.views import (
    SignalProjectProfileViewSet,
    SignalScoutConfigViewSet,
    SignalScoutMembersViewSet,
    SignalScoutMetadataViewSet,
    SignalScoutRunViewSet,
    SignalScratchpadViewSet,
)
from products.signals.backend.views import SignalViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.register_legacy_dual_route(r"signals", SignalViewSet, "project_signals", ["team_id"])
    signal_reports_router = routers.projects.register(
        r"signals/reports", signals.SignalReportViewSet, "environment_signal_reports", ["team_id"]
    )
    signal_reports_router.register(
        r"artefacts",
        signals.SignalReportArtefactViewSet,
        "environment_signal_report_artefacts",
        ["team_id", "report_id"],
    )
    # Inbox "plan mode" (Projects) — read surface for plan reports; membership resolved from ClickHouse.
    routers.projects.register(r"signals/plans", InboxPlanViewSet, "environment_signal_plans", ["team_id"])
    routers.projects.register(
        r"signals/source_configs", signals.SignalSourceConfigViewSet, "environment_signal_source_configs", ["team_id"]
    )
    routers.projects.register(
        r"signals/config", signals.SignalTeamConfigViewSet, "environment_signal_config", ["team_id"]
    )
    routers.projects.register(
        r"signals/processing", signals.SignalProcessingViewSet, "environment_signal_processing", ["team_id"]
    )
    # Signals agent HTTP surface — exposed via MCP as `signals-scout-*` tools. Most reads (runs,
    # memory, project profile) are public-grantable via `signal_scout:read`; writes — and the member
    # roster read — are sandbox-scope only via the internal `signal_scout_internal` scope object.
    routers.projects.register(
        r"signals/scout/runs", SignalScoutRunViewSet, "environment_signals_scout_runs", ["team_id"]
    )
    routers.projects.register(
        r"signals/scout/configs", SignalScoutConfigViewSet, "environment_signals_scout_configs", ["team_id"]
    )
    routers.projects.register(
        r"signals/scout/scratchpad", SignalScratchpadViewSet, "environment_signals_scout_scratchpad", ["team_id"]
    )
    routers.projects.register(
        r"signals/scout/project_profile",
        SignalProjectProfileViewSet,
        "environment_signals_scout_project_profile",
        ["team_id"],
    )
    routers.projects.register(
        r"signals/scout/metadata",
        SignalScoutMetadataViewSet,
        "environment_signals_scout_metadata",
        ["team_id"],
    )
    # Reviewer-routing roster. `signal_scout_internal:read` (internal scope) → sandbox-only, never in
    # the public MCP catalog; the org-nested member tools the scoped-team token can't reach can't serve this.
    routers.projects.register(
        r"signals/scout/members",
        SignalScoutMembersViewSet,
        "environment_signals_scout_members",
        ["team_id"],
    )
