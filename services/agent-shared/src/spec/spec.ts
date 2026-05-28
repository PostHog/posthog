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
            /**
             * Required. Workspaces (Slack team ids, e.g. "T01ABC") allowed to
             * invoke this agent. Use the literal string `"*"` to opt into an
             * open-to-any-workspace policy (B2C-style public bot). Authors
             * MUST make the choice explicitly — there is no implicit
             * "any-workspace" default.
             */
            trusted_workspaces: z.union([z.array(z.string()).min(1), z.literal('*')]),
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
    /**
     * Short summary shown in the system-prompt skill index. The model decides
     * whether to call `@posthog/load-skill` based on this description, so it
     * should describe WHAT the skill teaches the agent and WHEN to load it.
     */
    description: z.string().optional(),
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

/**
 * Normalized reasoning-effort knob. Matches pi-ai's `ThinkingLevel` exactly,
 * so the runner can forward `spec.reasoning` straight to
 * `completeSimple()` without translation. Provider-specific mappings
 * (Anthropic extended thinking, OpenAI o-series, Gemini thinking) are
 * handled inside pi-ai. Omitting the field uses the provider default —
 * important so existing agents don't get reasoning charges they didn't
 * opt into.
 */
export const ReasoningEffortSchema = z.enum(['minimal', 'low', 'medium', 'high', 'xhigh'])

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
    reasoning: ReasoningEffortSchema.optional(),
})

export type AgentSpec = z.infer<typeof AgentSpecSchema>
export type Trigger = z.infer<typeof TriggerSchema>
export type ToolRef = z.infer<typeof ToolRefSchema>
export type McpRef = z.infer<typeof McpRefSchema>
export type SkillRef = z.infer<typeof SkillRefSchema>
export type ReasoningEffort = z.infer<typeof ReasoningEffortSchema>

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
    /** Posthog user id (Django FK). Null for revisions created outside the auth flow (tests, system). */
    created_by_id: number | null
    created_at: string
    state: RevisionState
    bundle_uri: string
    bundle_sha256: string | null
    spec: AgentSpec
}

export interface SessionPrincipal {
    /** "anonymous" | "service" | "internal" | "shared_secret" | "slack" */
    kind: string
    team_id?: number
    /** Stable identifier for the principal — pat_id, slack user, etc. */
    id?: string
}

export interface AgentSession {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    state: 'queued' | 'running' | 'waiting' | 'completed' | 'failed'
    /**
     * Principal that authenticated `/run`. Subsequent `/send` calls must
     * carry a principal that matches (same kind + id). Null for sessions
     * started without auth on public agents.
     */
    principal: SessionPrincipal | null
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
    /**
     * Times the janitor has re-queued this session after a stuck-running
     * detection. Past the configured threshold the session is failed instead
     * (poison-pill handling). 0 for fresh sessions.
     */
    retry_count: number
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
