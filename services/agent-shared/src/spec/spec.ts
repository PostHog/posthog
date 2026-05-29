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
            /**
             * When true, `/send` to a `closed` session reopens it (state
             * → queued, message appended to pending_inputs) instead of
             * returning 410. Default false — `meta-end-session` is
             * normally a hard close. Has no effect on `failed` sessions
             * (those stay terminal). See the session-restart redesign.
             */
            allow_restart: z.boolean().default(false),
        }),
    }),
    z.object({
        type: z.literal('mcp'),
        config: z
            .object({
                /** Mirror of the chat trigger flag — see above. */
                allow_restart: z.boolean().default(false),
            })
            .default({ allow_restart: false }),
    }),
])

/**
 * Approval policy attached to a tool ref. Authoritative defaults live here —
 * the dispatcher reads `ToolRef.approval_policy` directly after Zod parsing,
 * so omitting fields in the spec falls through to these values.
 *
 * `approvers` is a closed set in v0 (`team_admins` only); see plan §6.1 for
 * why richer scopes are deferred.
 */
export const ApprovalPolicySchema = z.object({
    approvers: z
        .array(z.enum(['team_admins']))
        .min(1)
        .default(['team_admins']),
    allow_edit: z.boolean().default(false),
    ttl_ms: z
        .number()
        .int()
        .min(60_000) // 1 minute
        .max(7 * 24 * 60 * 60 * 1000) // 7 days
        .default(24 * 60 * 60 * 1000), // 24h
    allow_agent_approver: z.boolean().default(false),
})

const DEFAULT_APPROVAL_POLICY = {
    approvers: ['team_admins' as const],
    allow_edit: false,
    ttl_ms: 24 * 60 * 60 * 1000,
    allow_agent_approver: false,
}

export const ToolRefSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('native'),
        id: z.string(),
        requires_approval: z.boolean().default(false),
        approval_policy: ApprovalPolicySchema.default(DEFAULT_APPROVAL_POLICY),
    }),
    z.object({
        kind: z.literal('custom'),
        id: z.string(),
        path: z.string(),
        requires_approval: z.boolean().default(false),
        approval_policy: ApprovalPolicySchema.default(DEFAULT_APPROVAL_POLICY),
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

/**
 * Author-facing knobs for the framework-injected system-prompt preamble.
 * See docs/agent-platform/plans/framework-system-prompt.md for the
 * section catalogue and rationale.
 */
export const FrameworkPromptSectionSchema = z.enum([
    /** Plan §3.1 — meta-tool decision rules. */
    'meta_tool_guidance',
    /** Plan §3.2 — `completed` vs `closed` contract. */
    'state_contract',
    /** Plan §3.3 — tool failure recovery flow. */
    'tool_failure_guidance',
    /** Plan §3.4 — approval-gated tool result envelope handling. */
    'approval_guidance',
    /** Plan §3.5 — extended-reasoning hint (only injected when spec.reasoning ∈ {high, xhigh}). */
    'reasoning_hint',
])

export const FrameworkPromptConfigSchema = z.object({
    /**
     * Sections to omit from the framework preamble. Reviewer-discoverable
     * (typed + validated at freeze time) escape hatch — see plan §7.4.
     * Unknown values are rejected by the enum.
     */
    omit: z.array(FrameworkPromptSectionSchema).default([]),
    /**
     * Pin the framework preamble version. When unset (default), the
     * runner uses the latest version. When set, the runner renders the
     * preamble as it was at that version — reproducibility escape hatch
     * for authors who don't want a platform upgrade to change frozen
     * revisions. See plan §7.3. Don't expect this to see much use.
     */
    version_pin: z.number().int().positive().optional(),
})

/**
 * Per-agent resumability config — the v0 slice of
 * `docs/agent-platform/plans/long-running-sessions.md`. v0 covers only the
 * per-agent TTL on `completed` sessions; compaction + `suspended` state
 * are deferred per the plan refresh.
 *
 * `enabled: false` (the default) preserves today's behaviour: the janitor
 * closes idle `completed` sessions at the platform-wide
 * `idleCompletedThresholdMs` (24h). With `enabled: true` the platform
 * defers closing until the per-agent `max_completed_age_ms` is hit,
 * letting a Slack assistant watch a thread for a whole sprint or a
 * weekly cron agent stay reachable across multiple fires.
 */
export const ResumeConfigSchema = z.object({
    enabled: z.boolean().default(false),
    /**
     * Override the platform-wide `completed → closed` sweep TTL. Default
     * 7 days; agents can dial up to whatever the platform admin allows.
     * Has no effect when `enabled: false`.
     */
    max_completed_age_ms: z
        .number()
        .int()
        .positive()
        .default(7 * 24 * 60 * 60 * 1000),
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
    reasoning: ReasoningEffortSchema.optional(),
    framework_prompt: FrameworkPromptConfigSchema.optional(),
    resume: ResumeConfigSchema.optional(),
})

export type AgentSpec = z.infer<typeof AgentSpecSchema>
export type Trigger = z.infer<typeof TriggerSchema>
export type ToolRef = z.infer<typeof ToolRefSchema>
export type ApprovalPolicy = z.infer<typeof ApprovalPolicySchema>
export type McpRef = z.infer<typeof McpRefSchema>
export type SkillRef = z.infer<typeof SkillRefSchema>
export type ReasoningEffort = z.infer<typeof ReasoningEffortSchema>
export type FrameworkPromptSection = z.infer<typeof FrameworkPromptSectionSchema>
export type FrameworkPromptConfig = z.infer<typeof FrameworkPromptConfigSchema>
export type ResumeConfig = z.infer<typeof ResumeConfigSchema>

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

/**
 * One slot in a session's ACL allowlist. Exactly one of `principal` or
 * `scope` is populated. `scope` is the "anyone matching this rule" form;
 * v0 ships the storage and the matcher but no UI populates it yet.
 */
export type SessionAclScope =
    | { kind: 'team_members'; team_id: number }
    | { kind: 'org_admins'; org_id: string }
    | { kind: 'slack_channel'; channel_id: string; workspace_id: string }

export interface SessionAclEntry {
    principal?: SessionPrincipal
    scope?: SessionAclScope
    granted_by: SessionPrincipal
    granted_at: string
    /** ISO timestamp; null means no expiry. */
    expires_at: string | null
    reason: string | null
    state: 'active' | 'revoked'
    revoked_by?: SessionPrincipal
    revoked_at?: string
    revoked_reason?: string
    /** v2: whether this grantee can grant further elevation. Default false. */
    can_delegate?: boolean
}

/**
 * A record of a rejected attempt to advance a session. Populated by the
 * ingress when `requireAclAccess` denies an incoming principal. v1 surfaces
 * these in the chat UI / Slack elevation message and lets the session owner
 * grant access (which moves the entry to `granted` and re-queues the
 * proposed message into `pending_inputs`).
 */
export interface PendingElevationRequest {
    id: string
    requester: SessionPrincipal
    requester_display: string
    trigger: 'chat' | 'webhook' | 'slack' | 'mcp'
    proposed_message: ConversationMessage
    created_at: string
    state: 'pending' | 'granted' | 'declined' | 'expired'
    decision_at?: string
    decision_by?: SessionPrincipal
}

export interface SessionUsageTotal {
    tokens_in: number
    tokens_out: number
    cache_read: number
    cache_write: number
    cost_input: number
    cost_output: number
    cost_cache_read: number
    cost_cache_write: number
    cost_total: number
}

export const EMPTY_USAGE_TOTAL: SessionUsageTotal = {
    tokens_in: 0,
    tokens_out: 0,
    cache_read: 0,
    cache_write: 0,
    cost_input: 0,
    cost_output: 0,
    cost_cache_read: 0,
    cost_cache_write: 0,
    cost_total: 0,
}

export interface AgentSession {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    /**
     * Session state. See docs/agent-platform/plans/_TODO.md (system-prompt
     * fleshing out) and the session-restart redesign for the contract:
     *
     *   queued    — awaiting a worker claim.
     *   running   — claimed; worker actively driving the turn.
     *   completed — agent finished its turn, session is OPEN. /send
     *               re-queues. Default end-of-turn state (natural stop,
     *               meta-end-turn, meta-ask-for-input).
     *   closed    — sealed by `meta-end-session`. Terminal. /send returns
     *               410 unless the trigger config sets `allow_restart`.
     *   cancelled — user invoked `/cancel`. Terminal. Same lifecycle
     *               semantics as `failed` (terminal regardless of
     *               `allow_restart`) but distinguishable in the UI and
     *               in observability so a user-initiated cancel isn't
     *               confused with a runtime error.
     *   failed    — error state. Terminal regardless of `allow_restart`.
     */
    state: 'queued' | 'running' | 'completed' | 'closed' | 'cancelled' | 'failed'
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
    /**
     * Append-only running totals updated by the runner after every assistant
     * turn. Lets list / rollup queries read cost off a single column instead
     * of walking the conversation JSONB. Backfilled from `conversation` for
     * sessions created before this column existed.
     */
    usage_total: SessionUsageTotal
    /**
     * Allowlist of additional principals (or scopes) on top of `principal`.
     * Empty by default. Consulted by `requireAclAccess` on every resume / send.
     * v0 has no UI to populate this; v1 adds the grant surface.
     */
    acl: SessionAclEntry[]
    /**
     * Rejected attempts to advance this session. Each entry preserves the
     * proposed message so a grant can replay it. v0 records these; v1
     * surfaces them in the chat UI / Slack thread.
     */
    pending_elevation_requests: PendingElevationRequest[]
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
    /**
     * Who sent this message. Populated by the ingress on every trigger that
     * accepts a user message (chat /run + /send, webhook, slack events, mcp
     * tools/call). Optional for backwards compatibility with existing rows;
     * absent on messages predating per-message principal stamping.
     *
     * Distinct from `AgentSession.principal` (the SESSION owner). When the
     * session ACL admits multiple principals (B.1), each message carries the
     * specific sender so per-asker authorisation (the gated-tool flow in #23)
     * can resolve "who's currently asking the bot to do X?"
     */
    sender?: SessionPrincipal
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
        cost?: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number; total?: number }
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
