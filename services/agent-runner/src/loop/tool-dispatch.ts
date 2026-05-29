/**
 * Dispatches one tool call against either:
 *   - the native registry (in-process function), or
 *   - the session's sandbox (custom tool, dispatched via Sandbox.invoke).
 *
 * Meta tools (@posthog/meta-end-turn, @posthog/meta-ask-for-input,
 * @posthog/meta-end-session) are recognized here and surface as control-flow
 * signals. The runner branches on the returned Outcome.kind to end the turn
 * (completed / open) vs hard-close the session.
 */

import { Value } from 'typebox/value'

import {
    AgentRevision,
    BundleStore,
    IntegrationCredentials,
    MemoryStore,
    Sandbox,
    ToolRef,
} from '@posthog/agent-shared'
import { getNativeTool, hasNativeTool } from '@posthog/agent-tools'

/**
 * Native tools the runner auto-includes for every agent (or conditionally,
 * like `@posthog/load-skill` when skills are present). They aren't listed in
 * `spec.tools`, so dispatchTool needs to recognize them outside the spec
 * lookup. Keep this in sync with `ALWAYS_ON_NATIVE_TOOL_IDS` in run-turn.ts.
 */
const AUTO_INCLUDED_NATIVES = new Set([
    '@posthog/meta-end-turn',
    '@posthog/meta-ask-for-input',
    '@posthog/meta-end-session',
    '@posthog/load-skill',
])

export type ToolDispatchOutcome =
    | { kind: 'ok'; result: unknown }
    | { kind: 'error'; message: string }
    /**
     * Explicit "I'm done with my turn." Session lands at `completed` (open).
     * Fired by `meta-end-turn` and `meta-ask-for-input`. The optional
     * `prompt` is the focus hint that `meta-ask-for-input` surfaces to
     * the UI via the `ask_for_input` bus event.
     */
    | { kind: 'end_turn'; prompt?: string }
    /**
     * Hard close. Session lands at `closed` (terminal unless the trigger
     * sets `allow_restart`). Fired by `meta-end-session`.
     */
    | { kind: 'close'; summary?: string }

export interface DispatchInput {
    teamId: number
    sessionId: string
    rev: AgentRevision
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    /** Resolved secret-value lookup for native tools (custom tools receive nonces). */
    secret: (name: string) => string | undefined
    log: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
    /** Bundle store + revision id are exposed to native tools as a `readBundleFile` closure on ToolContext. */
    bundle?: BundleStore
    /** S3-backed memory store, scoped per-call by the dispatcher. Memory tools no-op without it. */
    memoryStore?: MemoryStore
}

export async function dispatchTool(
    input: DispatchInput,
    toolName: string,
    args: unknown
): Promise<ToolDispatchOutcome> {
    if (toolName === '@posthog/meta-end-turn') {
        return { kind: 'end_turn' }
    }
    if (toolName === '@posthog/meta-ask-for-input') {
        const a = args as { prompt?: string }
        return { kind: 'end_turn', prompt: a.prompt ?? '' }
    }
    if (toolName === '@posthog/meta-end-session') {
        const a = args as { summary?: string }
        return { kind: 'close', summary: a.summary }
    }

    // Native tools the runner auto-includes (not declared in spec.tools).
    // We skip the spec.tools lookup for these and dispatch straight to native.
    const isAutoIncluded = AUTO_INCLUDED_NATIVES.has(toolName)
    const ref = isAutoIncluded ? null : input.rev.spec.tools.find((t: ToolRef) => t.id === toolName)
    if (!isAutoIncluded && !ref) {
        return { kind: 'error', message: `tool not in revision: ${toolName}` }
    }
    if (!isAutoIncluded && ref!.kind === 'native' && !hasNativeTool(toolName)) {
        return { kind: 'error', message: `native tool unknown: ${toolName}` }
    }

    if (ref && ref.kind === 'custom') {
        if (!input.sandbox) {
            return { kind: 'error', message: `custom tool ${toolName} requires a sandbox` }
        }
        const r = await input.sandbox.invoke({ toolId: toolName, action: 'default', args })
        if (!r.ok) {
            return { kind: 'error', message: `${r.error.code}: ${r.error.message}` }
        }
        return { kind: 'ok', result: r.result }
    }

    // native — validate via TypeBox, run in-process.
    const native = getNativeTool(toolName)
    if (!Value.Check(native.schema.args, args)) {
        const first = [...Value.Errors(native.schema.args, args)][0]
        return { kind: 'error', message: first?.message ?? 'invalid args' }
    }
    try {
        const result = await native.run(args, {
            teamId: input.teamId,
            applicationId: input.rev.application_id,
            sessionId: input.sessionId,
            integrations: input.integrations,
            secret: input.secret,
            log: input.log,
            skillIndex: input.rev.spec.skills.map((s) => ({ id: s.id, description: s.description, path: s.path })),
            readBundleFile: input.bundle
                ? async (path: string): Promise<string | null> => {
                      try {
                          return await input.bundle!.readText(input.rev.id, path)
                      } catch {
                          return null
                      }
                  }
                : undefined,
            memoryStore: input.memoryStore,
        })
        return { kind: 'ok', result }
    } catch (err) {
        return { kind: 'error', message: (err as Error).message }
    }
}
