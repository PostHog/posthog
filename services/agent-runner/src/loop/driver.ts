/**
 * Session driver — runs one claimed session to a turn-boundary stopping point
 * by handing control to pi-agent-core's `runAgentLoop` and translating its
 * `AgentEvent` stream back into PostHog's bus / log / analytics sinks and the
 * persisted conversation.
 *
 * Replaces the hand-rolled turn loop (`run-turn.ts`) + tool dispatcher
 * (`dispatch-one.ts` / `tool-dispatch.ts`) + stream normalizer
 * (`pi-client.ts`). The loop now owns: streaming, tool-arg validation, tool
 * dispatch (via each `AgentTool.execute`), and the turn/tool event stream.
 * This file owns everything PostHog-specific around it:
 *
 *   - hooks: `getSteeringMessages` drains `pending_inputs`; `shouldStopAfterTurn`
 *     enforces shutdown + `spec.limits.max_turns`; `getApiKey` / `apiKey` and
 *     `reasoning` plumb the model knobs.
 *   - the event sink: appends every finalized message to `session.conversation`
 *     (in order — the loop emits the assistant `message_end` before its tool
 *     results), mirrors lifecycle events to the SSE bus + log sink, emits one
 *     `$ai_generation` per turn and one `$ai_span` per tool call, accumulates
 *     `usage_total`, and persists after each turn.
 *   - outcome derivation: meta control-flow (`terminate` + `details.control`),
 *     shutdown, the turn cap, and `stopReason` collapse into a `RunOutcome` the
 *     worker maps to a session state.
 *
 * Suspension: the worker's shutdown `AbortSignal` is wired into both the loop's
 * `signal` (cancels the in-flight provider call) and `shouldStopAfterTurn` (a
 * clean turn-boundary stop). Either way the turn either completes or is
 * discarded and re-run on resume — the same turn-boundary checkpointing the
 * old loop had.
 *
 * Approval-gated tools queue via their wrapped `AgentTool.execute` (see the
 * gate override below) and resume when a decided marker lands in
 * `pending_inputs` — handled in `getSteeringMessages`. See
 * docs/agent-platform/plans/approval-gated-tools.md.
 */

import type { AgentContext, AgentEvent, AgentEventSink, AgentMessage, StreamFn } from '@earendil-works/pi-agent-core'
import { runAgentLoop } from '@earendil-works/pi-agent-core'
import type { AssistantMessage, Message, Model } from '@earendil-works/pi-ai'
import { streamSimple } from '@earendil-works/pi-ai'

import {
    accumulateUsage,
    AgentRevision,
    AgentSession,
    AnalyticsSink,
    analyticsDistinctId,
    ApprovalStore,
    AssistantMessageRecord,
    BundleStore,
    buildSystemPrompt,
    ConversationMessage,
    createLogger,
    FRAMEWORK_PROMPT_VERSION,
    GatewayClient,
    generationSpanId,
    IntegrationCredentials,
    isDeltaEventKind,
    LogLevel,
    LogSink,
    MemoryStore,
    NoopAnalyticsSink,
    NoopLogSink,
    NoopSessionEventBus,
    Sandbox,
    SecretBroker,
    SessionEvent,
    SessionEventBus,
    SessionEventKind,
    toolSpanId,
} from '@posthog/agent-shared'

import { approvalMarkerRequestId, ApprovalPolicy, dispatchApprovedResult, queueApprovalResult } from './approval'
import { AgentToolDeps, buildAgentTools, MetaControl, RealToolExecute, ToolResultDetails } from './build-agent-tools'
import type { IsAskerInApproverScope } from './per-asker-auth'
import { providerSafeName } from './provider-safe-names'

export interface RunSessionDeps {
    /** The pi-ai Model to invoke for this session (resolved from rev.spec.model). */
    model: Model<string>
    /** Per-call API key (provider-specific). */
    apiKey?: string
    /**
     * Stream function for the loop. Defaults to pi-ai's `streamSimple` (which
     * routes through the registered provider — real providers in prod, the faux
     * provider in the e2e harness). Injectable for unit tests.
     */
    streamFn?: StreamFn
    bundle: BundleStore
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    secrets: Record<string, string>
    broker?: SecretBroker
    /** Aborting this signal mid-turn cancels the LLM call and stops the loop. */
    shutdownSignal?: AbortSignal
    /** Called once per turn after the assistant message + tool results are appended. */
    onTurnPersist?: (session: AgentSession) => Promise<void>
    bus?: SessionEventBus
    logs?: LogSink
    analytics?: AnalyticsSink
    /** Suppress pi-ai's client-side cost numbers (gateway tracks cost server-side). */
    useGatewayCost?: boolean
    /** Approval-gated tool store. When set, gated tools queue instead of
     * executing and resume via the decided-marker path in getSteeringMessages.
     * When absent, gated tools run normally (pre-approval default). */
    approvals?: ApprovalStore
    buildApprovalUrl?: (requestId: string) => string
    /**
     * Per-asker authorisation shortcut for approval-gated tools (#23 step 3).
     *
     * **NOT YET CONSUMED** by the pi-agent-core driver. Accepted on the deps
     * for API-shape stability with `WorkerDeps` (the harness + index.ts wire
     * a real impl). Needs to be plumbed into the gated tool's `execute`
     * swap below so the queue is skipped when the asker already satisfies
     * the approver scope.
     */
    isAskerInApproverScope?: IsAskerInApproverScope
    /**
     * S3-backed memory store. Threaded into `AgentToolDeps` → `ToolContext`
     * so native `@posthog/memory-*` tools work; absent → memory tools return
     * `memory_store_unavailable` to the model. Wired in prod from
     * `AGENT_MEMORY_S3_*` config.
     */
    memoryStore?: MemoryStore
    /**
     * Per-session static HTTP headers stamped on every outbound model call.
     * On the llm-gateway path this carries `X-PostHog-Distinct-Id` +
     * `X-PostHog-Trace-Id` so gateway-emitted `$ai_generation` events
     * attribute correctly.
     *
     * **NOT YET CONSUMED** by the pi-agent-core driver — the old loop pushed
     * these into `PiAiClient.invoke({ headers })`. To restore, the `streamFn`
     * wrapper needs to inject these into the per-call options. Accepted on
     * the deps for API-shape stability with the worker; until ported, the
     * presence of this field is the signal `errorContext()` uses to mark
     * failures as `source: llm_gateway`.
     */
    gatewayHeaders?: Record<string, string>
    /**
     * Gateway read client + the team's `phc_` bearer. When set, after every
     * pi-ai turn the runner is expected to fetch
     * `GET /v1/usage/<request_id>` and merge gateway-computed cost into
     * `usage_total.cost_total`.
     *
     * **NOT YET CONSUMED** by the pi-agent-core driver — the old loop did
     * this in run-turn.ts's per-turn block. Needs porting into the
     * `turn_end` branch of the sink (the per-turn `request_id` would need
     * to be stamped by the same streamFn wrapper that injects
     * gatewayHeaders). Accepted on the deps for API-shape stability;
     * gateway-path cost stays zero on the session row until ported.
     */
    gatewayUsage?: {
        client: GatewayClient
        phc: string
    }
}

export type RunOutcome =
    | { state: 'completed'; turns: number }
    | { state: 'closed'; summary?: string; turns: number }
    | { state: 'suspended'; reason: 'shutdown'; turns: number }
    | { state: 'failed'; reason: string; turns: number }

export async function runSession(rev: AgentRevision, session: AgentSession, deps: RunSessionDeps): Promise<RunOutcome> {
    const system = await buildSystemPrompt(rev, deps.bundle)
    const bus: SessionEventBus = deps.bus ?? new NoopSessionEventBus()
    const logs: LogSink = deps.logs ?? new NoopLogSink()
    const analytics: AnalyticsSink = deps.analytics ?? new NoopAnalyticsSink()
    const distinctId = analyticsDistinctId(session)

    const runLog = createLogger('runner', {
        session_id: session.id,
        application_id: session.application_id,
        team_id: session.team_id,
    })
    const log = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void => {
        runLog[level](meta ?? {}, msg)
    }

    const emit = async (kind: SessionEventKind, data: Record<string, unknown> = {}): Promise<void> => {
        const ts = new Date().toISOString()
        await bus.publish({ session_id: session.id, kind, data, ts } satisfies SessionEvent)
        // Drop high-cardinality delta events from the persistent log sink; the
        // turn-end full-text events still land.
        if (isDeltaEventKind(kind)) {
            return
        }
        const level: LogLevel = kind === 'failed' ? 'error' : 'info'
        await logs.write([
            {
                ts,
                team_id: session.team_id,
                application_id: session.application_id,
                session_id: session.id,
                level,
                event: kind,
                data,
            },
        ])
    }

    const toolDeps: AgentToolDeps = {
        rev,
        session,
        sandbox: deps.sandbox,
        integrations: deps.integrations,
        secrets: deps.secrets,
        bundle: deps.bundle,
        log,
        memoryStore: deps.memoryStore,
    }
    const { tools, nameToId } = await buildAgentTools(rev, toolDeps)

    await emit('session_started', {
        team_id: session.team_id,
        agent: rev.application_id,
        rev: rev.id,
        framework_prompt_version: FRAMEWORK_PROMPT_VERSION,
    })

    // Clean suspension point before any work — matches the old top-of-loop check.
    if (deps.shutdownSignal?.aborted) {
        return { state: 'suspended', reason: 'shutdown', turns: 0 }
    }

    // Per-run state the sink accumulates; outcome derivation reads it after the loop.
    let turn = 0
    let inputSnapshot: ConversationMessage[] = []
    let turnStart = 0
    let genSpan = ''
    let stoppedByCap = false
    let lastStopReason: AssistantMessage['stopReason'] | undefined
    let lastError: string | undefined
    let lastControl: MetaControl | undefined
    let controlThisTurn: MetaControl | undefined
    let lastTurnContinued = false
    const toolStarts = new Map<string, { args: Record<string, unknown>; t0: number }>()

    // Keep each tool's real execute, then swap gated tools for the queue path.
    // The real execute is what an approved call runs on resume (the human has
    // already cleared the gate). Gating is active only when an approvals store
    // is wired; otherwise gated tools run normally (the pre-approval default).
    const realExecute = new Map<string, RealToolExecute>()
    for (const tool of tools) {
        // Tools are named with their original id.
        realExecute.set(tool.name, tool.execute as RealToolExecute)
    }
    if (deps.approvals) {
        const approvals = deps.approvals
        for (const tool of tools) {
            const id = tool.name
            const ref = rev.spec.tools.find((t) => t.id === id)
            if (ref?.requires_approval) {
                const policy = ref.approval_policy as ApprovalPolicy
                tool.execute = (toolCallId, args) =>
                    queueApprovalResult({
                        approvals,
                        buildApprovalUrl: deps.buildApprovalUrl,
                        session,
                        revisionId: rev.id,
                        // `turn` is the live counter — at call time it's the
                        // turn that proposed this gated call.
                        turn,
                        toolName: id,
                        toolCallId,
                        args: (args ?? {}) as Record<string, unknown>,
                        policy,
                    })
            }
        }
    }

    const sink: AgentEventSink = async (event: AgentEvent): Promise<void> => {
        switch (event.type) {
            case 'turn_start': {
                turn++
                controlThisTurn = undefined
                await emit('turn_started', { turn })
                return
            }
            case 'message_start': {
                // Snapshot the model input + start the generation span when the
                // assistant turn begins (steering messages for this turn are
                // already appended via their own message_end).
                if (event.message.role === 'assistant') {
                    inputSnapshot = [...session.conversation]
                    turnStart = Date.now()
                    genSpan = generationSpanId(session.id, turn)
                }
                return
            }
            case 'message_update': {
                const e = event.assistantMessageEvent
                if (e.type === 'text_delta') {
                    await emit('assistant_text_delta', { turn, text: e.delta })
                } else if (e.type === 'thinking_delta') {
                    await emit('assistant_thinking_delta', { turn, thinking: e.delta })
                }
                return
            }
            case 'message_end': {
                // Every finalized message (steering/user, assistant, tool result)
                // lands in the persisted transcript in emission order.
                session.conversation.push(event.message as ConversationMessage)
                return
            }
            case 'tool_execution_start': {
                toolStarts.set(event.toolCallId, {
                    args: (event.args ?? {}) as Record<string, unknown>,
                    t0: Date.now(),
                })
                await emit('tool_call', { name: event.toolName, args: event.args, id: event.toolCallId })
                return
            }
            case 'tool_execution_end': {
                const original = event.toolName
                const started = toolStarts.get(event.toolCallId)
                const details = event.result?.details as ToolResultDetails | undefined
                if (details?.control) {
                    lastControl = details.control
                    controlThisTurn = details.control
                }
                const errorText = event.isError ? resultText(event.result) : undefined
                await emit('tool_result', {
                    name: original,
                    id: event.toolCallId,
                    ok: !event.isError,
                    error: errorText,
                    ...(details?.queued ? { approval: { request_id: details.requestId, state: 'queued' } } : {}),
                })
                // A queued gated call didn't really execute — no span for it
                // (the approved dispatch emits its own span on resume).
                if (!details?.queued) {
                    await analytics.write([
                        {
                            kind: 'span',
                            ts: new Date().toISOString(),
                            team_id: session.team_id,
                            application_id: session.application_id,
                            revision_id: rev.id,
                            session_id: session.id,
                            turn,
                            span_id: toolSpanId(session.id, turn, event.toolCallId),
                            parent_span_id: genSpan,
                            distinct_id: distinctId,
                            tool_name: original,
                            tool_call_id: event.toolCallId,
                            input: started?.args ?? {},
                            output: event.isError ? null : (details?.output ?? null),
                            latency_ms: started ? Date.now() - started.t0 : 0,
                            is_error: event.isError,
                            error: errorText,
                        },
                    ])
                }
                return
            }
            case 'turn_end': {
                const msg = event.message as AssistantMessage
                lastStopReason = msg.stopReason
                lastError = msg.errorMessage
                const hasToolCalls = msg.content.some((b) => b.type === 'toolCall')
                lastTurnContinued = hasToolCalls && !controlThisTurn

                const record: AssistantMessageRecord = {
                    role: 'assistant',
                    content: msg.content,
                    api: msg.api,
                    provider: msg.provider,
                    model: msg.model,
                    usage: msg.usage,
                    stopReason: msg.stopReason,
                    errorMessage: msg.errorMessage,
                    timestamp: msg.timestamp,
                }
                session.usage_total = accumulateUsage(session.usage_total, record, {
                    useGatewayCost: deps.useGatewayCost,
                })

                for (const b of msg.content) {
                    if (b.type === 'text' && b.text) {
                        await emit('assistant_text', { text: b.text })
                    }
                }

                await analytics.write([
                    {
                        kind: 'generation',
                        ts: new Date(msg.timestamp).toISOString(),
                        team_id: session.team_id,
                        application_id: session.application_id,
                        revision_id: rev.id,
                        session_id: session.id,
                        turn,
                        span_id: genSpan,
                        distinct_id: distinctId,
                        model: msg.model ?? deps.model.id,
                        provider: msg.provider ?? deps.model.provider,
                        input: inputSnapshot,
                        output: msg.content,
                        input_tokens: msg.usage?.input ?? 0,
                        output_tokens: msg.usage?.output ?? 0,
                        cache_read_tokens: msg.usage?.cacheRead,
                        cache_write_tokens: msg.usage?.cacheWrite,
                        total_tokens: msg.usage?.totalTokens,
                        latency_ms: Date.now() - turnStart,
                        cost_usd: deps.useGatewayCost ? undefined : msg.usage?.cost?.total,
                        stop_reason: msg.stopReason,
                        is_error: msg.stopReason === 'error',
                        error: msg.stopReason === 'error' ? msg.errorMessage : undefined,
                    },
                ])
                await deps.onTurnPersist?.(session)
                return
            }
            default:
                return
        }
    }

    const context: AgentContext = {
        systemPrompt: system,
        messages: [...session.conversation] as unknown as AgentMessage[],
        tools,
    }

    // Tools are registered under their original ids so the loop matches calls
    // by name. Sanitize names on the wire (strict providers reject `@`/`/`) and
    // translate provider-echoed names back to the original before the loop sees
    // the assistant message. The faux provider echoes the script's (original)
    // name verbatim — the reverse map misses and leaves it unchanged.
    const streamFn = sanitizingStreamFn(deps.streamFn ?? streamSimple, nameToId)

    try {
        await runAgentLoop(
            [],
            context,
            {
                model: deps.model,
                apiKey: deps.apiKey,
                maxTokens: 4096,
                // pi-ai ignores `reasoning` for non-reasoning models, so forward unconditionally.
                reasoning: rev.spec.reasoning,
                convertToLlm: (messages) => messages as unknown as Message[],
                // The loop contract requires this hook to never throw. We also
                // must NOT clear pending_inputs up front: an approval marker
                // whose dispatch fails transiently has to survive for the next
                // resume, or the user's approval is silently lost and the row
                // stays stuck in `approving`. So we consume entries only as we
                // successfully process them; anything that throws is kept.
                getSteeringMessages: async (): Promise<AgentMessage[]> => {
                    if (session.pending_inputs.length === 0) {
                        return []
                    }
                    const pending = session.pending_inputs
                    const out: ConversationMessage[] = []
                    const kept: ConversationMessage[] = []
                    for (const msg of pending) {
                        const requestId = deps.approvals ? approvalMarkerRequestId(msg) : null
                        if (!requestId || !deps.approvals) {
                            // Plain steering input (e.g. /send) — consume it.
                            out.push(msg)
                            continue
                        }
                        try {
                            const row = await deps.approvals.get(requestId)
                            // Drop markers that aren't a live, in-flight approval
                            // for THIS session. The session_id check is a security
                            // boundary: /send appends caller-controlled strings to
                            // pending_inputs and the request id is exposed via SSE,
                            // so without it one session could inject another's
                            // approval id and hijack its dispatch.
                            if (!row || row.session_id !== session.id || row.state !== 'approving') {
                                runLog.warn(
                                    {
                                        requestId,
                                        rowState: row?.state ?? 'missing',
                                        sameSession: row?.session_id === session.id,
                                    },
                                    'approval.marker.dropped'
                                )
                                continue
                            }
                            const t0 = Date.now()
                            // dispatchApprovedResult marks the row dispatched as its
                            // commit point. If it throws after the tool ran but
                            // before that mark lands, keeping the marker can
                            // re-execute on resume — a known transient-failure
                            // window; full idempotency would need a transactional
                            // dispatch (tracked follow-up).
                            const d = await dispatchApprovedResult({
                                approvals: deps.approvals,
                                realExecute: realExecute.get(row.tool_name),
                                row,
                            })
                            // Secure the wake before observability so a failing
                            // emit/analytics can't strand an already-dispatched call.
                            out.push(d.wake)
                            try {
                                const span = turn + 1
                                await emit('tool_call', {
                                    name: d.toolName,
                                    args: d.args,
                                    id: d.toolCallId,
                                    approved: true,
                                })
                                await emit('tool_result', {
                                    name: d.toolName,
                                    id: d.toolCallId,
                                    ok: !d.isError,
                                    error: d.error,
                                    approval: { request_id: d.requestId, state: 'approved' },
                                })
                                await analytics.write([
                                    {
                                        kind: 'span',
                                        ts: new Date().toISOString(),
                                        team_id: session.team_id,
                                        application_id: session.application_id,
                                        revision_id: rev.id,
                                        session_id: session.id,
                                        turn: span,
                                        span_id: toolSpanId(session.id, span, d.toolCallId),
                                        parent_span_id: generationSpanId(session.id, span),
                                        distinct_id: distinctId,
                                        tool_name: d.toolName,
                                        tool_call_id: d.toolCallId,
                                        input: d.args,
                                        output: d.isError ? null : (d.output ?? null),
                                        latency_ms: Date.now() - t0,
                                        is_error: d.isError,
                                        error: d.error,
                                    },
                                ])
                            } catch (obsErr) {
                                runLog.warn(
                                    { requestId, err: (obsErr as Error).message },
                                    'approval.observability_failed'
                                )
                            }
                        } catch (err) {
                            // Transient failure (e.g. a DB blip) — keep the marker
                            // so a later resume retries rather than losing the
                            // user's approval.
                            runLog.warn({ requestId, err: (err as Error).message }, 'approval.marker.retry')
                            kept.push(msg)
                        }
                    }
                    session.pending_inputs = kept
                    return out as unknown as AgentMessage[]
                },
                shouldStopAfterTurn: async (): Promise<boolean> => {
                    if (deps.shutdownSignal?.aborted) {
                        return true
                    }
                    if (turn >= rev.spec.limits.max_turns) {
                        stoppedByCap = true
                        return true
                    }
                    return false
                },
            },
            sink,
            deps.shutdownSignal,
            streamFn
        )
    } catch (err) {
        const e = err as Error & { name?: string }
        if (e.name === 'AbortError' || deps.shutdownSignal?.aborted) {
            return { state: 'suspended', reason: 'shutdown', turns: turn }
        }
        runLog.error({ turn, err: e.message, ...errorContext() }, 'loop.failed')
        await emit('failed', { reason: e.message ?? 'loop_error', turns: turn, ...errorContext() })
        return { state: 'failed', reason: e.message ?? 'loop_error', turns: turn }
    }

    // Outcome derivation — order matters (shutdown beats a stale terminal state).
    if (deps.shutdownSignal?.aborted || lastStopReason === 'aborted') {
        return { state: 'suspended', reason: 'shutdown', turns: turn }
    }
    if (lastControl?.kind === 'close') {
        await emit('closed', { turns: turn, summary: lastControl.summary })
        return { state: 'closed', summary: lastControl.summary, turns: turn }
    }
    if (lastStopReason === 'error') {
        runLog.error({ turn, reason: lastError, ...errorContext() }, 'model.error')
        await emit('failed', { reason: lastError ?? 'model_error', turns: turn, ...errorContext() })
        return { state: 'failed', reason: lastError ?? 'model_error', turns: turn }
    }
    if (lastStopReason === 'length') {
        await emit('failed', { reason: 'max_tokens', turns: turn, ...errorContext() })
        return { state: 'failed', reason: 'max_tokens', turns: turn }
    }

    // Stamps the failure source (gateway vs direct provider) + model id on
    // every error log/event so operators can tell at a glance whether a
    // mystery `400 status code (no body)` came from the gateway or the
    // upstream provider. Defined inline so it closes over `deps`.
    function errorContext(): Record<string, unknown> {
        return {
            source: deps.gatewayHeaders ? 'llm_gateway' : 'provider',
            model: deps.model.id,
            provider: deps.model.provider,
            api: deps.model.api,
        }
    }
    if (stoppedByCap && lastTurnContinued) {
        await emit('failed', { reason: 'max_turns_exceeded', turns: turn })
        return { state: 'failed', reason: 'max_turns_exceeded', turns: turn }
    }
    if (lastControl?.kind === 'end_turn' && lastControl.prompt) {
        await emit('ask_for_input', { turns: turn, prompt: lastControl.prompt })
    }
    await emit('completed', { turns: turn })
    return { state: 'completed', turns: turn }
}

/** First text block of a tool result, used for the error string in spans/events. */
function resultText(result: { content?: Array<{ type: string; text?: string }> } | undefined): string {
    const block = result?.content?.find((c) => c.type === 'text')
    return block?.text ?? 'error'
}

/**
 * Wrap a StreamFn so provider-bound tool names are sanitized to the
 * `^[a-zA-Z0-9_-]{1,128}$` form strict providers require, and the names a
 * provider echoes back in tool calls are translated to the original ids the
 * loop matches against.
 *
 * Three sites need rewriting on every call:
 *   1. `context.tools[].name` — the declarations the provider validates against.
 *   2. `context.messages[]` — historical assistant `toolCall` names and the
 *      paired `toolResult.toolName` from prior turns. Strict providers
 *      (e.g. OpenAI Responses, `^[a-zA-Z0-9_-]+$`) reject the original
 *      `@posthog/query` shape in this position too, so without rewriting them
 *      turn 2 fails with a 400 even though turn 1 went through fine.
 *   3. The materialized `result()` — tool calls on the assistant reply get
 *      their names translated BACK to the original ids the loop matches
 *      against. The faux provider echoes the script's original name verbatim
 *      so the reverse-map miss just leaves it unchanged.
 */
function sanitizingStreamFn(base: StreamFn, safeToOriginal: Map<string, string>): StreamFn {
    return async (model, context, options) => {
        const tools = context.tools?.map((t) => ({ ...t, name: providerSafeName(t.name) }))
        const messages = context.messages?.map(sanitizeMessageNames)
        const stream = await base(model, { ...context, tools, messages }, options)
        const result = async (): Promise<AssistantMessage> => {
            const msg = await stream.result()
            return {
                ...msg,
                content: msg.content.map((b) =>
                    b.type === 'toolCall' ? { ...b, name: safeToOriginal.get(b.name) ?? b.name } : b
                ),
            }
        }
        return new Proxy(stream, {
            get(target, prop, receiver) {
                if (prop === 'result') {
                    return result
                }
                const value = Reflect.get(target, prop, receiver)
                return typeof value === 'function' ? value.bind(target) : value
            },
        })
    }
}

/**
 * Rewrite tool names embedded in a historical Message so they match the
 * provider-safe form the live request will declare. Untyped to avoid a
 * tight coupling to pi-ai's Message union — we touch only the two fields
 * that carry a tool id, copy everything else through, and leave non-tool
 * messages unchanged.
 */
function sanitizeMessageNames(message: Message): Message {
    const m = message as unknown as { role?: string; toolName?: unknown; content?: unknown }
    if (m.role === 'toolResult' && typeof m.toolName === 'string') {
        return { ...message, toolName: providerSafeName(m.toolName) } as Message
    }
    if (m.role === 'assistant' && Array.isArray(m.content)) {
        return {
            ...message,
            content: (m.content as Array<{ type?: string; name?: string }>).map((b) =>
                b && b.type === 'toolCall' && typeof b.name === 'string' ? { ...b, name: providerSafeName(b.name) } : b
            ),
        } as Message
    }
    return message
}
