/**
 * One turn through the agent. Driven by `runSession` which loops turns until
 * the model returns stopReason=stop (or a meta tool ends/suspends, or limits
 * are hit, or shutdown is requested).
 *
 * Turn boundary discipline:
 *   - At turn start we drain `session.pending_inputs` into `conversation`.
 *     This is the recovery point for the "queued follow-ups during in-flight
 *     turn" case — /send appends to pending_inputs; the next turn picks it up.
 *   - After each turn we check the shutdown signal. If aborted, we persist
 *     and return `state=suspended` so a sibling worker can resume from PG.
 *   - pi-ai's `complete(model, context, { signal })` propagates the abort
 *     into the in-flight provider call too, so a SIGTERM during an LLM
 *     request cuts cleanly.
 */

import type { AssistantMessage, Context, Model, ToolCall } from '@earendil-works/pi-ai'

import {
    accumulateUsage,
    AgentRevision,
    AgentSession,
    AnalyticsSink,
    analyticsDistinctId,
    ApprovalStore,
    AssistantMessageRecord,
    BundleStore,
    ConversationMessage,
    createLogger,
    generationSpanId,
    IntegrationCredentials,
    isDeltaEventKind,
    LogLevel,
    LogSink,
    NoopAnalyticsSink,
    NoopLogSink,
    NoopSessionEventBus,
    Sandbox,
    SecretBroker,
    SessionEvent,
    SessionEventBus,
    SessionEventKind,
} from '@posthog/agent-shared'

import { PiClient } from '../models/pi-client'
import { parseApprovalDecidedMarker } from './approval-marker'
import { buildToolList } from './build-tool-list'
import { dispatchApproved, dispatchOne } from './dispatch-one'
import { FRAMEWORK_PROMPT_VERSION } from './framework-preamble'
import { buildToolNameMap, providerSafeName } from './provider-safe-names'
import { buildSystemPrompt } from './system-prompt'

export interface RunSessionDeps {
    pi: PiClient
    /** The pi-ai Model to invoke for this session (resolved from rev.spec.model). */
    model: Model<string>
    /** Per-call API key (provider-specific). Optional — PiAiClient has a default. */
    apiKey?: string
    bundle: BundleStore
    sandbox: Sandbox | null
    integrations: Record<string, IntegrationCredentials>
    /** Resolved plaintext secrets keyed by name. */
    secrets: Record<string, string>
    broker?: SecretBroker
    /** Aborting this signal mid-turn cancels the LLM call and stops the loop. */
    shutdownSignal?: AbortSignal
    /**
     * Called once per turn after a fresh assistant message is appended. The
     * worker uses it to persist progress so a crash mid-loop leaves valid state.
     */
    onTurnPersist?: (session: AgentSession) => Promise<void>
    /**
     * Lifecycle event sink. Defaults to NoopSessionEventBus.
     * Chat `/listen` SSE subscribes through this bus.
     */
    bus?: SessionEventBus
    /**
     * Structured log sink. Defaults to NoopLogSink.
     * Production writes to ClickHouse via Kafka.
     */
    logs?: LogSink
    /**
     * LLM analytics sink — `$ai_generation` per model call, `$ai_span` per
     * tool dispatch. Defaults to NoopAnalyticsSink. Production wires the
     * dedicated `agent_ai_events` Kafka topic. See `analytics-sink.ts`.
     */
    analytics?: AnalyticsSink
    /**
     * When this session ran through PostHog's llm-gateway. Tokens are still
     * trusted (provider response) but pi-ai's `cost.*` numbers are client-
     * side estimates we ignore — the gateway tracks server-side cost.
     */
    useGatewayCost?: boolean
    /**
     * Approval-gated tool store. When set, the dispatcher intercepts tool
     * calls flagged `requires_approval` and the turn loop processes
     * approval-decided wake markers in `pending_inputs`. See
     * docs/agent-platform/plans/approval-gated-tools.md.
     */
    approvals?: ApprovalStore
    /**
     * URL the synthetic queued tool_result surfaces to the model. The
     * dispatcher calls this with the new request id. Defaults to a
     * `urn:posthog:approval:<id>` placeholder.
     */
    buildApprovalUrl?: (requestId: string) => string
}

export type RunOutcome =
    /** Agent finished its turn; session is OPEN. Default end-of-turn state. */
    | { state: 'completed'; turns: number }
    /** Hard close via `meta-end-session`. Session is TERMINAL (unless `allow_restart`). */
    | { state: 'closed'; summary?: string; turns: number }
    /** Worker was asked to suspend (rolling deploy etc.) — re-queue and let a sibling resume. */
    | { state: 'suspended'; reason: 'shutdown'; turns: number }
    /** Hard failure. Session is TERMINAL regardless of `allow_restart`. */
    | { state: 'failed'; reason: string; turns: number }

export async function runSession(rev: AgentRevision, session: AgentSession, deps: RunSessionDeps): Promise<RunOutcome> {
    const system = await buildSystemPrompt(rev, deps.bundle)
    // Tools carry our internal ids (e.g. `@posthog/query`, `@posthog/meta-ask-for-input`,
    // custom `my.tool`). Providers (Anthropic/OpenAI) reject most of those
    // characters, so we sanitize at the pi-ai boundary and translate model-
    // emitted tool calls back to the internal id before dispatch.
    const tools = await buildToolList(rev, deps.bundle)
    const toolNameMap = buildToolNameMap(tools.map((t) => t.name))
    for (const t of tools) {
        t.name = providerSafeName(t.name)
    }
    const bus: SessionEventBus = deps.bus ?? new NoopSessionEventBus()
    const logs: LogSink = deps.logs ?? new NoopLogSink()
    const analytics: AnalyticsSink = deps.analytics ?? new NoopAnalyticsSink()
    const distinctId = analyticsDistinctId(session)
    let turns = 0
    // Per-session logger — every record carries session_id + application_id so
    // you can grep one session's full lifecycle out of a busy log stream.
    const runLog = createLogger('runner', {
        session_id: session.id,
        application_id: session.application_id,
        team_id: session.team_id,
    })
    // Compat shim for tool-dispatch's `log(level, msg, meta)` signature.
    const log = (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>): void => {
        runLog[level](meta ?? {}, msg)
    }
    runLog.debug(
        {
            spec_tools: rev.spec.tools.length,
            tools_to_model: tools.length,
            tool_names: tools.map((t) => t.name),
            model: rev.spec.model,
        },
        'session.run.start'
    )
    const emit = async (kind: SessionEventKind, data: Record<string, unknown> = {}): Promise<void> => {
        const ts = new Date().toISOString()
        await bus.publish({ session_id: session.id, kind, data, ts } satisfies SessionEvent)
        // Mirror lifecycle events into the structured log sink. Drop the
        // high-cardinality delta events — log_entries would balloon to
        // hundreds of rows per turn and become unusable for grep / debug.
        // The full-text `assistant_text` + full-args `tool_call` events
        // still fire at turn end so log consumers see one row per turn-of-
        // event-kind. Same trade-off the plan §5 calls out.
        if (isDeltaEventKind(kind)) {
            return
        }
        // Levels: failed → error; everything else → info.
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

    await emit('session_started', {
        team_id: session.team_id,
        agent: rev.application_id,
        rev: rev.id,
        // Stamp the active framework preamble version so real-inference
        // behaviour shifts can be correlated against preamble revisions.
        // See plan §7.3 (framework-system-prompt.md).
        framework_prompt_version: FRAMEWORK_PROMPT_VERSION,
    })

    while (turns < rev.spec.limits.max_turns) {
        // Shutdown check at the top of every turn — clean suspension point.
        if (deps.shutdownSignal?.aborted) {
            return { state: 'suspended', reason: 'shutdown', turns }
        }

        // Drain pending_inputs into the active conversation BEFORE invoking
        // the model. This is the merge point for /send during an in-flight
        // turn: those messages land here for the next pi-ai call to see.
        //
        // Approval-decided markers are intercepted BEFORE the drain — for
        // each marker we dispatch the approved tool, finalise the row, and
        // push the wrapped synthetic tool_result onto conversation. The
        // marker itself never lands in conversation, so the model never
        // sees the sentinel string. See approval-marker.ts.
        if (session.pending_inputs.length > 0) {
            const remaining: ConversationMessage[] = []
            for (const msg of session.pending_inputs) {
                const requestId = approvalMarkerRequestId(msg)
                if (!requestId || !deps.approvals) {
                    remaining.push(msg)
                    continue
                }
                const row = await deps.approvals.get(requestId)
                if (!row || row.state !== 'approving') {
                    // Stale / orphan marker — drop it. The decide path
                    // would have set state to `approving` if the row is
                    // ours to dispatch; anything else means the row was
                    // already finalised or was never valid.
                    runLog.warn({ requestId, rowState: row?.state ?? 'missing' }, 'approval.marker.dropped_stale')
                    continue
                }
                await dispatchApproved(row, {
                    rev,
                    session,
                    sandbox: deps.sandbox,
                    integrations: deps.integrations,
                    secrets: deps.secrets,
                    bundle: deps.bundle,
                    runLog,
                    log,
                    emit,
                    analytics,
                    parentSpanId: generationSpanId(session.id, turns + 1),
                    distinctId,
                    toolNameMap,
                    turn: turns + 1,
                    approvals: deps.approvals,
                })
            }
            if (remaining.length > 0) {
                session.conversation.push(...remaining)
            }
            session.pending_inputs = []
        }

        turns++
        await emit('turn_started', { turn: turns })

        const context: Context = {
            systemPrompt: system,
            messages: session.conversation as unknown as Context['messages'],
            tools,
        }
        runLog.debug({ turn: turns, messages: context.messages.length, tools: tools.length }, 'pi.stream.begin')
        let result: AssistantMessage | undefined
        const piStart = Date.now()
        const generationSpan = generationSpanId(session.id, turns)
        try {
            // Stream the turn. Deltas fan out to the SSE bus for live UIs;
            // the terminal `end` event carries the materialised
            // AssistantMessage that the rest of the turn loop operates on
            // (persistence, cost accumulation, analytics, tool dispatch).
            const stream = deps.pi.stream(deps.model, context, {
                apiKey: deps.apiKey,
                maxTokens: 4096,
                signal: deps.shutdownSignal,
                // `spec.reasoning` is opt-in; omitted means provider default
                // (no thinking). pi-ai silently ignores it for non-reasoning
                // models, so we can forward unconditionally.
                reasoning: rev.spec.reasoning,
            })
            for await (const delta of stream) {
                switch (delta.type) {
                    case 'text_delta':
                        await emit('assistant_text_delta', { turn: turns, text: delta.text })
                        continue
                    case 'thinking_delta':
                        await emit('assistant_thinking_delta', { turn: turns, thinking: delta.thinking })
                        continue
                    case 'toolcall_start':
                        await emit('tool_call_start', { turn: turns, id: delta.id, name: delta.name })
                        continue
                    case 'toolcall_delta':
                        await emit('tool_call_args_delta', { turn: turns, id: delta.id, argsDelta: delta.argsDelta })
                        continue
                    case 'toolcall_end':
                        // Dispatch waits for the full `tool_call` event we
                        // emit at turn-end (see below) — we don't fire
                        // anything here because the per-tool `tool_call`
                        // event is the dispatcher's source of truth.
                        continue
                    case 'end':
                        result = delta.assistantMessage
                        continue
                }
            }
            if (!result) {
                // pi-ai's contract is that `end` always fires unless the
                // stream is aborted (handled in the catch). If we get here
                // the stream terminated without `end` — treat as failed.
                runLog.error({ turn: turns }, 'pi.stream.no_end_event')
                return { state: 'failed', reason: 'pi-ai_stream_no_end', turns }
            }
        } catch (err) {
            const e = err as Error & { name?: string }
            if (e.name === 'AbortError' || deps.shutdownSignal?.aborted) {
                runLog.debug({ turn: turns }, 'pi.stream.aborted')
                return { state: 'suspended', reason: 'shutdown', turns }
            }
            // Best-effort analytics emission for the failed call so error rate
            // is visible in LLM Analytics. Provider/model come off the resolved
            // pi-ai Model since `result` isn't available here.
            await analytics.write([
                {
                    kind: 'generation',
                    ts: new Date().toISOString(),
                    team_id: session.team_id,
                    application_id: session.application_id,
                    revision_id: rev.id,
                    session_id: session.id,
                    turn: turns,
                    span_id: generationSpan,
                    distinct_id: distinctId,
                    model: deps.model.id,
                    provider: deps.model.provider,
                    input: context.messages,
                    output: null,
                    input_tokens: 0,
                    output_tokens: 0,
                    latency_ms: Date.now() - piStart,
                    is_error: true,
                    error: e.message ?? 'pi-ai_error',
                },
            ])
            runLog.error({ turn: turns, err: e.message }, 'pi.stream.failed')
            return { state: 'failed', reason: e.message ?? 'pi-ai_error', turns }
        }
        runLog.debug(
            {
                turn: turns,
                durationMs: Date.now() - piStart,
                stopReason: result.stopReason,
                tokensIn: result.usage?.input,
                tokensOut: result.usage?.output,
                contentBlocks: result.content.length,
            },
            'pi.stream.ok'
        )

        // Persist the assistant message into the conversation. We store the
        // full AssistantMessage including api/provider/model/usage/stopReason
        // — pi-ai accepts these back as context for the next turn.
        const assistantRecord: AssistantMessageRecord = {
            role: 'assistant',
            content: result.content,
            api: result.api,
            provider: result.provider,
            model: result.model,
            usage: result.usage,
            stopReason: result.stopReason,
            errorMessage: result.errorMessage,
            timestamp: result.timestamp,
        }
        session.conversation.push(assistantRecord)
        session.usage_total = accumulateUsage(session.usage_total, assistantRecord, {
            useGatewayCost: deps.useGatewayCost,
        })
        // Emit `$ai_generation` per call. cost_usd is suppressed on the
        // gateway path (pi-ai's numbers there are client-side estimates).
        await analytics.write([
            {
                kind: 'generation',
                ts: new Date(result.timestamp).toISOString(),
                team_id: session.team_id,
                application_id: session.application_id,
                revision_id: rev.id,
                session_id: session.id,
                turn: turns,
                span_id: generationSpan,
                distinct_id: distinctId,
                model: result.model ?? deps.model.id,
                provider: result.provider ?? deps.model.provider,
                input: context.messages,
                output: result.content,
                input_tokens: result.usage?.input ?? 0,
                output_tokens: result.usage?.output ?? 0,
                cache_read_tokens: result.usage?.cacheRead,
                cache_write_tokens: result.usage?.cacheWrite,
                total_tokens: result.usage?.totalTokens,
                latency_ms: Date.now() - piStart,
                cost_usd: deps.useGatewayCost ? undefined : result.usage?.cost?.total,
                stop_reason: result.stopReason,
                is_error: result.stopReason === 'error',
                error: result.stopReason === 'error' ? result.errorMessage : undefined,
            },
        ])
        await deps.onTurnPersist?.(session)

        // Emit assistant text events for SSE listeners. One event per text
        // block (streaming will subdivide later).
        for (const block of result.content) {
            if (block.type === 'text' && block.text) {
                await emit('assistant_text', { text: block.text })
            }
        }

        if (result.stopReason === 'error') {
            await emit('failed', { reason: result.errorMessage ?? 'model_error', turns })
            return { state: 'failed', reason: result.errorMessage ?? 'model_error', turns }
        }
        if (result.stopReason === 'aborted') {
            return { state: 'suspended', reason: 'shutdown', turns }
        }
        if (result.stopReason === 'length') {
            await emit('failed', { reason: 'max_tokens', turns })
            return { state: 'failed', reason: 'max_tokens', turns }
        }
        if (result.stopReason === 'stop') {
            // Natural stop is equivalent to `meta-end-turn` — agent done
            // with its turn, session OPEN.
            await emit('completed', { turns })
            return { state: 'completed', turns }
        }

        // stopReason === 'toolUse' — dispatch every tool call, append one
        // toolResult message per dispatch, loop for the follow-up turn.
        const toolCalls = result.content.filter((b): b is ToolCall => b.type === 'toolCall')
        if (toolCalls.length === 0) {
            await emit('completed', { turns })
            return { state: 'completed', turns }
        }

        let endTurn: { prompt?: string } | null = null
        let close: { summary?: string } | null = null

        for (const call of toolCalls) {
            const signal = await dispatchOne(call, {
                rev,
                session,
                sandbox: deps.sandbox,
                integrations: deps.integrations,
                secrets: deps.secrets,
                bundle: deps.bundle,
                runLog,
                log,
                emit,
                analytics,
                parentSpanId: generationSpan,
                distinctId,
                toolNameMap,
                turn: turns,
                approvals: deps.approvals,
                buildApprovalUrl: deps.buildApprovalUrl,
            })
            if (signal.kind === 'end_turn') {
                endTurn = { prompt: signal.prompt }
                break
            }
            if (signal.kind === 'close') {
                close = { summary: signal.summary }
                break
            }
        }

        await deps.onTurnPersist?.(session)

        if (close) {
            await emit('closed', { turns, summary: close.summary })
            return { state: 'closed', summary: close.summary, turns }
        }
        if (endTurn) {
            // `meta-ask-for-input` rides on end_turn but additionally emits
            // a UI focus hint with the prompt. State is `completed` either
            // way — the hint has no state-machine impact.
            if (endTurn.prompt) {
                await emit('ask_for_input', { turns, prompt: endTurn.prompt })
            }
            await emit('completed', { turns })
            return { state: 'completed', turns }
        }
    }
    await emit('failed', { reason: 'max_turns_exceeded', turns })
    return { state: 'failed', reason: 'max_turns_exceeded', turns }
}

/**
 * Returns the approval request id when this message is the runner's
 * internal "approval decided" wake marker — see approval-marker.ts. The
 * janitor's decide-approve endpoint writes one of these into
 * `pending_inputs` so the next turn can dispatch the approved tool.
 */
function approvalMarkerRequestId(msg: ConversationMessage): string | null {
    if (msg.role !== 'user') {
        return null
    }
    if (typeof msg.content === 'string') {
        return parseApprovalDecidedMarker(msg.content)
    }
    if (Array.isArray(msg.content) && msg.content.length === 1 && msg.content[0].type === 'text') {
        return parseApprovalDecidedMarker(msg.content[0].text)
    }
    return null
}
