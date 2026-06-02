/**
 * Production `AgentMcpResolver` — turns a `kind: 'agent'` MCP ref + a session
 * context into the `{ url, headers }` the runner needs to open an MCP client
 * against another agent on the same control plane.
 *
 * Lookup chain (all errors are loud — the runner catches and fails the
 * session, no silent degradation):
 *   1. Look up the target application by `(teamId, slug)` against
 *      `RevisionStore.getApplicationBySlug`. Missing app → `agent_mcp_target_not_found`.
 *   2. Confirm the application has a live revision pinned. Missing →
 *      `agent_mcp_target_no_live_revision`.
 *   3. Load the live revision and confirm its spec declares a trigger of
 *      type `mcp` (matching `services/agent-ingress/src/triggers/mcp.ts`).
 *      Missing → `agent_mcp_target_no_mcp_trigger`.
 *   4. Mint the ingress URL as `<baseUrl>/agents/<slug>/mcp` and stamp the
 *      `x-posthog-internal` header from the boot-time `INTERNAL_SECRET`.
 *
 * The internal secret matches the auth check at
 * `services/agent-ingress/src/enqueue/auth.ts:posthog_internal` and the
 * same env name the janitor uses. Plain bearer; no PKI / rotation in v0.
 *
 * **Error-message contract.** The thrown errors below embed
 * `team=<teamId> slug=<slug> rev=<revisionId>` so operators triaging via
 * structured logs can pin the failing target. The runner's catch path
 * (`worker.runOne` outer try/catch) routes these only to `sLog.error` —
 * never to `session.conversation`, never to a model-visible
 * `tool_result` — so no cross-tenant info leaks. If a future change
 * starts surfacing these error messages to the session record or to a
 * different principal on resume, the embedded ids become an exposure and
 * the wrapper must redact them first.
 *
 * See `docs/agent-platform/plans/runtime-mcps.md` "Resolved design" PR 7.
 */

import type { RevisionStore } from '@posthog/agent-shared'

import type { AgentMcpResolver } from '../loop/mcp-clients'

export interface MakeAgentMcpResolverDeps {
    revisions: RevisionStore
    /**
     * Base URL the ingress serves at (e.g. `https://app.posthog.com`). The
     * resolver appends `/agents/<slug>/mcp` — same path the ingress mounts
     * under via `services/agent-ingress/src/triggers/mcp.ts`.
     */
    ingressBaseUrl: string
    /**
     * Internal-secret bearer for `posthog_internal` auth. Mirrors the
     * janitor's `INTERNAL_SECRET`; both sides must agree.
     */
    internalSecret: string
}

/**
 * Build a resolver suitable for `WorkerDeps.agentMcpResolver`. Caller is
 * responsible for handling the `undefined` case at the boot site — we never
 * construct a resolver with partial inputs. Errors thrown from the resolver
 * surface to the runner via `mcp-clients.openMcpClients`, which wraps them
 * as `agent_mcp_target_*` codes for the session failure reason.
 */
export function makeAgentMcpResolver(deps: MakeAgentMcpResolverDeps): AgentMcpResolver {
    const baseUrl = stripTrailingSlash(deps.ingressBaseUrl)
    return async (slug, ctx) => {
        const application = await deps.revisions.getApplicationBySlug(ctx.teamId, slug)
        if (!application) {
            throw new Error(`agent_mcp_target_not_found: team=${ctx.teamId} slug=${slug}`)
        }
        if (!application.live_revision_id) {
            throw new Error(`agent_mcp_target_no_live_revision: team=${ctx.teamId} slug=${slug}`)
        }
        const revision = await deps.revisions.getRevision(application.live_revision_id)
        if (!revision) {
            // Shouldn't happen — the application pointed at a revision that
            // doesn't exist. Treat as no live revision so the failure code
            // is the same operationally.
            throw new Error(
                `agent_mcp_target_no_live_revision: team=${ctx.teamId} slug=${slug} rev=${application.live_revision_id}`
            )
        }
        const hasMcpTrigger = revision.spec.triggers.some((t) => t.type === 'mcp')
        if (!hasMcpTrigger) {
            throw new Error(`agent_mcp_target_no_mcp_trigger: team=${ctx.teamId} slug=${slug} rev=${revision.id}`)
        }
        return {
            url: `${baseUrl}/agents/${encodeURIComponent(slug)}/mcp`,
            headers: { 'x-posthog-internal': deps.internalSecret },
        }
    }
}

function stripTrailingSlash(url: string): string {
    return url.endsWith('/') ? url.slice(0, -1) : url
}
