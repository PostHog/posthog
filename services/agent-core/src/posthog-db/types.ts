/**
 * Shape returned by `ApplicationsRepository.resolve*` — the same payload Django used
 * to return over its (now-removed) `/internal/agents/applications/resolve` endpoint.
 * Defined here so callers don't have to know about the underlying schema.
 */
export interface ResolvedRevision {
    applicationId: string
    applicationSlug: string
    teamId: number
    revisionId: string
    revisionState: 'pending_upload' | 'uploaded' | 'validating' | 'ready' | 'failed'
    bundleS3Key: string
    bundleSha256: string
    topLevelConfig: Record<string, unknown>
    parsedManifest: Record<string, unknown> | null
    /**
     * v1: auth mode lives under `top_level_config.auth`. Defaults to `{ mode: 'public' }`
     * when absent. The shape mirrors the auth modes implemented in agent-ingress.
     */
    auth:
        | { mode: 'public' }
        | { mode: 'shared_secret'; token: string }
        | { mode: 'webhook_signature'; provider: string; secret: string }
}
