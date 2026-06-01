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
/**
 * Approver scopes accepted in v0:
 *   - `team_admins` — any user with the `org_admin` / `team_admin` role on
 *     the owning team. The default scope on every gated tool.
 *   - `session_principal` — the auth-time principal stored on the session
 *     row (NOT the most recent /send sender — see B1 in
 *     `runtime-mcps.md` "Resolved design"). Used by the concierge so the
 *     session owner can authorise their own destructive call without
 *     round-tripping through a team admin; a second user posting to a
 *     resumed session can't bypass the gate. v0 is per-asker fast-path
 *     only — queued-approval routing to the session principal widens
 *     later via approver-scope routing in `approval-gated-tools.md` §6.
 */
export const ApproverScopeSchema = z.enum(['team_admins', 'session_principal'])

export const ApprovalPolicySchema = z.object({
    approvers: z.array(ApproverScopeSchema).min(1).default(['team_admins']),
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
    /**
     * **Client-fulfilled tool.** The agent author declares the tool fully
     * inline (id + description + args_schema); the connecting client
     * (browser dock, IDE MCP host, etc.) advertises which ids it can
     * fulfill at session start via `client.handles[]`. The runner
     * reconciles:
     *
     *   - In spec AND in `client.handles[]` → exposed to the model.
     *   - In spec, NOT handled, `required: false` (default) → hidden
     *     from the model surface; the agent.md should be written to
     *     degrade gracefully (text-only narration).
     *   - In spec, NOT handled, `required: true` → session open fails
     *     with `client_tool_unsupported`.
     *
     * Dispatch path: when the model calls the tool, the runner emits a
     * `client_tool_call` session event carrying the args + a call_id;
     * the client executes locally and POSTs the result to
     * `/sessions/<id>/client_tool_result`. See
     * docs/agent-platform/plans/agent-console-website.md §8.
     */
    z.object({
        kind: z.literal('client'),
        /**
         * Tool id the model sees. Author-chosen; must not collide with
         * other tools in the same spec. Convention: short snake_case
         * names (`focus`, `toast`, `get_context`) — no required prefix.
         */
        id: z.string().min(1),
        /**
         * Human-readable + model-readable description. Same as native
         * tool descriptions; this is the primary signal the model uses
         * to decide when to call the tool.
         */
        description: z.string().min(1),
        /**
         * JSON Schema for the tool's args. Held as a free-form object
         * because spec authors define their own shape per tool — the
         * runner doesn't introspect it.
         */
        args_schema: z.record(z.string(), z.unknown()).default({}),
        /**
         * When false (the default), missing client support → tool hidden,
         * session proceeds. When true, missing client support → session
         * open fails.
         */
        required: z.boolean().default(false),
        /**
         * Per-call timeout in ms. Default 5s — UI tools should answer in
         * <100ms; if they don't, the user closed the tab or follow-mode
         * is off. Author may raise for slower client operations.
         */
        timeout_ms: z.number().int().positive().max(60_000).default(5_000),
    }),
])

/**
 * Per-tool selection + approval-gating entry for `external` MCP refs. The
 * bare-string form is the inclusion-only case (was `allowlist[]` pre-PR 7);
 * the object form adds approval gating using the same primitives as
 * `ToolRefSchema` (`requires_approval` + `approval_policy`). The dispatcher
 * looks the entry up by name when wrapping the model-visible
 * `<prefix>__<remoteName>` tool — see
 * `services/agent-runner/src/loop/mcp-tool-lookup.ts` and the approval-wrap
 * fallback in `driver.ts`.
 */
export const McpToolEntrySchema = z.union([
    z.string().min(1),
    z.object({
        /** Raw remote tool name (pre-prefix). Must match an entry from `client.listTools()`. */
        name: z.string().min(1),
        requires_approval: z.boolean().default(false),
        approval_policy: ApprovalPolicySchema.default(DEFAULT_APPROVAL_POLICY),
    }),
])

/**
 * Runtime MCP servers an agent connects to at session start. The runner opens
 * one client per entry, exposes each remote tool as a regular `AgentTool` to
 * pi-ai (name-prefixed `<id>__<toolName>`), and routes dispatch back through
 * the open client. See `docs/agent-platform/plans/runtime-mcps.md`.
 *
 * Two variants:
 *   - `agent` — points at another PostHog agent's MCP server (`spec.triggers`
 *     of type `mcp` on the target). Auth piggybacks on `posthog_internal`;
 *     the runner resolves the route from the local revision store. Acts as
 *     the in-platform composability shortcut (see
 *     `docs/agent-platform/plans/agent-as-mcp-server.md` §9). Uses `slug` as
 *     the tool-name prefix. No per-tool gating: the target agent owns its
 *     own approval policy via its own `spec.tools[]`, so re-gating at the
 *     caller side would be redundant.
 *   - `external` — a third-party MCP server reachable over HTTP. `auth.integration`
 *     plugs into PostHog's integrations registry (OAuth-style); `secrets[]`
 *     is the simpler per-MCP token case, resolved through the same
 *     encrypted-env path the agent's main `spec.secrets` uses. Uses `id` as
 *     the tool-name prefix. `tools[]` selects + gates: bare string = inclusion
 *     only; object form adds `requires_approval` + `approval_policy`.
 *
 * **Future migration (not blocking):** the runtime-mcps plan describes a
 * flatter shape `{ id, endpoint, tools[], secrets[] }` with no discriminator,
 * mirrored by the concierge example bundle. We're holding the union for now
 * because the console + spec tests already depend on the `kind` discriminator
 * — flattening would be a multi-PR migration with no functional payoff. When
 * we revisit (likely tied to v2 of the runtime-mcp surface), the `agent`
 * variant becomes `{ id: slug, endpoint: '<internal-url>', ... }` and the
 * discriminator disappears.
 */
export const McpRefSchema = z.discriminatedUnion('kind', [
    z.object({
        kind: z.literal('agent'),
        /** Target agent slug. Doubles as the tool-name prefix at runtime. */
        slug: z.string(),
    }),
    z.object({
        kind: z.literal('external'),
        /**
         * Stable id within the spec. Tool-name prefix at runtime —
         * `<id>__<toolName>` is what the model sees so it can tell which MCP
         * a tool came from. Must be unique across `spec.mcps[]`.
         */
        id: z.string().min(1),
        url: z.string().url(),
        auth: z
            .object({
                integration: z.string().optional(),
            })
            .optional(),
        /**
         * Per-MCP secret names. Resolved at session start through the same
         * encrypted-env path as the agent's main `spec.secrets`. The runner
         * substitutes `${name}` placeholders in the URL + auth headers before
         * opening the client; the plaintext never leaves the runner process.
         */
        secrets: z.array(z.string()).default([]),
        /**
         * Per-tool selection AND approval gating. Bare string is a passthrough
         * (gates inclusion, no approval); object form carries
         * `requires_approval` + `approval_policy`. Omitted / empty = expose
         * every tool the server lists. Replaces the earlier `allowlist[]`
         * field (PR 7 hard-break — no production specs used it).
         */
        tools: z.array(McpToolEntrySchema).optional(),
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

/**
 * Auth modes — each entry is a discriminated variant. A spec can accept
 * multiple modes simultaneously; the ingress verifier tries each in order
 * and the first that matches the incoming request wins.
 *
 * The principle running through the design: **identity (who) is separate
 * from credentials (what tokens)**. Verifier produces a `SessionPrincipal`
 * (stored on the session row, identity-only) plus a `credentials` map
 * (stashed in the `CredentialBroker` for tool runtime to query at call
 * time — never persisted, never on the principal).
 */
export const AuthModeSchema = z.discriminatedUnion('type', [
    /** Anonymous — no auth required. */
    z.object({ type: z.literal('public') }),
    /** PostHog OAuth bearer. Validated against `issuer`'s introspection
     *  endpoint (for `issuer: 'posthog'`, that's `/api/users/@me/`).
     *  Credential available to tools as target `posthog_api`. */
    z.object({
        type: z.literal('oauth'),
        issuer: z.string().min(1),
        scopes: z.array(z.string()).default([]),
    }),
    /** PostHog Personal API Key bearer. Same validation endpoint as oauth
     *  for PostHog (PostHog accepts both). Credential as `posthog_api`. */
    z.object({ type: z.literal('pat') }),
    /** JWT signed with the named encrypted-env secret. Lets a B2B
     *  embedder mint identity tokens for their users without going
     *  through OAuth. Credential available to tools as `self` (the JWT
     *  itself + decoded claims). */
    z.object({
        type: z.literal('jwt'),
        issuer_secret_ref: z.string().min(1),
    }),
    /** A shared secret in a named header. Mostly for webhook triggers. */
    z.object({
        type: z.literal('shared_secret'),
        header: z.string().min(1),
    }),
    /** PostHog-internal server-to-server token (for Django ↔ ingress). */
    z.object({ type: z.literal('posthog_internal') }),
])

export const AuthConfigSchema = z.object({
    /** Accepted auth modes. First successful match per request wins. */
    modes: z.array(AuthModeSchema).default([{ type: 'public' }]),
})

export type AuthMode = z.infer<typeof AuthModeSchema>
export type AuthModeType = AuthMode['type']

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
    auth: AuthConfigSchema.default({ modes: [{ type: 'public' }] }),
    reasoning: ReasoningEffortSchema.optional(),
    framework_prompt: FrameworkPromptConfigSchema.optional(),
    resume: ResumeConfigSchema.optional(),
})

export type AgentSpec = z.infer<typeof AgentSpecSchema>
export type Trigger = z.infer<typeof TriggerSchema>
export type ToolRef = z.infer<typeof ToolRefSchema>
export type ApprovalPolicy = z.infer<typeof ApprovalPolicySchema>
export type ApproverScope = z.infer<typeof ApproverScopeSchema>
export type McpRef = z.infer<typeof McpRefSchema>
export type McpToolEntry = z.infer<typeof McpToolEntrySchema>
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

/**
 * Session-bound identity — **never carries tokens**. Tokens live in the
 * `CredentialBroker` keyed by session_id; this struct is the persisted
 * "who" answer that the ACL machinery + audit log consume.
 *
 * Discriminated by `kind`; each variant carries whatever fields uniquely
 * identify that principal type. New auth modes should add a new variant
 * here rather than overloading existing ones.
 */
export type SessionPrincipal =
    | { kind: 'anonymous' }
    /** PostHog OAuth or PAT — both resolve through `/api/users/@me/`. */
    | {
          kind: 'posthog'
          source: 'oauth' | 'pat'
          user_id: string
          user_uuid?: string
          team_id: number
          email?: string
          scopes?: string[]
      }
    /** JWT signed with the agent's configured secret. `sub` + `claims`
     *  are author-defined; the platform treats them as opaque. */
    | {
          kind: 'jwt'
          issuer_secret_ref: string
          sub: string
          claims: Record<string, unknown>
      }
    /**
     * Slack user resolved through the slack integration. Pure Slack
     * identity only — any cross-platform linkage (e.g. "this Slack user
     * maps to a PostHog user") is a credential-resolution concern, not
     * an identity property. The broker resolves `posthog_api` for a
     * Slack principal by looking up `agent_user_id → posthog user →
     * stored auth`; if nothing's stored, the broker returns null and
     * the tool degrades.
     */
    | {
          kind: 'slack'
          workspace_id: string
          slack_user_id: string
          agent_user_id?: string
      }
    /** Internal / service-to-service caller (PostHog backend → ingress). */
    | { kind: 'posthog_internal'; team_id?: number }
    /** Shared-secret bearer (webhook-style). */
    | { kind: 'shared_secret'; team_id?: number }
    /** Cron / scheduler / other system principals. */
    | { kind: 'service'; team_id?: number; id?: string }

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
     *               meta-end-turn).
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
