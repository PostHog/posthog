import {
    DequeuedSessionJob,
    LogProducer,
    SessionBus,
    SessionEvent,
    SessionLogger,
    SessionQueueWorker,
    WorkerConfig,
    createSessionLogger,
    logger,
} from '@posthog/agent-core'

import { SessionExecutor } from './executor'
import { SessionState, deserializeState, serializeState } from './state'
import { executeTool } from './tools/registry'
import { ToolContext } from './tools/types'

export interface RunnerWorkerConfig extends WorkerConfig {
    executor: SessionExecutor
    bus: SessionBus
    logProducer: LogProducer
    /** Lookup that returns the per-application secrets dictionary. Hooked to the internal-API client in prod. */
    loadSecrets: (applicationId: string | null) => Promise<Record<string, string>>
}

/**
 * Consumes session jobs and runs one turn per dequeue, rescheduling at every
 * tool boundary. The queue worker is the source of concurrency: it caps the
 * number of in-flight jobs (`config.concurrency`) and auto-heartbeats each
 * row's `last_heartbeat` during its handler — we don't manage that loop here.
 */
export class RunnerWorker {
    private readonly queue: SessionQueueWorker
    private readonly executor: SessionExecutor
    private readonly bus: SessionBus
    private readonly logProducer: LogProducer
    private readonly loadSecrets: RunnerWorkerConfig['loadSecrets']

    constructor(config: RunnerWorkerConfig) {
        this.queue = new SessionQueueWorker({
            pool: config.pool,
            queueName: config.queueName,
            concurrency: config.concurrency,
            pollDelayMs: config.pollDelayMs,
            heartbeatTimeoutMs: config.heartbeatTimeoutMs,
            heartbeatIntervalMs: config.heartbeatIntervalMs,
            drainTimeoutMs: config.drainTimeoutMs,
        })
        this.executor = config.executor
        this.bus = config.bus
        this.logProducer = config.logProducer
        this.loadSecrets = config.loadSecrets
    }

    async start(): Promise<void> {
        await this.queue.connect((job) => this.processJob(job))
    }

    async stop(): Promise<void> {
        await this.queue.disconnect()
    }

    isHealthy(): boolean {
        return this.queue.isHealthy()
    }

    private async processJob(job: DequeuedSessionJob): Promise<void> {
        const sessionLogger: SessionLogger = createSessionLogger({
            teamId: job.teamId,
            applicationId: job.applicationId,
            sessionId: job.id,
            producer: this.logProducer,
        })

        try {
            const state = deserializeState(job.state)
            // The queue dequeue SNAPSHOTS `pending_inputs` into
            // `job.drainedInputs` (it doesn't clear the column).
            // Anything still sitting in the legacy in-state
            // `pendingInputs` (from older queue rows that pre-date the
            // column) is folded in too — order preserved.
            //
            // The `at` timestamps of these snapshotted entries are
            // threaded into the commit (ack/reschedule/fail/cancel) so
            // the same UPDATE that writes state also filters out the
            // consumed entries from pending_inputs. At-least-once: if
            // this worker dies before committing, the next dequeue sees
            // the same /sends again.
            const newInputs = [
                ...state.pendingInputs,
                ...job.drainedInputs.map((p) => ({ at: p.at, content: p.content })),
            ]
            state.pendingInputs = []
            const drainedInputAts = job.drainedInputs.map((p) => p.at)

            // On turn 0, the trigger's initial input becomes the first
            // user message. We log it once here so it shows up in CH
            // alongside subsequent /send-delivered user messages; the
            // executor sees it via state.messages.
            if (state.turnCount === 0 && state.initialInput && Object.keys(state.initialInput).length > 0) {
                const initialContent = extractInitialMessage(state.initialInput)
                if (initialContent !== null) {
                    state.messages.push({ role: 'user', content: initialContent, at: new Date().toISOString() })
                    await this.publish(job.id, sessionLogger, {
                        type: 'message',
                        at: new Date().toISOString(),
                        role: 'user',
                        content: initialContent,
                    })
                }
            }

            // Each drained /send becomes a `user` message in the canonical
            // log. Done BEFORE the executor runs so the executor's
            // state.messages snapshot already includes the new user input.
            for (const input of newInputs) {
                state.messages.push({ role: 'user', content: input.content, at: input.at })
                await this.publish(job.id, sessionLogger, {
                    type: 'message',
                    at: input.at,
                    role: 'user',
                    content: input.content,
                })
            }

            await this.publish(job.id, sessionLogger, { type: 'turn_started', at: new Date().toISOString() })

            const secrets = await this.loadSecrets(job.applicationId)
            const ctx: ToolContext = {
                sessionId: job.id,
                teamId: job.teamId,
                applicationId: job.applicationId,
                revisionId: job.revisionId,
                secrets,
            }

            const outcome = await this.executor.runTurn({
                state,
                newInputs: newInputs.map((m) => ({ content: m.content, at: m.at })),
                job: {
                    sessionId: job.id,
                    teamId: job.teamId,
                    applicationId: job.applicationId,
                    revisionId: job.revisionId,
                    secrets,
                    principal: job.principal,
                },
            })

            await this.publish(job.id, sessionLogger, { type: 'turn_completed', at: new Date().toISOString() })

            switch (outcome.kind) {
                case 'completed':
                    state.messages.push(outcome.message)
                    state.turnCount += 1
                    // Surface the executor's assistant message on the bus +
                    // log_entries before the terminal session_completed event.
                    // Without this, the model's final reply only ever lives
                    // inside SessionState (a runner-internal blob) — clients
                    // listening on /listen and the log_entries downstream
                    // never see what the agent actually said.
                    await this.publish(job.id, sessionLogger, {
                        type: 'message',
                        at: outcome.message.at ?? new Date().toISOString(),
                        role: outcome.message.role,
                        content: outcome.message.content,
                    })
                    await this.publish(job.id, sessionLogger, {
                        type: 'session_completed',
                        at: new Date().toISOString(),
                        output: outcome.output,
                    })
                    // Persist final state on terminal transitions AND
                    // filter the consumed pending_inputs entries in the
                    // same UPDATE. Without `drainedInputAts` the column
                    // would keep growing forever for at-least-once
                    // resilience; without `state` the conversation log
                    // would close empty.
                    await job.ack({ state: serializeState(state), drainedInputAts })
                    return
                case 'failed':
                    await this.publish(job.id, sessionLogger, {
                        type: 'session_failed',
                        at: new Date().toISOString(),
                        error: outcome.error,
                    })
                    await job.fail({ state: serializeState(state), drainedInputAts })
                    return
                case 'cancelled':
                    // Client aborted the run via /cancel/:id. The durable record
                    // is the queue row's `canceled` status; the live event is a
                    // terminal `session_failed` with an explicit reason (there is
                    // no separate `session_canceled` event in the union today).
                    await this.publish(job.id, sessionLogger, {
                        type: 'session_failed',
                        at: new Date().toISOString(),
                        error: 'cancelled by client',
                    })
                    await job.cancel({ state: serializeState(state), drainedInputAts })
                    return
                case 'tool_call': {
                    state.messages.push(outcome.message)
                    state.turnCount += 1
                    await this.publish(job.id, sessionLogger, {
                        type: 'tool_call',
                        tool: outcome.call.id,
                        at: new Date().toISOString(),
                        args: outcome.call.args,
                    })
                    const result = await this.runToolCall(outcome.call, ctx)
                    await this.publish(job.id, sessionLogger, {
                        type: 'tool_result',
                        tool: outcome.call.id,
                        at: new Date().toISOString(),
                        ok: result.ok,
                        result: result.ok ? result.value : undefined,
                        error: result.ok ? undefined : result.error,
                    })
                    state.messages.push({
                        role: 'system',
                        content: JSON.stringify({ tool: outcome.call.id, result }),
                        at: new Date().toISOString(),
                    })
                    await job.reschedule({
                        scheduledAt: new Date(),
                        state: serializeState(state),
                    })
                    return
                }
                case 'awaiting_input': {
                    state.messages.push(outcome.message)
                    state.turnCount += 1
                    await this.publish(job.id, sessionLogger, {
                        type: 'message',
                        at: outcome.message.at ?? new Date().toISOString(),
                        role: outcome.message.role,
                        content: outcome.message.content,
                    })
                    await this.publish(job.id, sessionLogger, {
                        type: 'awaiting_input',
                        at: new Date().toISOString(),
                        prompt: typeof outcome.message.content === 'string' ? outcome.message.content : null,
                    })
                    // /send writes to `pending_inputs` durably AND, when
                    // status='available', advances `scheduled` to NOW.
                    // But while THIS turn was running the status was
                    // 'running', so a /send mid-turn lands in
                    // pending_inputs without advancing the schedule.
                    // Check the column here before parking: if it's
                    // non-empty, reschedule to NOW so the worker
                    // drains the queued input on the very next poll.
                    // Otherwise park ~one minute out and wait for a
                    // future /send (or the janitor) to wake us.
                    const hasQueuedInput = await this.queue.hasPendingInputs(job.id, drainedInputAts)
                    const scheduledAt = hasQueuedInput ? new Date() : new Date(Date.now() + 60_000)
                    await job.reschedule({
                        scheduledAt,
                        state: serializeState(state),
                        drainedInputAts,
                    })
                    return
                }
            }
        } catch (err) {
            logger.error({ err, sessionId: job.id }, 'runner job processing failed')
            await this.publish(job.id, sessionLogger, {
                type: 'session_failed',
                at: new Date().toISOString(),
                error: err instanceof Error ? err.message : String(err),
            })
            try {
                await job.fail()
            } catch (failErr) {
                logger.error({ err: failErr, sessionId: job.id }, 'runner job fail() failed')
            }
        }
    }

    private async runToolCall(call: { id: string; args: unknown }, ctx: ToolContext): ReturnType<typeof executeTool> {
        return executeTool({ id: call.id, args: call.args }, ctx)
    }

    private async publish(sessionId: string, sessionLogger: SessionLogger, event: SessionEvent): Promise<void> {
        try {
            await this.bus.publishEvent(sessionId, event)
        } catch (err) {
            logger.error('runner publish failed', { sessionId, error: String(err) })
        }
        sessionLogger.appendEvent(event)
    }
}

export type { SessionState }

/**
 * Turn an `initialInput` dict (the parsed POST /run body or the parsed
 * Slack event) into a single user-facing message string for the
 * conversation log. The convention:
 *
 *   - `{ message: "..." }` → use the message field verbatim. Matches the
 *     chat-style invocation pattern.
 *   - `{ text: "..." }` → same convention for Slack events.
 *   - Anything else → JSON-stringify (lossy for nested objects, but
 *     gives the agent something to look at).
 *   - Empty object → null (caller skips adding the user message).
 */
function extractInitialMessage(initialInput: Record<string, unknown>): string | null {
    // http_invoke trigger payload — wraps the body inside a dict:
    //   { type: 'http_invoke', method, path, query, body: { message: '...' } }
    // The user's "message" lives under `body.message` (or `body.text`).
    const body = initialInput.body
    if (body && typeof body === 'object' && !Array.isArray(body)) {
        const inner = body as Record<string, unknown>
        if (typeof inner.message === 'string' && inner.message.length > 0) {
            return inner.message
        }
        if (typeof inner.text === 'string' && inner.text.length > 0) {
            return inner.text
        }
    }
    // slack_event trigger payload — `text` is at the top level.
    if (typeof initialInput.text === 'string' && initialInput.text.length > 0) {
        return initialInput.text
    }
    // Same convention but at the top of the dict — useful for inline
    // testing where callers POST { message: '...' } directly.
    if (typeof initialInput.message === 'string' && initialInput.message.length > 0) {
        return initialInput.message
    }
    try {
        const dumped = JSON.stringify(initialInput)
        return dumped && dumped !== '{}' ? dumped : null
    } catch {
        return null
    }
}
