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
            const newInputs = state.pendingInputs.slice()
            state.pendingInputs = []

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
                    await job.ack()
                    return
                case 'failed':
                    await this.publish(job.id, sessionLogger, {
                        type: 'session_failed',
                        at: new Date().toISOString(),
                        error: outcome.error,
                    })
                    await job.fail()
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
                    await job.cancel()
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
                case 'awaiting_input':
                    state.messages.push(outcome.message)
                    state.turnCount += 1
                    // Park the job in the future; /send/:id arrivals from the bus
                    // bring it forward via the input listener once that wiring lands.
                    await job.reschedule({
                        scheduledAt: new Date(Date.now() + 60_000),
                        state: serializeState(state),
                    })
                    return
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
