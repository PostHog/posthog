/**
 * One model-emitted tool call → one dispatch → one toolResult message
 * appended to the session conversation. Pulled out of the turn loop so
 * run-turn.ts can stay focused on the loop's control flow.
 *
 * Side effects (intentional):
 *   - Emits `tool_call` + `tool_result` lifecycle events through the caller's
 *     `emit()`.
 *   - Pushes a `toolResult` message onto session.conversation.
 *   - Debug-logs begin/done with timing through the caller's `runLog`.
 *
 * Return value carries the control-flow signal — caller decides whether to
 * keep looping, suspend, or end. Naming the field `signal` (not `outcome`)
 * to avoid confusion with `dispatchTool`'s `Outcome`.
 */

import type { ToolCall } from '@earendil-works/pi-ai'

import {
    AgentRevision,
    AgentSession,
    BundleStore,
    IntegrationCredentials,
    Logger,
    Sandbox,
    SessionEventKind,
    ToolResultMessage,
} from '@posthog/agent-shared-v2'

import { dispatchTool } from './tool-dispatch'

export interface DispatchOneDeps {
    rev: AgentRevision
    session: AgentSession
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    secrets: Record<string, string>
    bundle: BundleStore
    /** Logger scoped to the session (created by run-turn). */
    runLog: Logger
    /** Same log shim the tool-side `ctx.log` writes through. */
    log: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
    /** Lifecycle event publisher — bus + log-sink mirror. */
    emit: (kind: SessionEventKind, data?: Record<string, unknown>) => Promise<void>
    /** Provider-safe → internal-id reverse map for THIS turn. */
    toolNameMap: Map<string, string>
    turn: number
}

export type DispatchSignal =
    | { kind: 'continue' }
    | { kind: 'suspend'; prompt: string }
    | { kind: 'end'; summary?: string }

export async function dispatchOne(call: ToolCall, deps: DispatchOneDeps): Promise<DispatchSignal> {
    // Translate the provider-safe name (what the model emits) back to the
    // internal id (what dispatchTool + our event consumers expect). Unknown
    // names pass through unchanged — dispatchTool will reject them.
    const originalName = deps.toolNameMap.get(call.name) ?? call.name
    deps.runLog.debug(
        { turn: deps.turn, tool: originalName, safeName: call.name, callId: call.id },
        'tool.dispatch.begin'
    )
    await deps.emit('tool_call', { name: originalName, args: call.arguments, id: call.id })
    const t0 = Date.now()
    const outcome = await dispatchTool(
        {
            teamId: deps.session.team_id,
            sessionId: deps.session.id,
            rev: deps.rev,
            sandbox: deps.sandbox,
            integrations: deps.integrations,
            secret: (name) => deps.secrets[name],
            bundle: deps.bundle,
            log: deps.log,
        },
        originalName,
        call.arguments
    )
    deps.runLog.debug(
        {
            turn: deps.turn,
            tool: originalName,
            kind: outcome.kind,
            durationMs: Date.now() - t0,
            error: outcome.kind === 'error' ? outcome.message : undefined,
        },
        'tool.dispatch.done'
    )
    await deps.emit('tool_result', {
        name: originalName,
        id: call.id,
        ok: outcome.kind === 'ok',
        error: outcome.kind === 'error' ? outcome.message : undefined,
    })
    const toolResult: ToolResultMessage = {
        role: 'toolResult',
        toolCallId: call.id,
        toolName: originalName,
        content: [{ type: 'text', text: toolResultText(outcome) }],
        isError: outcome.kind === 'error',
        timestamp: Date.now(),
    }
    deps.session.conversation.push(toolResult)
    if (outcome.kind === 'suspend') {
        return { kind: 'suspend', prompt: outcome.prompt }
    }
    if (outcome.kind === 'end') {
        return { kind: 'end', summary: outcome.summary }
    }
    return { kind: 'continue' }
}

function toolResultText(outcome: Awaited<ReturnType<typeof dispatchTool>>): string {
    switch (outcome.kind) {
        case 'ok':
            return JSON.stringify(outcome.result)
        case 'error':
            return outcome.message
        case 'suspend':
            return JSON.stringify({ suspended: true })
        case 'end':
            return JSON.stringify({ ended: true })
    }
}
