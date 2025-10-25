import type { ApiClient } from '@/api/client'
import type { PrefixedString } from '@/lib/types'
import type { StateManager } from '@/lib/utils/StateManager'
import type { SessionManager } from '@/lib/utils/SessionManager'
import type { ScopedCache } from '@/lib/utils/cache/ScopedCache'
import type { ApiRedactedPersonalApiKey } from '@/schema/api'
import type { z } from 'zod'

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
    INKEEP_API_KEY: string | undefined
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
}

export type ToolBase<TSchema extends z.ZodTypeAny = z.ZodTypeAny> = Omit<
    Tool<TSchema>,
    'title' | 'description' | 'scopes' | 'annotations'
>

export type ZodObjectAny = z.ZodObject<any, any, any, any, any>
