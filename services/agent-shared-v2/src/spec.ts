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
    conversation: ConversationMessage[]
    created_at: string
    updated_at: string
}

export type ConversationMessage =
    | { role: 'user'; content: string | UserContentBlock[] }
    | { role: 'assistant'; content: AssistantContentBlock[] }

export type UserContentBlock =
    | { type: 'text'; text: string }
    | { type: 'tool_result'; tool_use_id: string; content: string; is_error?: boolean }

export type AssistantContentBlock =
    | { type: 'text'; text: string }
    | { type: 'tool_use'; id: string; name: string; input: unknown }
