import {
    DequeuedSessionJob,
    SessionBus,
    SessionEvent,
    SessionQueueWorker,
    WorkerConfig,
    logger,
} from '@posthog/agent-core'

import { SessionExecutor } from './executor'
import { SessionState, deserializeState, serializeState } from './state'
import { executeTool } from './tools/registry'
import { ToolContext } from './tools/types'

export interface RunnerWorkerConfig extends WorkerConfig {
    executor: SessionExecutor
    bus: SessionBus
    /** Lookup that returns the per-application secrets dictionary. Hooked to the internal-API client in prod. */
    loadSecrets: (applicationId: string | null) => Promise<Record<string, string>>
    /** Optional turn-level heartbeat interval. Defaults to 5s. */
    heartbeatIntervalMs?: number
}

/**
 * Consumes session jobs, runs one turn per dequeue, and reschedules at every tool
 * boundary. A heartbeat ticks while a turn is in flight so the janitor doesn't reap us.
 */
export class RunnerWorker {
    private readonly queue: SessionQueueWorker
    private readonly executor: SessionExecutor
    private readonly bus: SessionBus
    private readonly loadSecrets: RunnerWorkerConfig['loadSecrets']
    private readonly heartbeatIntervalMs: number

    constructor(config: RunnerWorkerConfig) {
        this.queue = new SessionQueueWorker({
            pool: config.pool,
            queueName: config.queueName,
            batchMaxSize: config.batchMaxSize,
            pollDelayMs: config.pollDelayMs,
            heartbeatTimeoutMs: config.heartbeatTimeoutMs,
            includeEmptyBatches: config.includeEmptyBatches,
        })
        this.executor = config.executor
        this.bus = config.bus
        this.loadSecrets = config.loadSecrets
        this.heartbeatIntervalMs = config.heartbeatIntervalMs ?? 5_000
    }

    async start(): Promise<void> {
        await this.queue.connect(async (batch) => {
            for (const job of batch) {
                await this.processJob(job)
            }
        })
    }

    async stop(): Promise<void> {
        await this.queue.disconnect()
    }

    isHealthy(): boolean {
        return this.queue.isHealthy()
    }

    private async processJob(job: DequeuedSessionJob): Promise<void> {
        const heartbeat = setInterval(() => {
            job.heartbeat().catch((err) => {
                logger.error('runner heartbeat failed', { sessionId: job.id, error: String(err) })
            })
        }, this.heartbeatIntervalMs)

        try {
            const state = deserializeState(job.state)
            const newInputs = state.pendingInputs.slice()
            state.pendingInputs = []

            await this.publish(job.id, { type: 'turn_started', at: new Date().toISOString() })

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
                },
            })

            await this.publish(job.id, { type: 'turn_completed', at: new Date().toISOString() })

            switch (outcome.kind) {
                case 'completed':
                    state.messages.push(outcome.message)
                    state.turnCount += 1
                    await this.publish(job.id, {
                        type: 'session_completed',
                        at: new Date().toISOString(),
                        output: outcome.output,
                    })
                    await job.ack()
                    return
                case 'failed':
                    await this.publish(job.id, {
                        type: 'session_failed',
                        at: new Date().toISOString(),
                        error: outcome.error,
                    })
                    await job.fail()
                    return
                case 'tool_call': {
                    state.messages.push(outcome.message)
                    state.turnCount += 1
                    await this.publish(job.id, {
                        type: 'tool_call',
                        tool: outcome.call.id,
                        at: new Date().toISOString(),
                        args: outcome.call.args,
                    })
                    const result = await this.runToolCall(outcome.call, ctx)
                    await this.publish(job.id, {
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
            logger.error('runner job processing failed', { sessionId: job.id, error: String(err) })
            await this.publish(job.id, {
                type: 'session_failed',
                at: new Date().toISOString(),
                error: String(err),
            })
            try {
                await job.fail()
            } catch (failErr) {
                logger.error('runner job fail() failed', { sessionId: job.id, error: String(failErr) })
            }
        } finally {
            clearInterval(heartbeat)
        }
    }

    private async runToolCall(call: { id: string; args: unknown }, ctx: ToolContext): ReturnType<typeof executeTool> {
        return executeTool({ id: call.id, args: call.args }, ctx)
    }

    private async publish(sessionId: string, event: SessionEvent): Promise<void> {
        try {
            await this.bus.publishEvent(sessionId, event)
        } catch (err) {
            logger.error('runner publish failed', { sessionId, error: String(err) })
        }
    }
}

export type { SessionState }
