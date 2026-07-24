from posthog.api.routing import RouterRegistry

import products.signals.backend.views as signals
from products.signals.backend.scout_harness.views import (
    SignalProjectProfileViewSet,
    SignalScoutConfigViewSet,
    SignalScoutMembersViewSet,
    SignalScoutMetadataViewSet,
    SignalScoutNoteViewSet,
    SignalScoutRunViewSet,
    SignalScratchpadViewSet,
)
from products.signals.backend.views import SignalViewSet


def register_routes(routers: RouterRegistry) -> None:
    routers.projects.register(r"signals", SignalViewSet, "project_signals", ["team_id"])
    signal_reports_router = routers.projects.register(
        r"signals/reports", signals.SignalReportViewSet, "project_signal_reports", ["team_id"]
    )
    signal_reports_router.register(
        r"artefacts",
        signals.SignalReportArtefactViewSet,
        "project_signal_report_artefacts",
        ["team_id", "report_id"],
    )
    routers.projects.register(
        r"signals/source_configs", signals.SignalSourceConfigViewSet, "project_signal_source_configs", ["team_id"]
    )
    routers.projects.register(r"signals/config", signals.SignalTeamConfigViewSet, "project_signal_config", ["team_id"])
    routers.projects.register(
        r"signals/processing", signals.SignalProcessingViewSet, "project_signal_processing", ["team_id"]
    )
    # Signals agent HTTP surface — exposed via MCP as `scout-*` tools. Most reads (runs,
    # memory, project profile) are public-grantable via `signal_scout:read`; writes — and the member
    # roster read — are sandbox-scope only via the internal `signal_scout_internal` scope object.
    routers.projects.register(r"signals/scout/runs", SignalScoutRunViewSet, "project_signals_scout_runs", ["team_id"])
    routers.projects.register(
        r"signals/scout/configs", SignalScoutConfigViewSet, "project_signals_scout_configs", ["team_id"]
    )
    routers.projects.register(
        r"signals/scout/scratchpad", SignalScratchpadViewSet, "project_signals_scout_scratchpad", ["team_id"]
    )
    # Steering notes team members (or their agents) leave for the scouts. Reads are public
    # (`signal_scout:read`); writes require skill-authoring-level authorization — see the viewset.
    routers.projects.register(
        r"signals/scout/notes", SignalScoutNoteViewSet, "project_signals_scout_notes", ["team_id"]
    )
    routers.projects.register(
        r"signals/scout/project_profile",
        SignalProjectProfileViewSet,
        "project_signals_scout_project_profile",
        ["team_id"],
    )
    routers.projects.register(
        r"signals/scout/metadata",
        SignalScoutMetadataViewSet,
        "project_signals_scout_metadata",
        ["team_id"],
    )
    # Reviewer-routing roster. `signal_scout_internal:read` (internal scope) → sandbox-only, never in
    # the public MCP catalog; the org-nested member tools the scoped-team token can't reach can't serve this.
    routers.projects.register(
        r"signals/scout/members",
        SignalScoutMembersViewSet,
        "project_signals_scout_members",
        ["team_id"],
    )
