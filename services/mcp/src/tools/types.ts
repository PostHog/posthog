import type { z } from 'zod'

import type { ApiClient, GroupType } from '@/api/client'
import type { Schemas } from '@/api/generated'
import type { ScopedCache } from '@/lib/cache/ScopedCache'
import type { SessionManager } from '@/lib/SessionManager'
import type { StateManager } from '@/lib/StateManager'
import type { PrefixedString } from '@/lib/types'
import type { ApiRedactedPersonalApiKey, ApiUser } from '@/schema/api'

export type CloudRegion = 'us' | 'eu'

export type SessionState = {
    uuid: string
}

export type CachedUser = ApiUser
export type CachedOrg = Schemas.OrganizationBasic
export type CachedProject = Schemas.ProjectBackwardCompat

export type State = {
    projectId: string | undefined
    orgId: string | undefined
    distinctId: string | undefined
    region: CloudRegion | undefined
    apiKey: ApiRedactedPersonalApiKey | undefined
    clientName: string | undefined
} & Record<PrefixedString<'session'>, SessionState> &
    Record<PrefixedString<'groupTypes'>, GroupType[] | undefined> &
    Record<PrefixedString<'groupTypesFetchedAt'>, number | undefined> &
    Record<PrefixedString<'cachedUser'>, CachedUser | undefined> &
    Record<PrefixedString<'cachedUserFetchedAt'>, number | undefined> &
    Record<PrefixedString<'cachedOrg'>, CachedOrg | undefined> &
    Record<PrefixedString<'cachedOrgFetchedAt'>, number | undefined> &
    Record<PrefixedString<'cachedProject'>, CachedProject | undefined> &
    Record<PrefixedString<'cachedProjectFetchedAt'>, number | undefined>

export type Env = {
    /**
     * Inkeep API key for the PostHog Agent Toolkit.
     * Setting this enables the 'docs-search' tool.
     */
    INKEEP_API_KEY: string | undefined
    /**
     * Custom API base URL for self-hosted PostHog instances.
     *
     * WARNING: In PostHog Production, this should NOT be set.
     * The code automatically handles US/EU region routing via getAuthorizationServerUrl().
     * Only set this for self-hosted PostHog deployments.
     */
    POSTHOG_API_BASE_URL: string | undefined
    /**
     * Base URL for serving MCP UI app static assets.
     * When using Workers Static Assets, this is the Worker's own public URL.
     * Example: https://mcp.posthog.com
     */
    MCP_APPS_BASE_URL: string | undefined
    /**
     * PostHog base URL for MCP Apps analytics (used for CSP and analytics ingestion).
     * For local development, set to http://localhost:8010.
     */
    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: string | undefined
    /**
     * PostHog API token for MCP Apps analytics (used for CSP and analytics ingestion).
     */
    POSTHOG_UI_APPS_TOKEN: string | undefined
    /**
     * PostHog API key for dev/self-hosted analytics.
     * Falls back to the production US key if not set.
     */
    POSTHOG_ANALYTICS_API_KEY: string | undefined
    /**
     * PostHog host for dev/self-hosted analytics.
     * Falls back to the production US host if not set.
     */
    POSTHOG_ANALYTICS_HOST: string | undefined
}

export type Context = {
    api: ApiClient
    cache: ScopedCache<State>
    env: Env
    stateManager: StateManager
    sessionManager: SessionManager
}

export type Tool<TSchema extends z.ZodType = z.ZodType, TResult = unknown> = {
    name: string
    title: string
    description: string
    schema: TSchema
    handler: (context: Context, params: z.infer<TSchema>) => Promise<TResult>
    scopes: string[]
    annotations: {
        destructiveHint: boolean
        idempotentHint: boolean
        openWorldHint: boolean
        readOnlyHint: boolean
    }
    _meta?: ToolMeta
}

export type ToolBase<TSchema extends z.ZodType = z.ZodType, TResult = unknown> = Omit<
    Tool<TSchema, TResult>,
    'title' | 'description' | 'scopes' | 'annotations'
> & {
    _meta?: ToolMeta
    /** When set, the tool is only available in this MCP version (1 = v1 only, 2 = v2 only). */
    mcpVersion?: number
}

export type ZodObjectAny = z.ZodType<any>

export type ToolUiMeta = {
    resourceUri: string
    visibility?: ('model' | 'app')[]
}

export const POSTHOG_META_KEY = 'com.posthog.mcp' as const
export const POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY = '__formatted_results_override' as const

export type PostHogToolMeta = {
    /** Return JSON instead of TOON-encoded text. Use for tools whose output is consumed programmatically. */
    responseFormat?: 'json'
}

export type ToolMeta = {
    // Legacy flat key for MCP Apps compatibility (ui/resourceUri)
    'ui/resourceUri'?: string
    // New non-legacy key for MCP Apps
    ui?: ToolUiMeta

    /** PostHog-specific tool metadata under a namespaced key. */
    [POSTHOG_META_KEY]?: PostHogToolMeta
}
