/**
 * Dispatches one tool call against either:
 *   - the native registry (in-process function), or
 *   - the session's sandbox (custom tool, dispatched via Sandbox.invoke).
 *
 * Meta tools (meta.ask_for_input.v1, meta.end_session.v1) are recognized here
 * and surface as control-flow signals — the runner branches on the returned
 * Outcome.kind to suspend or terminate the session.
 */

import { Value } from 'typebox/value'

import { AgentRevision, IntegrationCredentials, Sandbox, ToolRef } from '@posthog/agent-shared-v2'
import { getNativeTool, hasNativeTool } from '@posthog/agent-tools'

export type ToolDispatchOutcome =
    | { kind: 'ok'; result: unknown }
    | { kind: 'error'; message: string }
    | { kind: 'suspend'; prompt: string }
    | { kind: 'end'; summary?: string }

export interface DispatchInput {
    teamId: number
    sessionId: string
    rev: AgentRevision
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    /** Resolved secret-value lookup for native tools (custom tools receive nonces). */
    secret: (name: string) => string | undefined
    log: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
}

export async function dispatchTool(
    input: DispatchInput,
    toolName: string,
    args: unknown
): Promise<ToolDispatchOutcome> {
    if (toolName === 'meta.ask_for_input.v1') {
        const a = args as { prompt?: string }
        return { kind: 'suspend', prompt: a.prompt ?? '' }
    }
    if (toolName === 'meta.end_session.v1') {
        const a = args as { summary?: string }
        return { kind: 'end', summary: a.summary }
    }

    const ref = input.rev.spec.tools.find((t: ToolRef) => t.id === toolName)
    if (!ref) {
        return { kind: 'error', message: `tool not in revision: ${toolName}` }
    }
    if (ref.kind === 'native' && !hasNativeTool(toolName)) {
        return { kind: 'error', message: `native tool unknown: ${toolName}` }
    }

    if (ref.kind === 'custom') {
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
            sessionId: input.sessionId,
            integrations: input.integrations,
            secret: input.secret,
            log: input.log,
        })
        return { kind: 'ok', result }
    } catch (err) {
        return { kind: 'error', message: (err as Error).message }
    }
}
