import type { z } from 'zod'

import type { ApiClient } from '@/api/client'
import type { SessionManager } from '@/lib/SessionManager'
import type { StateManager } from '@/lib/StateManager'
import type { ScopedCache } from '@/lib/cache/ScopedCache'
import type { PrefixedString } from '@/lib/types'
import type { ApiRedactedPersonalApiKey } from '@/schema/api'

export type CloudRegion = 'us' | 'eu'

export type SessionState = {
    uuid: string
}

export type State = {
    projectId: string | undefined
    orgId: string | undefined
    distinctId: string | undefined
    region: CloudRegion | undefined
    apiKey: ApiRedactedPersonalApiKey | undefined
} & Record<PrefixedString<'session'>, SessionState>

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
     * PostHog base URL for MCP Apps analytics (used for CSP and analytics ingestion).
     * For local development, set to http://localhost:8010.
     */
    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: string | undefined
    /**
     * PostHog API token for MCP Apps analytics (used for CSP and analytics ingestion).
     */
    POSTHOG_UI_APPS_TOKEN: string | undefined
}

export type Context = {
    api: ApiClient
    cache: ScopedCache<State>
    env: Env
    stateManager: StateManager
    sessionManager: SessionManager
}

export type Tool<TSchema extends z.ZodTypeAny = z.ZodTypeAny> = {
    name: string
    title: string
    description: string
    schema: TSchema
    handler: (context: Context, params: z.infer<TSchema>) => Promise<any>
    scopes: string[]
    annotations: {
        destructiveHint: boolean
        idempotentHint: boolean
        openWorldHint: boolean
        readOnlyHint: boolean
    }
    _meta?: ToolMeta
}

export type ToolBase<TSchema extends z.ZodTypeAny = z.ZodTypeAny> = Omit<
    Tool<TSchema>,
    'title' | 'description' | 'scopes' | 'annotations'
> & {
    _meta?: ToolMeta
}

export type ZodObjectAny = z.ZodObject<any, any, any, any, any>

export type ToolUiMeta = {
    resourceUri: string
    visibility?: ('model' | 'app')[]
}

export type ToolMeta = {
    ui?: ToolUiMeta
    // Legacy flat key for MCP Apps compatibility (ui/resourceUri)
    'ui/resourceUri'?: string
}
