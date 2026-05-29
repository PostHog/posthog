/**
 * Build the `AgentTool[]` for a session — the tool surface pi-agent-core's
 * loop dispatches against. Replaces the old split between `build-tool-list.ts`
 * (declarations for pi-ai) and `tool-dispatch.ts` (in-process routing): each
 * tool now carries its own `execute`, so the loop validates args against
 * `parameters` and calls `execute` directly.
 *
 * Three tool sources, mirroring the old `buildToolList` + `dispatchTool`:
 *   1. Always-on meta control-flow (`meta-end-turn`, `meta-ask-for-input`,
 *      `meta-end-session`) — surfaced as `terminate` results carrying a
 *      `control` detail the driver reads to derive the run outcome. These are
 *      intercepted before `native.run` (they never execute), exactly as
 *      `tool-dispatch.ts` did.
 *   2. Native tools (incl. `@posthog/load-skill` when the agent has skills) —
 *      `execute` builds the same `ToolContext` the old dispatcher did and calls
 *      `native.run`.
 *   3. Custom tools — `execute` routes to `sandbox.invoke`; the arg schema and
 *      description load from `<path>/schema.json` in the bundle.
 *
 * Tool-result content is kept byte-identical to the old path: a successful
 * call returns `JSON.stringify(result)` as text; a failure throws, which the
 * loop renders as an error tool_result (content = the thrown message,
 * `isError: true`) — the same shape `dispatchOne` produced. Analytics spans
 * are NOT emitted here; the driver's `tool_execution_end` sink owns that, which
 * is why each result stashes the raw return value in `details.output`.
 */

import type { AgentTool, AgentToolResult } from '@earendil-works/pi-agent-core'
import type { TSchema } from '@earendil-works/pi-ai'

import {
    AgentRevision,
    AgentSession,
    BundleStore,
    IntegrationCredentials,
    Sandbox,
    ToolContext,
} from '@posthog/agent-shared'
import { getNativeTool, hasNativeTool } from '@posthog/agent-tools'

import { buildToolNameMap } from './provider-safe-names'

/**
 * Meta control-flow tools — always exposed, intercepted as `terminate` results
 * instead of executing. Kept in sync with the meta tools the registry defines.
 * `@posthog/meta-emit-event` is deliberately absent: it runs like any native.
 */
export const ALWAYS_ON_NATIVE_TOOL_IDS = [
    '@posthog/meta-end-turn',
    '@posthog/meta-ask-for-input',
    '@posthog/meta-end-session',
]

const CONTROL_FLOW_IDS = new Set(ALWAYS_ON_NATIVE_TOOL_IDS)

/** Control signal a meta tool surfaces to the driver via `AgentToolResult.details`. */
export type MetaControl = { kind: 'end_turn'; prompt?: string } | { kind: 'close'; summary?: string }

/** `details` shape every tool in this adapter returns. */
export interface ToolResultDetails {
    /** Present only for meta control-flow tools — the driver maps this to a RunOutcome. */
    control?: MetaControl
    /** Raw native return value / sandbox result, for the analytics span `output`. */
    output?: unknown
    /** Set when a gated tool returned a synthetic queued-for-approval result. */
    queued?: boolean
    /** The approval request id, when `queued`. */
    requestId?: string
}

/**
 * A tool's real `execute` — the un-gated path. The driver keeps a reference to
 * each tool's original execute so an approved call can be dispatched on resume
 * even after the gated tool's execute has been swapped for the queue path.
 */
export type RealToolExecute = (
    toolCallId: string,
    args: Record<string, unknown>
) => Promise<AgentToolResult<ToolResultDetails>>

/** Per-session context the tool `execute` closures need. Supplied by the driver. */
export interface AgentToolDeps {
    rev: AgentRevision
    session: AgentSession
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    /** Resolved plaintext secrets for native tools (custom tools get nonces via the sandbox). */
    secrets: Record<string, string>
    bundle: BundleStore
    log: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
}

export interface BuiltAgentTools {
    tools: AgentTool<TSchema, ToolResultDetails>[]
    /** providerSafeName → original tool id. Tools are registered under their
     * original ids (the loop matches calls by name); the driver's streamFn
     * sanitizes names on the wire and uses this map to translate the names a
     * strict provider echoes back to the original before the loop matches. */
    nameToId: Map<string, string>
}

export async function buildAgentTools(rev: AgentRevision, deps: AgentToolDeps): Promise<BuiltAgentTools> {
    const tools: AgentTool<TSchema, ToolResultDetails>[] = []
    const seen = new Set<string>()

    // `@posthog/load-skill` is auto-included only when the agent has skills —
    // exposing it otherwise just adds a tool that errors on use.
    const alwaysOn = [...ALWAYS_ON_NATIVE_TOOL_IDS]
    if (rev.spec.skills.length > 0) {
        alwaysOn.push('@posthog/load-skill')
    }
    const all = [...alwaysOn.map((id) => ({ kind: 'native' as const, id })), ...rev.spec.tools]

    for (const t of all) {
        if (seen.has(t.id)) {
            continue
        }
        seen.add(t.id)

        if (CONTROL_FLOW_IDS.has(t.id)) {
            tools.push(makeControlFlowTool(t.id))
            continue
        }
        if (t.kind === 'native') {
            // Unknown native id (stale spec): skip, exactly as buildToolList did.
            if (!hasNativeTool(t.id)) {
                seen.delete(t.id)
                continue
            }
            tools.push(makeNativeTool(t.id, deps))
            continue
        }
        // custom — schema + description from the bundle, dispatched via sandbox.
        const { description, parameters } = await loadCustomSchema(rev, t.id, t.path, deps.bundle)
        tools.push(makeCustomTool(t.id, description, parameters, deps))
    }

    // Tools are named with their original ids (the loop matches calls by name).
    // The map keys the provider-safe form back to the original so the driver's
    // streamFn can translate names a strict provider echoed back.
    return { tools, nameToId: buildToolNameMap(tools.map((t) => t.name)) }
}

function makeControlFlowTool(id: string): AgentTool<TSchema, ToolResultDetails> {
    const native = getNativeTool(id)
    return {
        name: id,
        label: id,
        description: native.schema.description,
        parameters: native.schema.args,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            if (id === '@posthog/meta-end-session') {
                const summary = (args as { summary?: string }).summary
                return {
                    content: [{ type: 'text', text: JSON.stringify({ ended: true }) }],
                    details: { control: { kind: 'close', summary } },
                    terminate: true,
                }
            }
            const prompt =
                id === '@posthog/meta-ask-for-input' ? ((args as { prompt?: string }).prompt ?? '') : undefined
            return {
                content: [{ type: 'text', text: JSON.stringify({ ended_turn: true }) }],
                details: { control: { kind: 'end_turn', prompt } },
                terminate: true,
            }
        },
    }
}

function makeNativeTool(id: string, deps: AgentToolDeps): AgentTool<TSchema, ToolResultDetails> {
    const native = getNativeTool(id)
    return {
        name: id,
        label: id,
        description: native.schema.description,
        parameters: native.schema.args,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            // Throws propagate: the loop renders them as an error tool_result
            // (content = message, isError: true) — same shape as the old path.
            const result = await native.run(args, buildToolContext(deps))
            return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
        },
    }
}

function makeCustomTool(
    id: string,
    description: string,
    parameters: TSchema,
    deps: AgentToolDeps
): AgentTool<TSchema, ToolResultDetails> {
    return {
        name: id,
        label: id,
        description,
        parameters,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            if (!deps.sandbox) {
                throw new Error(`custom tool ${id} requires a sandbox`)
            }
            const r = await deps.sandbox.invoke({ toolId: id, action: 'default', args })
            if (!r.ok) {
                throw new Error(`${r.error.code}: ${r.error.message}`)
            }
            return { content: [{ type: 'text', text: JSON.stringify(r.result) }], details: { output: r.result } }
        },
    }
}

/** Replicates the `ToolContext` the old `dispatchTool` built for native tools. */
function buildToolContext(deps: AgentToolDeps): ToolContext {
    return {
        teamId: deps.session.team_id,
        applicationId: deps.rev.application_id,
        sessionId: deps.session.id,
        integrations: deps.integrations,
        secret: (name) => deps.secrets[name],
        log: deps.log,
        skillIndex: deps.rev.spec.skills.map((s) => ({ id: s.id, description: s.description, path: s.path })),
        readBundleFile: async (path: string): Promise<string | null> => {
            try {
                return await deps.bundle.readText(deps.rev.id, path)
            } catch {
                return null
            }
        },
    }
}

async function loadCustomSchema(
    rev: AgentRevision,
    id: string,
    path: string,
    bundle: BundleStore
): Promise<{ description: string; parameters: TSchema }> {
    const schemaPath = `${path.replace(/\/$/, '')}/schema.json`
    try {
        const raw = await bundle.readText(rev.id, schemaPath)
        const schema = JSON.parse(raw) as { description?: string; args?: unknown }
        return {
            description: schema.description ?? `custom tool ${id}`,
            parameters: (schema.args as TSchema) ?? ({ type: 'object' } as unknown as TSchema),
        }
    } catch {
        return { description: `custom tool ${id}`, parameters: { type: 'object' } as unknown as TSchema }
    }
}
