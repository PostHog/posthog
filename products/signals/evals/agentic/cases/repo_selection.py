from __future__ import annotations

from products.signals.evals.agentic.datasets import RepoSelectionCase, RepoSelectionExpectation, SignalSpec


def _case(
    case_id: str,
    content: str,
    candidates: tuple[str, str],
    expected: str,
    judging_notes: str,
) -> RepoSelectionCase:
    return RepoSelectionCase(
        case_id=case_id,
        step="repo_selection",
        signals=(SignalSpec(signal_id=f"sig_{case_id}", content=content),),
        candidate_repos=candidates,
        judging_notes=judging_notes,
        expected=RepoSelectionExpectation(expected_repository=expected),
    )


CASES: list[RepoSelectionCase] = [
    _case(
        "reposel_canvas_bound_text_svg",
        "Connector labels render correctly on the canvas, but move to the wrong endpoint in SVG exports after the "
        "connector direction is reversed. Free-standing text exports correctly.",
        ("excalidraw/excalidraw", "tldraw/tldraw"),
        "excalidraw/excalidraw",
        "Excalidraw owns packages/excalidraw/renderer/staticSvgScene.ts and packages/element/src/arrowEndpointText.ts.",
    ),
    _case(
        "reposel_canvas_rich_text_svg",
        "Bold and list formatting in editable text shapes is flattened only in SVG exports; the rich-text editor and "
        "the shape geometry remain correct on the canvas.",
        ("excalidraw/excalidraw", "tldraw/tldraw"),
        "tldraw/tldraw",
        "tldraw owns SvgExportContext.tsx, exportToSvg.tsx, and RichTextArea.tsx.",
    ),
    _case(
        "reposel_cms_users_permissions_role",
        "A custom public role keeps its name after restart but loses the generated content API action bindings that "
        "were selected in the admin permissions screen.",
        ("strapi/strapi", "payloadcms/payload"),
        "strapi/strapi",
        "Strapi has the users-permissions plugin and its role controller alongside the content API permission engine.",
    ),
    _case(
        "reposel_cms_field_access_permissions",
        "A collection's field-level read callback grants access, and the API returns the field, but the admin document "
        "table removes it while constructing the current user's entity permissions.",
        ("strapi/strapi", "payloadcms/payload"),
        "payloadcms/payload",
        "Payload owns getEntityPermissions.ts, getFieldPermissions.ts, and the document permission UI utilities.",
    ),
    _case(
        "reposel_automation_node_api_retry",
        "A visual workflow's HTTP request step is set to retry on failure at most three times. A 429 with Retry-After "
        "still causes the workflow executor to start a fourth request.",
        ("n8n-io/n8n", "activepieces/activepieces"),
        "n8n-io/n8n",
        "n8n owns the HttpRequest node, network retryability module, and workflow-execute implementation.",
    ),
    _case(
        "reposel_automation_flow_retry",
        "Rerunning a failed historical flow should resume at its failed HTTP step, but the platform wraps the stored "
        "step error and terminates the flow before the retry-run worker can schedule it.",
        ("n8n-io/n8n", "activepieces/activepieces"),
        "activepieces/activepieces",
        "Activepieces owns activepieces-error.ts, flow-execution.ts, its HTTP piece, and ap-retry-run.ts.",
    ),
    _case(
        "reposel_postgres_schema_cache",
        "A self-hosted REST endpoint reports that a newly created relation is missing immediately after a schema-cache "
        "reload notification. PostgreSQL can query the table and no dashboard UI is involved.",
        ("supabase/supabase", "postgrest/postgrest"),
        "postgrest/postgrest",
        "PostgREST owns the standalone server schema cache reference and schema cache snapshots.",
    ),
    _case(
        "reposel_supabase_rls_editor",
        "A row-level security policy saved in the browser database dashboard is enforced by the REST API, but the "
        "policy editor and RLS toggle disagree until the page is refreshed.",
        ("supabase/supabase", "postgrest/postgrest"),
        "supabase/supabase",
        "Supabase owns the Studio PolicyEditorPanel and RLSToggleDialog UI.",
    ),
]
