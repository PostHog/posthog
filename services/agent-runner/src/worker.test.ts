import { DateTime } from 'luxon'

import { FakeLogProducer, InMemorySessionBus, SessionEvent } from '@posthog/agent-core'

import { ExecutorTurnOutput, SessionExecutor } from './executor'
import { deserializeState, serializeState } from './state'
import { RunnerWorker } from './worker'

/**
 * Drives processJob via a non-public hook (cast to any). The worker's queue dependency
 * is real but never connected; instead, we hand-craft a DequeuedSessionJob and call into
 * processJob to verify the orchestration without spinning up Postgres.
 */
interface JobCallRecord {
    method: string
    args?: unknown
}

interface FakeDequeuedJob {
    id: string
    teamId: number
    applicationId: string | null
    revisionId: string | null
    queueName: string
    scheduled: DateTime
    created: DateTime
    transitionCount: number
    state: Buffer | null
    ack(): Promise<void>
    fail(): Promise<void>
    reschedule(input?: unknown): Promise<void>
    cancel(): Promise<void>
    heartbeat(): Promise<void>
}

function makeJob(
    id: string,
    opts: { state?: Buffer; applicationId?: string | null }
): { record: JobCallRecord[]; job: FakeDequeuedJob } {
    const calls: JobCallRecord[] = []
    return {
        record: calls,
        job: {
            id,
            teamId: 1,
            applicationId: opts.applicationId ?? 'app-1',
            revisionId: 'rev-1',
            queueName: 'default',
            scheduled: DateTime.now(),
            created: DateTime.now(),
            transitionCount: 0,
            state: opts.state ?? null,
            async ack() {
                calls.push({ method: 'ack' })
            },
            async fail() {
                calls.push({ method: 'fail' })
            },
            async reschedule(input?: unknown) {
                calls.push({ method: 'reschedule', args: input })
            },
            async cancel() {
                calls.push({ method: 'cancel' })
            },
            async heartbeat() {
                calls.push({ method: 'heartbeat' })
            },
        },
    }
}

function scriptedExecutor(outputs: ExecutorTurnOutput[]): SessionExecutor {
    let i = 0
    return {
        async runTurn() {
            const next = outputs[i]
            i += 1
            if (!next) {
                throw new Error('scriptedExecutor: no more outputs')
            }
            return next
        },
    }
}

function captureEvents(bus: InMemorySessionBus, sessionId: string): SessionEvent[] {
    const received: SessionEvent[] = []
    void bus.subscribeEvents(sessionId, (e) => received.push(e))
    return received
}

describe('RunnerWorker.processJob', () => {
    it('completion: publishes session_completed and acks the job', async () => {
        const bus = new InMemorySessionBus()
        const events = captureEvents(bus, 's-complete')
        const worker = new RunnerWorker({
            pool: { dbUrl: 'postgres://unused' },
            queueName: 'default',
            executor: scriptedExecutor([
                {
                    kind: 'completed',
                    message: { role: 'assistant', content: 'done', at: '2026-05-14T00:00:00Z' },
                    output: { answer: 42 },
                },
            ]),
            bus,
            loadSecrets: async () => ({}),
            logProducer: new FakeLogProducer(),
            heartbeatIntervalMs: 1_000_000,
        })

        const { record, job } = makeJob('s-complete', {})
        await (worker as unknown as { processJob(j: typeof job): Promise<void> }).processJob(job)

        expect(record.map((r) => r.method)).toEqual(['ack'])
        expect(events.map((e) => e.type)).toEqual(['turn_started', 'turn_completed', 'session_completed'])

        await bus.disconnect()
    })

    it('failed: publishes session_failed and fails the job', async () => {
        const bus = new InMemorySessionBus()
        const events = captureEvents(bus, 's-fail')
        const worker = new RunnerWorker({
            pool: { dbUrl: 'postgres://unused' },
            queueName: 'default',
            executor: scriptedExecutor([{ kind: 'failed', error: 'boom' }]),
            bus,
            loadSecrets: async () => ({}),
            logProducer: new FakeLogProducer(),
            heartbeatIntervalMs: 1_000_000,
        })
        const { record, job } = makeJob('s-fail', {})
        await (worker as unknown as { processJob(j: typeof job): Promise<void> }).processJob(job)

        expect(record.map((r) => r.method)).toEqual(['fail'])
        const failed = events.find(
            (e): e is Extract<SessionEvent, { type: 'session_failed' }> => e.type === 'session_failed'
        )
        expect(failed?.error).toBe('boom')

        await bus.disconnect()
    })

    it('cancelled: publishes a terminal session_failed and cancels the job', async () => {
        const bus = new InMemorySessionBus()
        const events = captureEvents(bus, 's-cancel')
        const worker = new RunnerWorker({
            pool: { dbUrl: 'postgres://unused' },
            queueName: 'default',
            executor: scriptedExecutor([{ kind: 'cancelled' }]),
            bus,
            loadSecrets: async () => ({}),
            logProducer: new FakeLogProducer(),
            heartbeatIntervalMs: 1_000_000,
        })
        const { record, job } = makeJob('s-cancel', {})
        await (worker as unknown as { processJob(j: typeof job): Promise<void> }).processJob(job)

        // The queue row settles as `canceled` (job.cancel), not failed.
        expect(record.map((r) => r.method)).toEqual(['cancel'])
        const failed = events.find(
            (e): e is Extract<SessionEvent, { type: 'session_failed' }> => e.type === 'session_failed'
        )
        expect(failed?.error).toBe('cancelled by client')

        await bus.disconnect()
    })

    it('tool_call: runs the tool natively and reschedules with updated state', async () => {
        const bus = new InMemorySessionBus()
        captureEvents(bus, 's-tool')
        const worker = new RunnerWorker({
            pool: { dbUrl: 'postgres://unused' },
            queueName: 'default',
            executor: scriptedExecutor([
                {
                    kind: 'tool_call',
                    message: { role: 'assistant', content: 'thinking', at: '2026-05-14T00:00:00.000Z' },
                    call: { id: 'meta.complete', args: { output: { ok: true } } },
                },
            ]),
            bus,
            loadSecrets: async () => ({}),
            logProducer: new FakeLogProducer(),
            heartbeatIntervalMs: 1_000_000,
        })
        const { record, job } = makeJob('s-tool', {})
        await (worker as unknown as { processJob(j: typeof job): Promise<void> }).processJob(job)

        const reschedule = record.find((r) => r.method === 'reschedule')
        expect(reschedule).not.toBeUndefined()
        const args = (reschedule!.args as { state: Buffer }).state
        const state = deserializeState(args)
        // Two messages: the assistant's "thinking" + the system tool result.
        expect(state.messages).toHaveLength(2)
        expect(state.messages[1].role).toBe('system')
        expect(state.turnCount).toBe(1)

        await bus.disconnect()
    })

    it('awaiting_input: reschedules with the current state and parks the job', async () => {
        const bus = new InMemorySessionBus()
        const worker = new RunnerWorker({
            pool: { dbUrl: 'postgres://unused' },
            queueName: 'default',
            executor: scriptedExecutor([
                {
                    kind: 'awaiting_input',
                    message: { role: 'assistant', content: 'awaiting' },
                    reason: 'needs more info',
                },
            ]),
            bus,
            loadSecrets: async () => ({}),
            logProducer: new FakeLogProducer(),
            heartbeatIntervalMs: 1_000_000,
        })
        const { record, job } = makeJob('s-wait', {})
        await (worker as unknown as { processJob(j: typeof job): Promise<void> }).processJob(job)

        const reschedule = record.find((r) => r.method === 'reschedule')
        expect(reschedule).not.toBeUndefined()
        await bus.disconnect()
    })

    it('flushes pending inputs into the turn and clears them in the persisted state', async () => {
        const bus = new InMemorySessionBus()
        const initialState = serializeState({
            messages: [],
            pendingInputs: [{ at: '2026-05-14T00:00:00.000Z', content: 'hello' }],
            initialInput: null,
            turnCount: 0,
        })

        let captured: { content: string }[] = []
        const worker = new RunnerWorker({
            pool: { dbUrl: 'postgres://unused' },
            queueName: 'default',
            executor: {
                async runTurn(input) {
                    captured = [...input.newInputs]
                    return {
                        kind: 'completed',
                        message: { role: 'assistant', content: 'ack' },
                        output: null,
                    }
                },
            },
            bus,
            loadSecrets: async () => ({}),
            logProducer: new FakeLogProducer(),
            heartbeatIntervalMs: 1_000_000,
        })

        const { job } = makeJob('s-flush', { state: initialState })
        await (worker as unknown as { processJob(j: typeof job): Promise<void> }).processJob(job)

        expect(captured).toEqual([{ content: 'hello', at: '2026-05-14T00:00:00.000Z' }])
        await bus.disconnect()
    })
})
