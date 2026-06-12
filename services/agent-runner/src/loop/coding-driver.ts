/**
 * Worker-integrated driver for in-sandbox coding agents. `runSession`
 * (driver.ts) delegates here when `spec.sandbox.loop_location === 'in_sandbox'`.
 * It mirrors what `runSession` does for a normal session — emits the same
 * lifecycle events to the bus + log, persists the conversation each turn,
 * drains `pending_inputs` for multi-turn, honours the shutdown signal — but
 * the LLM runs in the tier-2 harness instead of pi-agent-core in-process.
 *
 * The sandbox is acquired once and kept alive for the whole invocation, so
 * follow-up `/send`s that arrive while the session runs reuse the same
 * workspace + harness context. (Surviving suspend/resume with workspace state
 * intact needs sandbox snapshots — a follow-up; see plan §11.)
 *
 * Driven entirely through the `CodingSandboxPool` interface, so the turn loop
 * is unit-tested with a fake pool (no Docker). The real harness path is
 * covered by coding-supervisor.realharness.test.ts.
 */

import {
    AgentRevision,
    AgentSession,
    AnalyticsEvent,
    AnalyticsSink,
    analyticsDistinctId,
    AssistantMessageRecord,
    buildResumePrompt,
    CodingEvent,
    CodingLaunchConfig,
    CodingSandbox,
    ConversationMessage,
    EMPTY_USAGE_TOTAL,
    formatConversationForResume,
    generateHarnessKeypair,
    generationSpanId,
    LogLevel,
    LogSink,
    mintHarnessJwt,
    mintInferenceProxyToken,
    NoopAnalyticsSink,
    parseFrame,
    renderLaunchConfig,
    SessionEvent,
    SessionEventBus,
    SessionEventKind,
    SessionInputsStore,
    TextContent,
    ToolCall,
    toolSpanId,
    ToolResultMessage,
} from '@posthog/agent-shared'

import type { RunOutcome, RunSessionDeps } from './driver'

/** Pull the text out of a user `ConversationMessage`. */
function userMessageText(msg: ConversationMessage): string | null {
    if (msg.role !== 'user') {
        return null
    }
    if (typeof msg.content === 'string') {
        return msg.content
    }
    return msg.content
        .map((c) => ('text' in c && typeof c.text === 'string' ? c.text : ''))
        .join('')
        .trim()
}

export async function driveCodingSession(
    rev: AgentRevision,
    session: AgentSession,
    deps: RunSessionDeps
): Promise<RunOutcome> {
    const bus: SessionEventBus = deps.bus
    const logs: LogSink = deps.logs
    const inputs: SessionInputsStore = deps.inputs

    const emit = async (kind: SessionEventKind, data: Record<string, unknown> = {}): Promise<void> => {
        const ts = new Date().toISOString()
        await bus.publish({ session_id: session.id, kind, data, ts } satisfies SessionEvent)
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

    // LLM analytics — mirrors the in-process driver: one `$ai_generation` per
    // turn, one `$ai_span` per tool call, one `$ai_trace` at terminal outcome,
    // all sharing the session id as trace id and routed to the agent's own
    // project. The harness calls the model via the gateway, but the driver owns
    // the trace so the agent's LLM Analytics gets the full picture (spans + the
    // `$agent_*` props the gateway can't see).
    const analytics: AnalyticsSink = deps.analytics ?? new NoopAnalyticsSink()
    const distinctId = analyticsDistinctId(session)

    if (!deps.codingPool) {
        await emit('failed', { reason: 'coding_pool_unavailable' })
        return { state: 'failed', reason: 'coding_pool_unavailable', turns: 0 }
    }

    // The agent's persona (agent.md / spec.entrypoint) is appended to the
    // harness's claude_code preset — the same layering the in-process
    // framework prompt does. Best-effort: a missing entrypoint falls back to
    // the harness preset rather than failing the session.
    let systemPrompt: string | undefined
    try {
        const entry = rev.spec.entrypoint || 'agent.md'
        if (deps.bundle && (await deps.bundle.exists(rev.id, entry))) {
            systemPrompt = await deps.bundle.readText(rev.id, entry)
        }
    } catch {
        systemPrompt = undefined
    }

    // With a proxy configured, the sandbox holds only a session-bound
    // capability token (dead once the session stops being live) — the real
    // gateway key stays on the ingress proxy side. TTL covers the session's
    // wall limit plus slack.
    const proxy = deps.codingGateway?.inferenceProxy
    const apiKey = proxy
        ? await mintInferenceProxyToken({
              sessionId: session.id,
              signingKey: proxy.signingKey,
              ttlSec: rev.spec.limits.max_wall_seconds + 600,
          })
        : deps.codingGateway?.apiKey

    const launch: CodingLaunchConfig = {
        ...renderLaunchConfig(rev.spec, { modelBaseUrl: deps.codingGateway?.baseUrl, systemPrompt }),
        apiKey,
        apiUrl: deps.posthogApiBaseUrl,
        projectId: deps.codingGateway?.projectId,
    }

    const taskId = `task-${session.id}`
    const runId = `run-${session.id}`
    const keypair = generateHarnessKeypair()
    const token = mintHarnessJwt(keypair.privateKeyPem, {
        run_id: runId,
        task_id: taskId,
        team_id: session.team_id,
        user_id: 0,
        distinct_id: `coding-${session.id}`,
        mode: 'background',
    })

    await emit('session_started')
    if (deps.shutdownSignal?.aborted) {
        return { state: 'suspended', reason: 'shutdown', turns: 0 }
    }

    let turns = 0
    let turnText = ''
    let turnError: string | null = null
    let turnStart = Date.now()
    // Per-turn tool activity, captured for the persisted transcript + analytics.
    let turnToolCalls = new Map<string, { tool?: string; command?: string }>()
    let turnToolStarts = new Map<string, number>()
    let turnToolResults: {
        toolCallId: string
        toolName: string
        output: string
        isError: boolean
        latencyMs: number
    }[] = []
    // Per-turn token/cost deltas — emitted on the turn's `$ai_generation`.
    let turnUsage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0 }
    // Trace-level state for the terminal `$ai_trace`.
    let traceInput: string | null = null
    let lastOutput: unknown = null
    let markConnected: () => void = () => undefined
    const connected = new Promise<void>((resolve) => (markConnected = resolve))

    const handle = (event: CodingEvent): void => {
        switch (event.kind) {
            case 'connected':
                markConnected()
                return
            case 'assistant_text':
                if (event.text) {
                    turnText += event.text
                    void emit('assistant_text_delta', { text: event.text })
                }
                return
            case 'thought':
                if (event.text) {
                    void emit('assistant_thinking_delta', { text: event.text })
                }
                return
            case 'tool_call': {
                const prev = turnToolCalls.get(event.toolCallId) ?? {}
                turnToolCalls.set(event.toolCallId, {
                    tool: event.tool ?? prev.tool,
                    command: event.command ?? prev.command,
                })
                if (!turnToolStarts.has(event.toolCallId)) {
                    turnToolStarts.set(event.toolCallId, Date.now())
                }
                void emit('tool_call', { tool: event.tool, command: event.command, tool_call_id: event.toolCallId })
                return
            }
            case 'tool_result': {
                const start = turnToolStarts.get(event.toolCallId)
                turnToolResults.push({
                    toolCallId: event.toolCallId,
                    toolName: turnToolCalls.get(event.toolCallId)?.tool ?? 'tool',
                    output: event.output ?? '',
                    isError: !event.ok,
                    latencyMs: start ? Date.now() - start : 0,
                })
                void emit('tool_result', { tool_call_id: event.toolCallId, ok: event.ok })
                return
            }
            case 'usage': {
                const u = (session.usage_total = session.usage_total ?? { ...EMPTY_USAGE_TOTAL })
                u.tokens_in += event.inputTokens
                u.tokens_out += event.outputTokens
                u.cache_read += event.cacheRead
                u.cache_write += event.cacheWrite
                u.cost_total += event.costUsd
                turnUsage.input += event.inputTokens
                turnUsage.output += event.outputTokens
                turnUsage.cacheRead += event.cacheRead
                turnUsage.cacheWrite += event.cacheWrite
                turnUsage.cost += event.costUsd
                return
            }
            case 'permission_request':
                // No approval queue wired yet — auto-allow (harness defaults to
                // bypassPermissions, so this is belt-and-braces). Real gating is
                // a follow-up (plan §11 / scratchpad).
                if (sandbox) {
                    const allow = event.options.find((o) => o.kind?.includes('allow')) ?? event.options[0]
                    void sandbox.command({
                        method: 'permission_response',
                        params: { requestId: event.requestId, optionId: allow?.optionId ?? 'allow' },
                    })
                }
                return
            case 'error':
                turnError = event.message
                return
            default:
                return
        }
    }

    let sandbox: CodingSandbox | undefined
    let subscription: { close: () => void } | undefined

    // Append the harness's container logs to a failure reason so a boot/runtime
    // crash is debuggable (otherwise the supervisor only sees an ECONNREFUSED
    // to a now-closed port). Owner-facing — lands in log_entries.
    const withHarnessLogs = async (reason: string): Promise<string> => {
        if (!sandbox) {
            return reason
        }
        const logs = (await sandbox.logs().catch(() => '')).slice(-4000)
        return logs ? `${reason}\n--- harness logs (tail) ---\n${logs}` : reason
    }

    // One `$ai_trace` per session at terminal outcome — names the trace (agent
    // name) + input/output state on top of the per-turn generations/spans that
    // already share this trace id. Skipped on suspend (the session ends for
    // real on resume).
    const writeTrace = async (isError: boolean, error?: string): Promise<void> => {
        await analytics.write([
            {
                kind: 'trace',
                ts: new Date().toISOString(),
                team_id: session.team_id,
                application_id: session.application_id,
                revision_id: rev.id,
                session_id: session.id,
                turn: turns,
                span_id: session.id,
                distinct_id: distinctId,
                trace_name: deps.applicationName ?? `agent:${session.application_id}`,
                input_state: traceInput,
                output_state: lastOutput,
                is_error: isError,
                error,
            },
        ])
    }

    try {
        sandbox = await deps.codingPool.acquireForSession({
            sessionId: session.id,
            teamId: session.team_id,
            launch,
            auth: { publicKeyPem: keypair.publicKeyPem, token },
            harnessIds: { taskId, runId },
        })

        subscription = sandbox.openEvents((frame) => {
            const event = parseFrame(frame)
            if (event) {
                handle(event)
            }
        })
        // Opening /events initializes the session; wait for the harness's
        // `connected` frame before relaying the turn (bounded fallback).
        await Promise.race([connected, new Promise((r) => setTimeout(r, 5_000))])

        // Seed the turn queue. The trailing conversation message is only an
        // unanswered prompt on the very first invocation — on a re-claim after a
        // /send it's the previous turn's assistant/toolResult, and the new input
        // sits in `pending_inputs`. So: take the trailing message only when it's
        // a user turn, then drain pending_inputs for any /send (a follow-up
        // re-claim, or one that raced in before the first turn). Re-running the
        // trailing conversation message unconditionally is what made follow-ups
        // replay the original prompt against a fresh harness.
        const queue: string[] = []
        const trailing = session.conversation[session.conversation.length - 1]
        // Prior-invocation history (everything before this invocation's new
        // input). The sandbox was torn down with the previous invocation, so a
        // re-claim boots a harness that knows nothing — replay the history as
        // context on the first send (interim until sandbox snapshot/resume).
        // Persisted transcript + analytics keep the raw message; only what
        // goes over the wire is wrapped.
        const priorHistory = trailing?.role === 'user' ? session.conversation.slice(0, -1) : [...session.conversation]
        const resumeContext = priorHistory.some((m) => m.role === 'assistant')
            ? formatConversationForResume(priorHistory)
            : null
        let firstSend = true
        if (trailing?.role === 'user') {
            const text = userMessageText(trailing)
            if (text) {
                queue.push(text)
                traceInput = text
            }
        }
        for (const msg of await inputs.drainPendingInputs(session.id)) {
            const text = userMessageText(msg)
            if (text) {
                session.conversation.push(msg)
                queue.push(text)
                traceInput = traceInput ?? text
            }
        }

        while (queue.length > 0) {
            if (deps.shutdownSignal?.aborted) {
                return { state: 'suspended', reason: 'shutdown', turns }
            }
            if (turns >= rev.spec.limits.max_turns) {
                break
            }
            const userText = queue.shift() as string
            turns += 1
            turnText = ''
            turnError = null
            turnStart = Date.now()
            turnToolCalls = new Map()
            turnToolStarts = new Map()
            turnToolResults = []
            turnUsage = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: 0 }
            await emit('turn_started', { turn: turns })

            // `/command` user_message is synchronous — it returns when the turn
            // is done; events stream over SSE during the await.
            const wireText = firstSend && resumeContext ? buildResumePrompt(resumeContext, userText) : userText
            firstSend = false
            const ack = await sandbox.command({ method: 'user_message', params: { content: wireText } })
            await new Promise((r) => setTimeout(r, 150)) // flush trailing SSE frames

            if (ack.error) {
                turnError = ack.error.message
            }

            // Persist a structured transcript matching the in-process shape: the
            // assistant message carries the text + tool-call blocks, followed by
            // one toolResult message per tool call.
            const assistantContent: (TextContent | ToolCall)[] = []
            if (turnText) {
                assistantContent.push({ type: 'text', text: turnText })
            }
            for (const [id, tc] of turnToolCalls) {
                assistantContent.push({
                    type: 'toolCall',
                    id,
                    name: tc.tool ?? 'tool',
                    arguments: tc.command ? { command: tc.command } : {},
                })
            }
            const assistantMsg: AssistantMessageRecord = {
                role: 'assistant',
                content: assistantContent,
                model: rev.spec.model,
                timestamp: Date.now(),
            }
            session.conversation.push(assistantMsg)
            for (const tr of turnToolResults) {
                const toolResultMsg: ToolResultMessage = {
                    role: 'toolResult',
                    toolCallId: tr.toolCallId,
                    toolName: tr.toolName,
                    content: [{ type: 'text', text: tr.output }],
                    isError: tr.isError,
                    timestamp: Date.now(),
                }
                session.conversation.push(toolResultMsg)
            }
            if (turnText) {
                await emit('assistant_text', { text: turnText })
            }
            lastOutput = assistantContent

            // One `$ai_generation` for the turn's model call + one `$ai_span`
            // per tool dispatch, all under this session's trace. Best-effort —
            // the sink swallows its own failures, never the session.
            const genSpan = generationSpanId(session.id, turns)
            const analyticsEvents: AnalyticsEvent[] = turnToolResults.map((tr) => ({
                kind: 'span',
                ts: new Date().toISOString(),
                team_id: session.team_id,
                application_id: session.application_id,
                revision_id: rev.id,
                session_id: session.id,
                turn: turns,
                span_id: toolSpanId(session.id, turns, tr.toolCallId),
                parent_span_id: genSpan,
                distinct_id: distinctId,
                tool_name: tr.toolName,
                tool_call_id: tr.toolCallId,
                input: { command: turnToolCalls.get(tr.toolCallId)?.command ?? '' },
                output: tr.output,
                latency_ms: tr.latencyMs,
                is_error: tr.isError,
            }))
            analyticsEvents.push({
                kind: 'generation',
                ts: new Date().toISOString(),
                team_id: session.team_id,
                application_id: session.application_id,
                revision_id: rev.id,
                session_id: session.id,
                turn: turns,
                span_id: genSpan,
                distinct_id: distinctId,
                model: launch.model,
                provider: launch.provider ?? 'posthog-ai-gateway',
                input: [{ role: 'user', content: userText }],
                output: assistantContent,
                input_tokens: turnUsage.input,
                output_tokens: turnUsage.output,
                cache_read_tokens: turnUsage.cacheRead,
                cache_write_tokens: turnUsage.cacheWrite,
                latency_ms: Date.now() - turnStart,
                cost_usd: turnUsage.cost,
                stop_reason: turnError ? 'error' : 'stop',
                is_error: Boolean(turnError),
                error: turnError ?? undefined,
            })
            await analytics.write(analyticsEvents)
            await deps.onTurnPersist?.(session)

            if (turnError) {
                const reason = await withHarnessLogs(turnError)
                await emit('failed', { reason })
                await writeTrace(true, reason)
                return { state: 'failed', reason, turns }
            }

            // Drain any /send that landed while this turn ran.
            const drained = await inputs.drainPendingInputs(session.id)
            for (const msg of drained) {
                const text = userMessageText(msg)
                if (text) {
                    session.conversation.push(msg)
                    queue.push(text)
                }
            }
        }

        await emit('completed')
        await writeTrace(false)
        return { state: 'completed', turns }
    } catch (err) {
        if (deps.shutdownSignal?.aborted) {
            return { state: 'suspended', reason: 'shutdown', turns }
        }
        const reason = await withHarnessLogs(err instanceof Error ? err.message : 'coding_session_error')
        await emit('failed', { reason })
        await writeTrace(true, reason)
        return { state: 'failed', reason, turns }
    } finally {
        subscription?.close()
        await deps.codingPool.release(session.id).catch(() => undefined)
    }
}
