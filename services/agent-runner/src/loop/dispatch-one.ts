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
import { randomUUID } from 'node:crypto'

import {
    AgentRevision,
    AgentSession,
    AnalyticsSink,
    ApprovalRequest,
    ApprovalStore,
    AssistantMessageRecord,
    BundleStore,
    hashCanonicalArgs,
    IntegrationCredentials,
    Logger,
    NoopAnalyticsSink,
    Sandbox,
    SessionEventKind,
    ToolResultMessage,
    toolSpanId,
} from '@posthog/agent-shared'

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
    /** LLM analytics sink — one `$ai_span` per tool dispatch. Optional; defaults to noop. */
    analytics?: AnalyticsSink
    /** Span id of the generation that emitted this tool call. Used as `$ai_parent_id` on the span. */
    parentSpanId: string
    /** Composite distinct_id resolved by the caller (`analyticsDistinctId`). */
    distinctId: string
    /** Provider-safe → internal-id reverse map for THIS turn. */
    toolNameMap: Map<string, string>
    turn: number
    /**
     * Approval-gated tools (see docs/agent-platform/plans/approval-gated-tools.md).
     * When omitted, no spec tool can be gated and every call dispatches
     * normally — preserves the pre-approval behaviour for callers that
     * don't yet have a store wired.
     */
    approvals?: ApprovalStore
    /**
     * Builds the human-facing URL the model surfaces in the synthetic
     * queued tool_result. Wired from `WorkerDeps`. Default returns a
     * `urn:posthog:approval:<id>` opaque value so callers can keep
     * working without a real router.
     */
    buildApprovalUrl?: (requestId: string) => string
}

export type DispatchSignal =
    | { kind: 'continue' }
    /**
     * Explicit turn-end. Session lands at `completed` (open). The
     * optional `prompt` is the UI focus hint surfaced by
     * `meta-ask-for-input`; the runner emits the `ask_for_input` bus
     * event when present.
     */
    | { kind: 'end_turn'; prompt?: string }
    /** Hard close. Session lands at `closed` (terminal). */
    | { kind: 'close'; summary?: string }

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

    // Approval gate. If the resolved tool ref declares requires_approval,
    // the model's call is queued instead of dispatched — see
    // docs/agent-platform/plans/approval-gated-tools.md.
    const toolRef = deps.rev.spec.tools.find((t) => t.id === originalName)
    if (toolRef?.requires_approval && deps.approvals) {
        const signal = await queueApproval(call, originalName, toolRef, deps)
        return signal
    }
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
    const analytics: AnalyticsSink = deps.analytics ?? new NoopAnalyticsSink()
    await analytics.write([
        {
            kind: 'span',
            ts: new Date().toISOString(),
            team_id: deps.session.team_id,
            application_id: deps.session.application_id,
            revision_id: deps.rev.id,
            session_id: deps.session.id,
            turn: deps.turn,
            span_id: toolSpanId(deps.session.id, deps.turn, call.id),
            parent_span_id: deps.parentSpanId,
            distinct_id: deps.distinctId,
            tool_name: originalName,
            tool_call_id: call.id,
            // Arguments come from the model. `dispatchTool` substitutes nonces
            // for secret values before calling the tool, so what the model
            // emitted here may still contain nonces — never plaintext secrets.
            input: call.arguments,
            output: outcome.kind === 'ok' ? outcome.result : null,
            latency_ms: Date.now() - t0,
            is_error: outcome.kind === 'error',
            error: outcome.kind === 'error' ? outcome.message : undefined,
        },
    ])
    const toolResult: ToolResultMessage = {
        role: 'toolResult',
        toolCallId: call.id,
        toolName: originalName,
        content: [{ type: 'text', text: toolResultText(outcome) }],
        isError: outcome.kind === 'error',
        timestamp: Date.now(),
    }
    deps.session.conversation.push(toolResult)
    if (outcome.kind === 'end_turn') {
        return { kind: 'end_turn', prompt: outcome.prompt }
    }
    if (outcome.kind === 'close') {
        return { kind: 'close', summary: outcome.summary }
    }
    return { kind: 'continue' }
}

function toolResultText(outcome: Awaited<ReturnType<typeof dispatchTool>>): string {
    switch (outcome.kind) {
        case 'ok':
            return JSON.stringify(outcome.result)
        case 'error':
            return outcome.message
        case 'end_turn':
            return JSON.stringify({ ended_turn: true })
        case 'close':
            return JSON.stringify({ ended: true })
    }
}

const APPROVER_HINT_TEAM_ADMINS = 'an authorized admin on this team'

/**
 * Intercept path for an approval-gated tool. Upserts an
 * `agent_tool_approval_request` row, writes a synthetic queued tool_result
 * to the model, and signals `continue` so the session loop keeps going.
 *
 * Idempotency: if a queued row already exists for the same canonical args
 * the store dedupes and we return the existing row id.
 *
 * Prior-decision context: if the previous row for the same canonical args
 * landed in a terminal state (rejected / expired / dispatched_failed), the
 * synthetic queued result surfaces it via `approval.prior_decision` so the
 * model can communicate context to the user.
 */
async function queueApproval(
    call: ToolCall,
    originalName: string,
    toolRef: NonNullable<AgentRevision['spec']['tools'][number]>,
    deps: DispatchOneDeps
): Promise<DispatchSignal> {
    const approvals = deps.approvals!
    const args = (call.arguments ?? {}) as Record<string, unknown>
    const argsHash = hashCanonicalArgs(args)

    // Look up the prior row for this canonical-args triple BEFORE upserting
    // so we can populate prior_decision without seeing our own fresh row.
    const previous = await approvals.findLatestByArgs(deps.session.id, originalName, argsHash)

    // Snapshot the assistant message that emitted this tool call so the
    // approval UI can show the model's reasoning even if conversation
    // compaction trims the original later.
    const lastAssistant = findLastAssistant(deps.session.conversation)

    const ttlMs = toolRef.approval_policy.ttl_ms
    const upsert = await approvals.upsertQueued({
        id: randomUUID(),
        session_id: deps.session.id,
        application_id: deps.session.application_id,
        team_id: deps.session.team_id,
        revision_id: deps.rev.id,
        turn: deps.turn,
        tool_call_id: call.id,
        tool_name: originalName,
        proposed_args: args,
        assistant_message: lastAssistant ?? {
            role: 'assistant',
            content: [{ type: 'text', text: '' }],
            timestamp: Date.now(),
        },
        approver_scope: {
            approvers: toolRef.approval_policy.approvers,
            allow_edit: toolRef.approval_policy.allow_edit,
            allow_agent_approver: toolRef.approval_policy.allow_agent_approver,
        },
        expires_at: new Date(Date.now() + ttlMs).toISOString(),
    })

    const buildUrl = deps.buildApprovalUrl ?? defaultApprovalUrl
    const approval: Record<string, unknown> = {
        request_id: upsert.request.id,
        state: 'queued',
        approver_hint: APPROVER_HINT_TEAM_ADMINS,
        approval_url: buildUrl(upsert.request.id),
    }
    if (!upsert.deduped && previous && isTerminal(previous.state)) {
        approval.prior_decision = {
            state: previous.state,
            reason: previous.decision_reason ?? undefined,
        }
    }

    const toolResult: ToolResultMessage = {
        role: 'toolResult',
        toolCallId: call.id,
        toolName: originalName,
        content: [{ type: 'text', text: JSON.stringify({ approval }) }],
        isError: false,
        timestamp: Date.now(),
    }
    deps.session.conversation.push(toolResult)
    await deps.emit('tool_result', {
        name: originalName,
        id: call.id,
        ok: true,
        approval: { request_id: upsert.request.id, state: 'queued' },
    })
    deps.runLog.debug(
        {
            turn: deps.turn,
            tool: originalName,
            callId: call.id,
            requestId: upsert.request.id,
            deduped: upsert.deduped,
        },
        'tool.dispatch.approval_queued'
    )
    return { kind: 'continue' }
}

function isTerminal(state: ApprovalRequest['state']): boolean {
    return state === 'rejected' || state === 'expired' || state === 'dispatched_failed' || state === 'dispatched'
}

function findLastAssistant(conv: AgentSession['conversation']): AssistantMessageRecord | null {
    for (let i = conv.length - 1; i >= 0; i--) {
        const m = conv[i]
        if (m.role === 'assistant') {
            return m
        }
    }
    return null
}

function defaultApprovalUrl(requestId: string): string {
    return `urn:posthog:approval:${requestId}`
}

/**
 * Dispatch a previously-approved tool call, wrapping the real tool result
 * with the approval envelope. Used by the run-turn approval-marker
 * processor when a wake message lands in `pending_inputs`.
 *
 * Distinct from `dispatchOne` because the approval gate is intentionally
 * bypassed (the human already approved); the synthetic tool_result also
 * differs in shape (carries `approval.state: 'approved'` + the real
 * result).
 */
export async function dispatchApproved(
    request: ApprovalRequest,
    deps: Omit<DispatchOneDeps, 'approvals' | 'buildApprovalUrl'> & { approvals: ApprovalStore }
): Promise<{ outcome: 'dispatched' | 'dispatched_failed'; result?: unknown; error?: string }> {
    const args = request.decided_args ?? request.proposed_args
    const synthCall: ToolCall = {
        type: 'toolCall',
        id: request.tool_call_id,
        name: request.tool_name,
        arguments: args,
    }
    await deps.emit('tool_call', { name: request.tool_name, args, id: request.tool_call_id, approved: true })
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
        request.tool_name,
        synthCall.arguments
    )
    const isError = outcome.kind === 'error'
    const realResult = outcome.kind === 'ok' ? outcome.result : undefined
    const dispatchOutcome: { result?: unknown; error?: string } = isError
        ? { error: (outcome as { message: string }).message }
        : { result: realResult }
    await deps.approvals.markDispatched(request.id, dispatchOutcome)
    const envelope: Record<string, unknown> = {
        approval: {
            request_id: request.id,
            state: 'approved',
            decided_by: request.decision_by ?? undefined,
            edited_args: request.decided_args !== null,
        },
    }
    if (isError) {
        envelope.error = (outcome as { message: string }).message
    } else {
        envelope.result = realResult
    }
    // Wake messages have to be `user`-role, not `tool_result`. Anthropic
    // (and other strict providers) require every tool_result to immediately
    // follow the matching tool_use in the prior assistant message —
    // by the time the approval lands the session has already produced
    // intervening assistant text reacting to the synthetic queued result,
    // so a second tool_result for the same tool_call_id is rejected.
    // Use a user message carrying the same JSON envelope; the model reads
    // it as new context. (The QUEUED synthetic tool_result in queueApproval
    // above is fine — it lands immediately after the tool_call.)
    const wakeMessage = {
        role: 'user' as const,
        content: [{ type: 'text' as const, text: JSON.stringify(envelope) }],
        timestamp: Date.now(),
    }
    deps.session.conversation.push(wakeMessage)
    await deps.emit('tool_result', {
        name: request.tool_name,
        id: request.tool_call_id,
        ok: !isError,
        approval: { request_id: request.id, state: 'approved' },
    })
    const analytics: AnalyticsSink = deps.analytics ?? new NoopAnalyticsSink()
    await analytics.write([
        {
            kind: 'span',
            ts: new Date().toISOString(),
            team_id: deps.session.team_id,
            application_id: deps.session.application_id,
            revision_id: deps.rev.id,
            session_id: deps.session.id,
            turn: deps.turn,
            span_id: toolSpanId(deps.session.id, deps.turn, request.tool_call_id),
            parent_span_id: deps.parentSpanId,
            distinct_id: deps.distinctId,
            tool_name: request.tool_name,
            tool_call_id: request.tool_call_id,
            input: args,
            output: realResult ?? null,
            latency_ms: Date.now() - t0,
            is_error: isError,
            error: isError ? (outcome as { message: string }).message : undefined,
        },
    ])
    return { outcome: isError ? 'dispatched_failed' : 'dispatched', result: realResult, error: dispatchOutcome.error }
}
