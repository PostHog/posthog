/**
 * Native tools for reading agent-platform state — the agent-management
 * surface the concierge needs to inspect any agent (its own
 * application, other team agents, their revisions, sessions, logs).
 *
 * All tools share the credential-broker auth path (`_posthog-api.ts`):
 * the connected user's `posthog_api` bearer authenticates every call.
 * If the broker doesn't have a credential, every tool fails the same
 * way with `posthog_credentials_unavailable` and the agent.md
 * degradation rules kick in.
 *
 * Tool ids mirror the MCP catalog (e.g. `@posthog/agent-applications-list`
 * matches `agent-applications-list` in `services/mcp/definitions/agent_platform.yaml`)
 * so a future migration to MCP-routed dispatch keeps the same surface.
 *
 * **Read-only for v0.** Write operations (new_draft, file_update,
 * validate, freeze, promote) are deliberately not here yet — they want
 * the approval gating + user-confirmation skills before landing.
 */

import { defineNativeTool, type ToolContext, Type } from '@posthog/agent-shared'

import { callPosthogApi, projectPath } from './_posthog-api'

interface AgentApplication {
    id: string
    team: number
    name: string
    slug: string
    description: string
    live_revision: string | null
    archived: boolean
    archived_at: string | null
    created_by: number | null
    created_at: string
    updated_at: string
}

interface ListResponse<T> {
    count?: number
    next?: string | null
    previous?: string | null
    results: T[]
}

const AgentApplicationSchema = Type.Object({
    id: Type.String(),
    team: Type.Number(),
    name: Type.String(),
    slug: Type.String(),
    description: Type.String(),
    live_revision: Type.Union([Type.String(), Type.Null()]),
    archived: Type.Boolean(),
    archived_at: Type.Union([Type.String(), Type.Null()]),
    created_by: Type.Union([Type.Number(), Type.Null()]),
    created_at: Type.String(),
    updated_at: Type.String(),
})

/**
 * Resolve an application by slug OR id. Lookup by slug requires a list
 * call; lookup by id is direct. Lets the concierge accept either form
 * naturally without forcing slug→id translation upstream.
 */
async function resolveApplicationId(ctx: ToolContext, ref: { slug?: string; id?: string }): Promise<string> {
    if (ref.id) {
        return ref.id
    }
    if (!ref.slug) {
        throw new Error('agent_ref_required: provide either `slug` or `id`')
    }
    const list = await callPosthogApi<ListResponse<AgentApplication>>(ctx, {
        method: 'GET',
        path: projectPath(ctx, '/agent_applications/'),
    })
    const hit = list.results.find((a) => a.slug === ref.slug)
    if (!hit) {
        throw new Error(`agent_not_found: no agent with slug "${ref.slug}" in this project`)
    }
    return hit.id
}

/**
 * Agent-ref props spread into each tool's `args: Type.Object({...})`.
 *
 * Deliberately not a `Type.Object` wrapped via `Type.Intersect(...)` —
 * that compiles to JSON Schema `allOf`, and Anthropic's tool-call
 * validator doesn't merge `allOf.required` arrays. The model then sees
 * `session_id` (etc.) as optional and skips it. Flat `Type.Object`
 * with spread props produces the right `required` list.
 */
const agentRefFields = {
    slug: Type.Optional(Type.String({ description: 'Application slug (e.g. "weekly-digest"). Either this or id.' })),
    id: Type.Optional(Type.String({ description: 'Application UUID. Either this or slug.' })),
}

/* ──────────────────────────────────────────────────────────────────────
 * Agent applications
 * ────────────────────────────────────────────────────────────────────── */

export const posthogAgentApplicationsListV1 = defineNativeTool({
    id: '@posthog/agent-applications-list',
    description:
        "List every agent application the connected user can see in this project. Returns id, slug, name, description, live_revision. Use when the user asks 'what agents do I have?' / 'show me my agents'.",
    args: Type.Object({
        include_archived: Type.Optional(Type.Boolean({ description: 'Include archived agents (default false).' })),
    }),
    returns: Type.Object({ results: Type.Array(AgentApplicationSchema) }),
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const data = await callPosthogApi<ListResponse<AgentApplication>>(ctx, {
            method: 'GET',
            path: projectPath(ctx, '/agent_applications/'),
            query: args.include_archived ? { include_archived: 'true' } : undefined,
        })
        return { results: data.results }
    },
})

export const posthogAgentApplicationsRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-retrieve',
    description:
        'Get the full record of one agent application by slug or id. Returns its name, description, current live_revision, archived state. Use as step 1 of inspecting any agent.',
    args: Type.Object({ ...agentRefFields }),
    returns: AgentApplicationSchema,
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi<AgentApplication>(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/`),
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Revisions
 * ────────────────────────────────────────────────────────────────────── */

const RevisionSchema = Type.Object({
    id: Type.String(),
    application: Type.String(),
    parent_revision: Type.Union([Type.String(), Type.Null()]),
    state: Type.String(),
    bundle_uri: Type.String(),
    bundle_sha256: Type.Union([Type.String(), Type.Null()]),
    spec: Type.Record(Type.String(), Type.Unknown()),
    created_by: Type.Union([Type.Number(), Type.Null()]),
    created_at: Type.String(),
    updated_at: Type.String(),
})

export const posthogAgentApplicationsRevisionsListV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-list',
    description:
        "List every revision of one agent in chronological order — draft, ready, live, archived. Use to see the agent's edit history or to find a specific revision to inspect.",
    args: Type.Object({ ...agentRefFields }),
    returns: Type.Object({ results: Type.Array(RevisionSchema) }),
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        const data = await callPosthogApi<ListResponse<unknown>>(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/revisions/`),
        })
        return data as { results: never }
    },
})

export const posthogAgentApplicationsRevisionsRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-retrieve',
    description:
        'Get a specific revision of an agent. Returns the full spec (model, triggers, tools, skills, limits, auth) plus the bundle_sha256 + state. Use to inspect what an agent is configured to do.',
    args: Type.Object({
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: RevisionSchema,
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/revisions/${args.revision_id}/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsSystemPromptV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-system-prompt',
    description:
        'Get the fully-rendered system prompt for a revision — what the model actually sees on every turn (framework preamble + agent.md + skills index). The single most informative artifact when explaining what an agent does.',
    args: Type.Object({
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Object({
        revision_id: Type.String(),
        framework_prompt_version: Type.Number(),
        system_prompt: Type.String(),
    }),
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/revisions/${args.revision_id}/system_prompt/`),
        })
    },
})

const ManifestFileSchema = Type.Object({
    path: Type.String(),
    size: Type.Number(),
    sha256: Type.String(),
})

export const posthogAgentApplicationsRevisionsManifestV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-manifest-retrieve',
    description:
        "List every file in a revision's bundle (path + size + sha256). Use to see the bundle layout before pulling specific files. Cheap — no file content returned.",
    args: Type.Object({
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
    }),
    returns: Type.Object({
        revision_id: Type.String(),
        state: Type.String(),
        bundle_sha256: Type.Union([Type.String(), Type.Null()]),
        files: Type.Array(ManifestFileSchema),
    }),
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/revisions/${args.revision_id}/manifest/`),
        })
    },
})

export const posthogAgentApplicationsRevisionsFileV1 = defineNativeTool({
    id: '@posthog/agent-applications-revisions-file-retrieve',
    description:
        "Read one file from a revision's bundle by path (e.g. 'agent.md', 'skills/research/SKILL.md'). Returns the file's text content. Use after manifest-retrieve to pull specific files.",
    args: Type.Object({
        ...agentRefFields,
        revision_id: Type.String({ description: 'Revision UUID.' }),
        path: Type.String({ description: 'Bundle-relative path, e.g. "skills/research/SKILL.md".' }),
    }),
    returns: Type.Object({ path: Type.String(), content: Type.String() }),
    requires: { integrations: [], scopes: ['agent_application:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/revisions/${args.revision_id}/file/`),
            query: { path: args.path },
        })
    },
})

/* ──────────────────────────────────────────────────────────────────────
 * Sessions
 * ────────────────────────────────────────────────────────────────────── */

const SessionSummarySchema = Type.Object({
    id: Type.String(),
    state: Type.String(),
    revision_id: Type.String(),
    external_key: Type.Union([Type.String(), Type.Null()]),
    created_at: Type.String(),
    updated_at: Type.String(),
    usage_total: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
})

export const posthogAgentApplicationsSessionsListV1 = defineNativeTool({
    id: '@posthog/agent-applications-sessions-list',
    description:
        'List recent sessions for an agent. Returns state, created_at, usage_total per session. Use to see what an agent has been doing or to find a specific session to debug.',
    args: Type.Object({
        ...agentRefFields,
        limit: Type.Optional(Type.Number({ description: 'Max sessions to return (default 50).' })),
        state: Type.Optional(
            Type.String({
                description: 'Filter by state: queued | running | completed | closed | cancelled | failed.',
            })
        ),
    }),
    returns: Type.Object({
        count: Type.Optional(Type.Number()),
        next: Type.Optional(Type.Union([Type.String(), Type.Null()])),
        results: Type.Array(SessionSummarySchema),
    }),
    requires: { integrations: [], scopes: ['agent_session:read'] },
    cost_hint: 'cheap',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/sessions/`),
            query: { limit: args.limit, state: args.state },
        })
    },
})

export const posthogAgentApplicationsSessionsRetrieveV1 = defineNativeTool({
    id: '@posthog/agent-applications-sessions-retrieve',
    description:
        'Get the full record of one session, including its conversation (all user/assistant/tool turns), principal, usage_total, and state. The primary tool for debugging a specific session.',
    args: Type.Object({
        ...agentRefFields,
        session_id: Type.String({ description: 'Session UUID.' }),
    }),
    returns: Type.Record(Type.String(), Type.Unknown()),
    requires: { integrations: [], scopes: ['agent_session:read'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/sessions/${args.session_id}/`),
        })
    },
})

export const posthogAgentApplicationsSessionLogsV1 = defineNativeTool({
    id: '@posthog/agent-applications-session-logs',
    description:
        "Get the structured event log for a session — session_started, turn_started, tool_call, tool_result, completed/failed events. Use after sessions-retrieve when you need turn-by-turn timing or error events the conversation doesn't carry.",
    args: Type.Object({
        ...agentRefFields,
        session_id: Type.String({ description: 'Session UUID.' }),
    }),
    returns: Type.Object({
        events: Type.Array(Type.Record(Type.String(), Type.Unknown())),
    }),
    requires: { integrations: [], scopes: ['agent_session:read'] },
    cost_hint: 'medium',
    async run(args, ctx) {
        const id = await resolveApplicationId(ctx, args)
        return callPosthogApi(ctx, {
            method: 'GET',
            path: projectPath(ctx, `/agent_applications/${id}/sessions/${args.session_id}/logs/`),
        })
    },
})
