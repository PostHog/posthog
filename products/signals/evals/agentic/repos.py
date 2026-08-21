from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Repo:
    key: str
    full_name: str
    primary_language: str
    domain: str
    tree_paths: tuple[str, ...] = ()
    default_branch: str = "main"
    default_branch_sha: str = ""

    @property
    def repo(self) -> str:
        return self.full_name.split("/", 1)[1]


REGISTRY: dict[str, Repo] = {
    repo.key: repo
    for repo in (
        Repo("cal", "calcom/cal.com", "TypeScript", "Open-source booking and scheduling platform."),
        Repo(
            "supabase",
            "supabase/supabase",
            "TypeScript",
            "Postgres development platform with auth, storage, APIs, and a database dashboard.",
            (
                "apps/studio/components/interfaces/Database/Policies/PolicyEditorPanel/index.tsx",
                "apps/studio/components/interfaces/Database/RLSToggleDialog.tsx",
                "apps/studio/components/interfaces/Settings/API/PostgrestConfig.tsx",
                "apps/docs/content/troubleshooting/refresh-postgrest-schema.mdx",
            ),
            default_branch="master",
            default_branch_sha="eabe06be5b36cf57f2b158bd5093b396606bf801",
        ),
        Repo(
            "postgrest",
            "postgrest/postgrest",
            "Haskell",
            "Standalone REST API server for PostgreSQL databases.",
            (
                "src/library/PostgREST/Auth/Jwt.hs",
                "docs/references/schema_cache.rst",
                "test/io/__snapshots__/test_cli/test_schema_cache_snapshot[dbTables].yaml",
            ),
            default_branch_sha="4a6aa0040feda48d0f76dc47cb2246c5dd65840f",
        ),
        Repo(
            "n8n",
            "n8n-io/n8n",
            "TypeScript",
            "Node-based workflow automation platform.",
            (
                "packages/nodes-base/nodes/HttpRequest/HttpRequest.node.ts",
                "packages/@n8n/backend-network/src/http/retryability.ts",
                "packages/core/src/execution-engine/workflow-execute.ts",
                "packages/cli/src/commands/execution/retry.ts",
            ),
            default_branch="master",
            default_branch_sha="c4892a4a1a048e16f445c4485fb9238291222be1",
        ),
        Repo(
            "activepieces",
            "activepieces/activepieces",
            "TypeScript",
            "Open-source workflow automation and integration platform.",
            (
                "packages/core/utils/src/lib/activepieces-error.ts",
                "packages/core/execution/src/lib/flow-run/execution/flow-execution.ts",
                "packages/pieces/core/http/src/lib/actions/send-http-request-action.ts",
                "packages/server/api/src/app/mcp/tools/ap-retry-run.ts",
            ),
            default_branch_sha="3cc6aa333c00fb5985c4f3ed040b1eda927bf6b9",
        ),
        Repo(
            "excalidraw",
            "excalidraw/excalidraw",
            "TypeScript",
            "Hand-drawn-style collaborative whiteboard.",
            (
                "packages/element/src/arrowEndpointText.ts",
                "packages/element/src/binding.ts",
                "packages/excalidraw/renderer/staticSvgScene.ts",
                "packages/excalidraw/tests/scene/export.test.ts",
            ),
            default_branch="master",
            default_branch_sha="e160ff7ba0641fba729c528482de5277ffb19c58",
        ),
        Repo(
            "tldraw",
            "tldraw/tldraw",
            "TypeScript",
            "SDK and application for infinite-canvas whiteboards.",
            (
                "packages/editor/src/lib/editor/types/SvgExportContext.tsx",
                "packages/editor/src/lib/exports/exportToSvg.tsx",
                "packages/tldraw/src/lib/shapes/text/RichTextArea.tsx",
                "packages/tldraw/src/lib/bindings/arrow/ArrowBindingUtil.ts",
            ),
            default_branch_sha="5e48138e82b0e2c8a64834482dccecb5b09e8727",
        ),
        Repo(
            "strapi",
            "strapi/strapi",
            "JavaScript",
            "Headless CMS with an admin panel and content API.",
            (
                "packages/plugins/users-permissions/admin/src/pages/Roles/pages/EditPage.jsx",
                "packages/plugins/users-permissions/server/src/controllers/role.js",
                "packages/core/core/src/services/content-api/permissions/engine.ts",
            ),
            default_branch="develop",
            default_branch_sha="3907045668ecb4f178d244e9d1a54c2d66196d15",
        ),
        Repo(
            "payload",
            "payloadcms/payload",
            "TypeScript",
            "Code-first headless CMS and application framework.",
            (
                "packages/payload/src/utilities/getEntityPermissions/getEntityPermissions.ts",
                "packages/payload/src/utilities/getFieldPermissions.ts",
                "packages/ui/src/utilities/getDocumentPermissions.ts",
                "docs/access-control/fields.mdx",
            ),
            default_branch_sha="eabe959f144d0a191d3402c0b8ec35eac6bf55e2",
        ),
        Repo(
            "posthog-js",
            "posthog/posthog-js",
            "TypeScript",
            "PostHog browser SDK for analytics, autocapture, and session replay.",
            (
                "packages/browser/src/autocapture.ts",
                "packages/browser/src/request-queue.ts",
                "packages/browser/src/posthog-featureflags.ts",
                "packages/react/src/components/PostHogCaptureOnViewed.tsx",
            ),
            default_branch_sha="3508c05bf4c70e99c4029c0638e00dd0d7949ec0",
        ),
        Repo(
            "posthog-python",
            "posthog/posthog-python",
            "Python",
            "PostHog server-side Python SDK for capture, feature flags, and LLM analytics.",
            (
                "posthog/consumer.py",
                "posthog/feature_flag_evaluations.py",
                "posthog/capture_v1.py",
                "posthog/test/test_consumer.py",
            ),
            default_branch_sha="b86126ec2a89d6dbe0ec5366180ae86a82adc4f0",
        ),
    )
}
