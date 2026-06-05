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
import { randomUUID } from 'node:crypto'

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
    CredentialBroker,
    createLogger,
    FRAMEWORK_PROMPT_VERSION,
    GatewayClient,
    generationSpanId,
    HttpFetcher,
    IntegrationCredentials,
    isDeltaEventKind,
    LogLevel,
    LogSink,
    MemoryStore,
    TabularStore,
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
import type { OpenedMcp } from './mcp-clients'
import { lookupMcpToolApproval } from './mcp-tool-lookup'
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
    /**
     * Per-session credential store populated by ingress at /run + /send.
     * Tool dispatch resolves `(session_id, target) → Credential` through
     * here to get the user's auth materials (e.g. PostHog OAuth bearer
     * under target `posthog_api`). Optional — when absent, tools that
     * try to resolve credentials get `null` and degrade.
     */
    credentialBroker?: CredentialBroker
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
     * Called inside the gated tool's `execute` before queueing: when the
     * most recent user-turn's sender themselves satisfies the tool's
     * `approver_scope`, the call is dispatched directly via the original
     * `realExecute` (no queue, no UI round-trip). Errors fall through to
     * the queue path so a transient lookup failure can't strand a gated
     * call. Omit to keep the always-queue default.
     */
    isAskerInApproverScope?: IsAskerInApproverScope
    /**
     * S3-backed memory store. Threaded into `AgentToolDeps` → `ToolContext`
     * so native `@posthog/memory-*` tools work; absent → memory tools return
     * `memory_store_unavailable` to the model. Wired in prod from
     * `AGENT_MEMORY_S3_*` config.
     */
    memoryStore?: MemoryStore
    /** Deterministic tabular store for @posthog/table-* tools. */
    tabularStore?: TabularStore
    /**
     * Per-session static HTTP headers stamped on every outbound model call.
     * On the ai-gateway path this carries `X-PostHog-Distinct-Id` +
     * `X-PostHog-Trace-Id` so gateway-emitted `$ai_generation` events
     * attribute correctly. The `gatewayMetadataStreamFn` wrapper merges
     * these with a per-turn `Idempotency-Key` + `X-Request-Id` of the form
     * `agent:<session>:<turn>` and forwards them to pi-ai's per-call
     * `options.headers`. Presence also signals `errorContext()` to mark
     * failures as `source: ai_gateway`.
     */
    gatewayHeaders?: Record<string, string>
    /**
     * Gateway read client + the team's `phc_` bearer. When set, after every
     * pi-ai turn the runner fetches `GET /v1/usage/<request_id>` (using the
     * id stamped by `gatewayMetadataStreamFn`) and merges the
     * gateway-computed cost into `usage_total.cost_total`. Best-effort: a
     * transient fetch failure or NaN body is logged + skipped so a gateway
     * blip can't strand the turn.
     */
    gatewayUsage?: {
        client: GatewayClient
        phc: string
    }
    /**
     * Opened MCP clients (one per entry in `rev.spec.mcps[]`). Forwarded
     * straight into `AgentToolDeps`; `buildAgentTools` walks them at session
     * start to emit one `AgentTool` per remote tool. Lifetime is owned by
     * the worker (`openMcpClients` before `runSession`, `close` in the
     * worker's `finally`). Absent or empty → no MCP tools surface.
     */
    mcpClients?: OpenedMcp[]
    /**
     * Outbound HTTP client for native tools — threaded through to
     * `AgentToolDeps` and then `ToolContext.http`. Required so tools can
     * assume the seam is present; wired once at the runner entrypoint
     * from `HTTPS_PROXY` env (smokescreen in prod, direct in dev).
     */
    http: HttpFetcher
    /** Base URL for the PostHog API. Forwarded into `ToolContext.posthogApiBaseUrl`. */
    posthogApiBaseUrl: string
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

    // Dispatcher for `kind: "client"` tools. Subscribes once for the session
    // and routes every `client_tool_result` event to whichever pending
    // promise has the matching call_id. The subscription is torn down +
    // pending promises rejected at session-end via the wrapping
    // try/finally below — otherwise the bus would accumulate one
    // subscriber per session handled by this worker.
    const pendingClientCalls = new Map<string, { resolve: (v: unknown) => void; reject: (e: Error) => void }>()
    const clientResultUnsub = bus.subscribe(session.id, (e) => {
        if (e.kind !== 'client_tool_result') {
            return
        }
        const d = e.data as { call_id?: string; result?: unknown; error?: string }
        if (!d.call_id) {
            return
        }
        const pending = pendingClientCalls.get(d.call_id)
        if (!pending) {
            return
        }
        pendingClientCalls.delete(d.call_id)
        // Key presence — not truthiness. An empty-string `error` still
        // means the handler failed; falling through to resolve(undefined)
        // would let pi-ai see malformed tool content and emit a silent
        // `ok: false, error: ""` to the model.
        if ('error' in d) {
            pending.reject(new Error(d.error || 'empty_client_error'))
        } else {
            pending.resolve(d.result)
        }
    })
    const tearDownClientDispatch = (): void => {
        clientResultUnsub()
        for (const p of pendingClientCalls.values()) {
            p.reject(new Error('session_ended'))
        }
        pendingClientCalls.clear()
    }
    const dispatchClientTool = async (
        toolId: string,
        args: Record<string, unknown>,
        timeoutMs: number
    ): Promise<unknown> => {
        const callId = randomUUID()
        const promise = new Promise<unknown>((resolve, reject) => {
            pendingClientCalls.set(callId, { resolve, reject })
            setTimeout(() => {
                if (pendingClientCalls.delete(callId)) {
                    reject(new Error('client_tool_timeout'))
                }
            }, timeoutMs)
        })
        await emit('client_tool_call', { call_id: callId, tool_id: toolId, args })
        return promise
    }

    // Wrap the loop + outcome derivation in try/finally so the bus
    // subscription registered above is always released (and pending
    // client-tool promises rejected) regardless of which return path
    // the function exits through. Intentionally left at +0 indent to
    // keep the diff small; the contents are unchanged.
    try {
        const toolDeps: AgentToolDeps = {
            rev,
            session,
            sandbox: deps.sandbox,
            integrations: deps.integrations,
            secrets: deps.secrets,
            bundle: deps.bundle,
            log,
            memoryStore: deps.memoryStore,
            tabularStore: deps.tabularStore,
            dispatchClientTool,
            credentialBroker: deps.credentialBroker,
            mcpClients: deps.mcpClients,
            http: deps.http,
            posthogApiBaseUrl: deps.posthogApiBaseUrl,
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
                // Native + custom tools carry their approval policy on
                // `spec.tools[]`. MCP tools materialise at session start
                // from `client.listTools()` so they can't appear there;
                // fall through to the lookup that decomposes the
                // `<prefix>__<remoteName>` shape against `spec.mcps[]`.
                // Client tools have no approval field today so they skip
                // either path. (PR 7 — runtime-mcps.md "Resolved design".)
                const ref = rev.spec.tools.find((t) => t.id === id)
                const nativeRef = ref && ref.kind !== 'client' && ref.requires_approval ? ref : null
                // Only fall through to MCP lookup when there's NO `spec.tools`
                // entry at all. A `client` tool whose id collides with an
                // MCP-exposed `<prefix>__<remote>` name is an author bug —
                // refuse to gate it with the MCP's policy rather than
                // surprising the client-tool dispatcher. The dispatch
                // collision-skip in `build-agent-tools.ts` handles the
                // surface side; this just keeps the wrap path consistent.
                const mcpGate = ref ? null : lookupMcpToolApproval(id, rev.spec)
                const policy: ApprovalPolicy | null = nativeRef
                    ? (nativeRef.approval_policy as ApprovalPolicy)
                    : mcpGate?.requires_approval
                      ? mcpGate.approval_policy
                      : null
                if (policy) {
                    const real = realExecute.get(id)
                    tool.execute = async (toolCallId, args) => {
                        // Per-asker shortcut (#23 step 3): when the most recent
                        // user-turn's sender already satisfies the tool's
                        // approver scope, dispatch the real tool directly and
                        // skip the queue. The model sees a normal tool_result
                        // either way. Best-effort — a thrown check falls through
                        // to the queue path so a transient DB blip can't strand
                        // a gated call as never-queued, never-executed.
                        if (real && deps.isAskerInApproverScope) {
                            try {
                                const allowed = await deps.isAskerInApproverScope(
                                    session.conversation,
                                    session.team_id,
                                    policy.approvers,
                                    session.principal
                                )
                                if (allowed) {
                                    log('info', 'tool.dispatch.per_asker_authorised', { tool: id })
                                    return real(toolCallId, (args ?? {}) as Record<string, unknown>)
                                }
                            } catch (err) {
                                log('warn', 'tool.dispatch.per_asker_check_failed', {
                                    tool: id,
                                    err: (err as Error).message,
                                })
                            }
                        }
                        return queueApprovalResult({
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
                        // Surface the structured output so the live SSE
                        // reducer can render the same result the persisted
                        // session conversation shows on reload. Without
                        // this the client sees only `ok`/`error`.
                        output: event.isError ? undefined : (details?.output ?? null),
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

                    // Gateway settled-cost recovery: pi-ai's `usage.cost.*` numbers
                    // are client-side estimates on the gateway path (zeroed by
                    // `accumulateUsage` when `useGatewayCost`), so fetch the real
                    // cost from `GET /v1/usage/<request_id>` and merge it. Best-
                    // effort — a transient fetch failure leaves cost_total
                    // unchanged for that turn (the gateway also emits its own
                    // `$ai_generation` event with the cost, so the loss is
                    // bounded to the session row's running total).
                    if (deps.gatewayUsage) {
                        const requestId = turnRequestIds.get(turn)
                        if (requestId) {
                            try {
                                const usage = await deps.gatewayUsage.client.getUsage(requestId, {
                                    phc: deps.gatewayUsage.phc,
                                })
                                if (usage) {
                                    const cost = Number(usage.cost_usd)
                                    if (Number.isFinite(cost)) {
                                        session.usage_total = {
                                            ...session.usage_total,
                                            cost_total: session.usage_total.cost_total + cost,
                                        }
                                    } else {
                                        runLog.warn(
                                            { turn, cost_usd: usage.cost_usd, requestId },
                                            'gateway.usage.cost_nan'
                                        )
                                    }
                                }
                            } catch (err) {
                                runLog.warn(
                                    { turn, requestId, err: (err as Error).message },
                                    'gateway.usage.fetch_failed'
                                )
                            }
                        }
                        // Always clear the entry so the map can't accumulate across a
                        // long-running session — we don't need it after this turn.
                        turnRequestIds.delete(turn)
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

        // Per-turn gateway metadata: an `agent:<session>:<turn>` request id stamped
        // on every outbound call, exposed back into the sink via this map so
        // `turn_end` can read the settled cost (cleared per turn after the fetch
        // so the map can't grow unbounded). Populated on the gateway path only.
        const turnRequestIds = new Map<number, string>()

        // Tools are registered under their original ids so the loop matches calls
        // by name. Sanitize names on the wire (strict providers reject `@`/`/`) and
        // translate provider-echoed names back to the original before the loop sees
        // the assistant message. The faux provider echoes the script's (original)
        // name verbatim — the reverse map misses and leaves it unchanged.
        //
        // Two wrappers compose: the gateway-metadata wrapper (when active) stamps
        // per-call request ids + headers; the sanitizing wrapper rewrites tool
        // names. Order doesn't change behaviour — both touch separate fields —
        // but gateway is outer so the request id is generated at the top of the
        // chain, before name sanitization mutates the context payload pi-ai sees.
        let baseStreamFn: StreamFn = deps.streamFn ?? streamSimple
        if (deps.gatewayHeaders || deps.gatewayUsage) {
            baseStreamFn = gatewayMetadataStreamFn(baseStreamFn, session.id, deps.gatewayHeaders, turnRequestIds)
        }
        const streamFn = sanitizingStreamFn(baseStreamFn, nameToId)

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
                source: deps.gatewayHeaders ? 'ai_gateway' : 'provider',
                model: deps.model.id,
                provider: deps.model.provider,
                api: deps.model.api,
            }
        }
        if (stoppedByCap && lastTurnContinued) {
            await emit('failed', { reason: 'max_turns_exceeded', turns: turn })
            return { state: 'failed', reason: 'max_turns_exceeded', turns: turn }
        }
        await emit('completed', { turns: turn })
        return { state: 'completed', turns: turn }
    } finally {
        tearDownClientDispatch()
    }
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
 * The actual mutation lives in `sanitizeOutboundContext` (every outbound
 * surface that carries a tool id) and `translateAssistantNamesBack` (the
 * result echo). Routing them through these two functions means every new
 * tool-id-bearing field a provider starts validating gets caught in one
 * place — the `sanitizingStreamFn` itself is just composition.
 */
function sanitizingStreamFn(base: StreamFn, safeToOriginal: Map<string, string>): StreamFn {
    return async (model, context, options) => {
        const stream = await base(model, sanitizeOutboundContext(context), options)
        const result = async (): Promise<AssistantMessage> =>
            translateAssistantNamesBack(await stream.result(), safeToOriginal)
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
 * Rewrite every tool-id-bearing field in an outbound context to the
 * provider-safe form. Currently:
 *   - `context.tools[].name` — declarations the provider validates against.
 *   - `context.messages[]` — historical assistant `toolCall` names + the
 *     paired `toolResult.toolName` from prior turns. Strict providers
 *     (e.g. OpenAI Responses, `^[a-zA-Z0-9_-]+$`) reject the original
 *     `@posthog/query` shape in this position too, so without rewriting
 *     turn 2 fails with a 400 even though turn 1 went through fine.
 *
 * Any new tool-id-bearing field a future pi-ai version starts sending must
 * be added here — that's the load-bearing point of the consolidation.
 * `provider-safe-names-coverage.test.ts` runs a worst-case fixture (tool
 * declaration + historical toolCall + historical toolResult) through this
 * function to lock the contract.
 */
export function sanitizeOutboundContext<T extends { tools?: Array<{ name: string }>; messages?: Message[] }>(
    context: T
): T {
    return {
        ...context,
        tools: context.tools?.map((t) => ({ ...t, name: providerSafeName(t.name) })),
        messages: context.messages?.map(sanitizeMessageNames),
    }
}

/**
 * Inverse of the outbound name rewrite for the assistant's own reply: the
 * loop matches tool calls by their ORIGINAL id, so any `toolCall.name` the
 * provider echoed back in the assistant message needs to be translated
 * before the loop sees it. Anything not in the map (e.g. the faux provider
 * echoing the original verbatim) passes through unchanged.
 */
export function translateAssistantNamesBack(
    msg: AssistantMessage,
    safeToOriginal: Map<string, string>
): AssistantMessage {
    return {
        ...msg,
        content: msg.content.map((b) =>
            b.type === 'toolCall' ? { ...b, name: safeToOriginal.get(b.name) ?? b.name } : b
        ),
    }
}

/**
 * Stamp `Idempotency-Key` + `X-Request-Id` (both `agent:<session>:<turn>`)
 * on every outbound model call, plus any caller-supplied gateway headers
 * (`X-PostHog-Distinct-Id`, `X-PostHog-Trace-Id`). The id is recorded in
 * `turnRequestIds` keyed by the loop's outbound-call counter so the sink
 * can fetch settled cost via `GET /v1/usage/<request_id>` after `turn_end`.
 *
 * Idempotency on this exact id buys gateway-side dedupe for pi-ai's own
 * retries on transient 5xx — the gateway collapses both attempts onto the
 * same usage row and bills the team once.
 */
function gatewayMetadataStreamFn(
    base: StreamFn,
    sessionId: string,
    gatewayHeaders: Record<string, string> | undefined,
    turnRequestIds: Map<number, string>
): StreamFn {
    let outboundTurn = 0
    return async (model, context, options) => {
        outboundTurn++
        const requestId = `agent:${sessionId}:${outboundTurn}`
        turnRequestIds.set(outboundTurn, requestId)
        const headers = {
            ...gatewayHeaders,
            ...options?.headers,
            'Idempotency-Key': requestId,
            'X-Request-Id': requestId,
        }
        return base(model, context, { ...options, headers })
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
