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
    AssistantMessageRecord,
    CodingEvent,
    CodingLaunchConfig,
    CodingSandbox,
    ConversationMessage,
    EMPTY_USAGE_TOTAL,
    generateHarnessKeypair,
    LogLevel,
    LogSink,
    mintHarnessJwt,
    parseFrame,
    renderLaunchConfig,
    SessionEvent,
    SessionEventBus,
    SessionEventKind,
    SessionInputsStore,
    TextContent,
    ToolCall,
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

/** The trailing user message — the turn this invocation should start on. */
function lastUserText(conversation: ConversationMessage[]): string | null {
    for (let i = conversation.length - 1; i >= 0; i--) {
        const t = userMessageText(conversation[i])
        if (t) {
            return t
        }
    }
    return null
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

    const launch: CodingLaunchConfig = {
        ...renderLaunchConfig(rev.spec, { modelBaseUrl: deps.codingGateway?.baseUrl, systemPrompt }),
        apiKey: deps.codingGateway?.apiKey,
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
    // Per-turn tool activity, captured for the persisted transcript.
    let turnToolCalls = new Map<string, { tool?: string; command?: string }>()
    let turnToolResults: { toolCallId: string; toolName: string; output: string; isError: boolean }[] = []
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
                void emit('tool_call', { tool: event.tool, command: event.command, tool_call_id: event.toolCallId })
                return
            }
            case 'tool_result':
                turnToolResults.push({
                    toolCallId: event.toolCallId,
                    toolName: turnToolCalls.get(event.toolCallId)?.tool ?? 'tool',
                    output: event.output ?? '',
                    isError: !event.ok,
                })
                void emit('tool_result', { tool_call_id: event.toolCallId, ok: event.ok })
                return
            case 'usage': {
                const u = (session.usage_total = session.usage_total ?? { ...EMPTY_USAGE_TOTAL })
                u.tokens_in += event.inputTokens
                u.tokens_out += event.outputTokens
                u.cache_read += event.cacheRead
                u.cache_write += event.cacheWrite
                u.cost_total += event.costUsd
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

        const queue: string[] = []
        const first = lastUserText(session.conversation)
        if (first) {
            queue.push(first)
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
            turnToolCalls = new Map()
            turnToolResults = []
            await emit('turn_started', { turn: turns })

            // `/command` user_message is synchronous — it returns when the turn
            // is done; events stream over SSE during the await.
            const ack = await sandbox.command({ method: 'user_message', params: { content: userText } })
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
            await deps.onTurnPersist?.(session)

            if (turnError) {
                const reason = await withHarnessLogs(turnError)
                await emit('failed', { reason })
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
        return { state: 'completed', turns }
    } catch (err) {
        if (deps.shutdownSignal?.aborted) {
            return { state: 'suspended', reason: 'shutdown', turns }
        }
        const reason = await withHarnessLogs(err instanceof Error ? err.message : 'coding_session_error')
        await emit('failed', { reason })
        return { state: 'failed', reason, turns }
    } finally {
        subscription?.close()
        await deps.codingPool.release(session.id).catch(() => undefined)
    }
}
