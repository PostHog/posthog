/**
 * AgentRevision spec — the structural/queryable layer.
 *
 * Lives in the DB as JSONB. The S3 bundle holds the content layer (agent.md,
 * skills tree, per-tool source.ts + compiled.js). See docs/native-refactor.md §1.
 */

import { z } from 'zod'

export const ModelIdSchema = z.string().min(1)

export const TriggerSchema = z.discriminatedUnion('type', [
    z.object({
        type: z.literal('slack'),
        config: z.object({
            channel_id: z.string().optional(),
            mention_only: z.boolean().default(false),
        }),
    }),
    z.object({
        type: z.literal('webhook'),
        config: z.object({
            path: z.string(),
            secret: z.string().optional(),
        }),
    }),
    z.object({
        type: z.literal('cron'),
        config: z.object({
            schedule: z.string(),
            timezone: z.string().default('UTC'),
        }),
    }),
    z.object({
        type: z.literal('chat'),
        config: z.object({
            require_auth: z.boolean().default(true),
        }),
    }),
    z.object({
        type: z.literal('mcp'),
        config: z.object({}).default({}),
    }),
])

export const ToolRefSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('native'),
        id: z.string(),
    }),
    z.object({
        kind: z.literal('custom'),
        id: z.string(),
        path: z.string(),
    }),
])

export const McpRefSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('agent'),
        slug: z.string(),
    }),
    z.object({
        kind: z.literal('external'),
        url: z.string().url(),
        auth: z
            .object({
                integration: z.string().optional(),
            })
            .optional(),
        allowlist: z.array(z.string()).optional(),
    }),
])

export const SkillRefSchema = z.object({
    id: z.string(),
    path: z.string(),
})

export const SpecLimitsSchema = z.object({
    max_turns: z.number().int().positive().default(50),
    max_tool_calls: z.number().int().positive().default(200),
    max_wall_seconds: z
        .number()
        .int()
        .positive()
        .default(15 * 60),
})

export const AuthModeSchema = z.enum(['public', 'pat', 'posthog_internal', 'shared_secret'])
export const AuthConfigSchema = z.object({
    mode: AuthModeSchema.default('public'),
    /** For shared_secret mode: name of the HTTP header carrying the secret. */
    header: z.string().optional(),
})

export const AgentSpecSchema = z.object({
    model: ModelIdSchema,
    triggers: z.array(TriggerSchema).default([]),
    tools: z.array(ToolRefSchema).default([]),
    mcps: z.array(McpRefSchema).default([]),
    skills: z.array(SkillRefSchema).default([]),
    integrations: z.array(z.string()).default([]),
    secrets: z.array(z.string()).default([]),
    limits: SpecLimitsSchema.default({ max_turns: 50, max_tool_calls: 200, max_wall_seconds: 15 * 60 }),
    entrypoint: z.string().default('agent.md'),
    auth: AuthConfigSchema.default({ mode: 'public' }),
})

export type AgentSpec = z.infer<typeof AgentSpecSchema>
export type Trigger = z.infer<typeof TriggerSchema>
export type ToolRef = z.infer<typeof ToolRefSchema>
export type McpRef = z.infer<typeof McpRefSchema>
export type SkillRef = z.infer<typeof SkillRefSchema>

export type RevisionState = 'draft' | 'ready' | 'live' | 'archived'

export interface AgentApplication {
    id: string
    team_id: number
    slug: string
    name: string
    description: string
    live_revision_id: string | null
    archived: boolean
    encrypted_env: string | null
}

export interface AgentRevision {
    id: string
    application_id: string
    parent_revision_id: string | null
    created_by: string
    created_at: string
    state: RevisionState
    bundle_uri: string
    bundle_sha256: string | null
    spec: AgentSpec
}

export interface AgentSession {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    state: 'queued' | 'running' | 'waiting' | 'completed' | 'failed'
    /**
     * The active conversation history. Built up turn-by-turn. Uses pi-ai's
     * Message shape verbatim so the runner can hand it straight to `complete()`.
     */
    conversation: ConversationMessage[]
    /**
     * Inputs that arrived while a turn was in flight. The runner drains this
     * into `conversation` at the start of the next turn. Lets `/send` calls
     * during a running turn be durable without contending on the active
     * conversation list. See docs/native-refactor.md (queued-followups).
     */
    pending_inputs: ConversationMessage[]
    created_at: string
    updated_at: string
}

/**
 * One message in a session's conversation. Structurally identical to pi-ai's
 * `Message` so the runner can pass `conversation` directly as
 * `Context.messages`. We re-declare it (rather than `import type`) to keep
 * agent-shared-v2 free of a forced dependency on pi-ai at the import site.
 */
export type ConversationMessage = UserMessage | AssistantMessageRecord | ToolResultMessage

export interface UserMessage {
    role: 'user'
    content: string | (TextContent | ImageContent)[]
    timestamp: number
}

/**
 * Renamed to AssistantMessageRecord to avoid colliding with pi-ai's exported
 * AssistantMessage type when consumers re-export both.
 */
export interface AssistantMessageRecord {
    role: 'assistant'
    content: (TextContent | ThinkingContent | ToolCall)[]
    api?: string
    provider?: string
    model?: string
    usage?: {
        input: number
        output: number
        cacheRead?: number
        cacheWrite?: number
        totalTokens?: number
        cost?: { input?: number; output?: number; total?: number }
    }
    stopReason?: 'stop' | 'length' | 'toolUse' | 'error' | 'aborted'
    errorMessage?: string
    timestamp: number
}

export interface ToolResultMessage {
    role: 'toolResult'
    toolCallId: string
    toolName: string
    content: (TextContent | ImageContent)[]
    isError: boolean
    timestamp: number
}

export interface TextContent {
    type: 'text'
    text: string
}

export interface ImageContent {
    type: 'image'
    data: string
    mimeType: string
}

export interface ThinkingContent {
    type: 'thinking'
    thinking: string
    thinkingSignature?: string
    redacted?: boolean
}

export interface ToolCall {
    type: 'toolCall'
    id: string
    name: string
    arguments: Record<string, unknown>
}
