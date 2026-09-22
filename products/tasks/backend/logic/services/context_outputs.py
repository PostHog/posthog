"""The living deliverables a run keeps current for a context, and what it takes to write them.

Native loops (``loop_runs``) and workflow-backed loops (``workflow_tasks``) attach a run to the
same contexts, so the scope grant and the publish contract are written once here instead of
drifting apart between the two paths.
"""

from uuid import UUID

from django.apps import apps
from django.db.models import Q

from posthog.temporal.oauth import LOOP_CONTEXT_INTERNAL_SCOPE, PosthogMcpScopes, resolve_scopes

from products.tasks.backend.models import Channel

# Least-privilege write grants for a run that maintains a context page or canvas, added on top of
# whatever posthog_mcp_scopes the run already carries rather than escalating it to the broad `full`
# write surface. resolve_scopes() re-adds the internal scopes at mint time. Context updates use the
# task surface plus server-minted internal-run provenance; canvases have their own scopes.
CONTEXT_WRITE_SCOPES = ["task:read", "task:write", LOOP_CONTEXT_INTERNAL_SCOPE]
CANVAS_WRITE_SCOPES = ["canvas:read", "canvas:write"]


def widen_scopes(scopes: PosthogMcpScopes, *, extra: list[str]) -> PosthogMcpScopes:
    """Return `scopes` plus `extra`, resolved to a flat list. `full` already covers everything."""
    if not extra:
        return scopes
    base = resolve_scopes(scopes, include_internal_scopes=False)
    return list(dict.fromkeys([*base, *extra]))


def context_canvas_is_visible(team_id: int, canvas_id: str | UUID, user_id: int | None) -> bool:
    """Whether `canvas_id` is a canvas in this team the user may see.

    The Canvas model belongs to the canvas product, which depends on tasks —
    resolved through the app registry so this soft existence check doesn't
    create a tasks → canvas import cycle.
    """
    canvas_model = apps.get_model("canvas", "Canvas")
    visible = Channel.visible_to_q(user_id, relation="channel")
    return canvas_model.objects.for_team(team_id).filter(Q(id=canvas_id, deleted=False) & visible).exists()


def render_canvas_maintenance_line(canvas_id: str) -> str:
    """The publish contract for the one canvas a run rewrites, as a bullet."""
    return (
        f"- Update its canvas (id: {canvas_id}): read the current source project and "
        f"`current_version_id` with `canvas-source-retrieve`, then publish the "
        f"complete project with `canvas-publish-create`, passing the version you "
        f"read as `expected_current_version_id`. Follow the `building-canvases` skill."
        " Read runtime state with `canvas-state-retrieve`: list keys without values, follow next_offset, "
        "and select only the keys needed. Read long values with `canvas-state-value-retrieve`, keeping "
        "the revision fixed across chunks. Discover these tools through MCP search and info; do not assume "
        "a composition storage tool is available. Missing tools, denied access, missing values, and incomplete "
        "reads are different conditions. Report the actual condition instead of requesting broader permissions."
    )
