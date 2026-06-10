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
    CodingEvent,
    CodingLaunchConfig,
    CodingSandbox,
    ConversationMessage,
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

    const launch: CodingLaunchConfig = {
        ...renderLaunchConfig(rev.spec, { modelBaseUrl: deps.codingGateway?.baseUrl }),
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
            case 'tool_call':
                void emit('tool_call', { tool: event.tool, command: event.command, tool_call_id: event.toolCallId })
                return
            case 'usage':
                // Usage accounting from the harness stream is a follow-up.
                return
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
            await emit('turn_started', { turn: turns })

            // `/command` user_message is synchronous — it returns when the turn
            // is done; events stream over SSE during the await.
            const ack = await sandbox.command({ method: 'user_message', params: { content: userText } })
            await new Promise((r) => setTimeout(r, 150)) // flush trailing SSE frames

            if (ack.error) {
                turnError = ack.error.message
            }

            session.conversation.push({
                role: 'assistant',
                content: [{ type: 'text', text: turnText }],
                model: rev.spec.model,
                timestamp: Date.now(),
            })
            if (turnText) {
                await emit('assistant_text', { text: turnText })
            }
            await deps.onTurnPersist?.(session)

            if (turnError) {
                await emit('failed', { reason: turnError })
                return { state: 'failed', reason: turnError, turns }
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
        const reason = err instanceof Error ? err.message : 'coding_session_error'
        await emit('failed', { reason })
        return { state: 'failed', reason, turns }
    } finally {
        subscription?.close()
        await deps.codingPool.release(session.id).catch(() => undefined)
    }
}
