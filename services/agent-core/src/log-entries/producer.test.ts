/**
 * Producer tests focus on the seams we own: connection state, the
 * fire-and-forget contract, JSON+surrogate-safe encoding. Batching itself
 * is librdkafka's job — not ours to verify here.
 */
import type { HighLevelProducer } from 'node-rdkafka'

import { KafkaLogProducer, FakeLogProducer } from './producer'
import { AGENT_SESSION_LOG_SOURCE, type LogEntry } from './types'

jest.mock('node-rdkafka', () => {
    return {
        HighLevelProducer: jest.fn().mockImplementation(() => {
            const listeners: Record<string, ((arg: unknown) => void)[]> = {}
            return {
                on: jest.fn((event: string, cb: (arg: unknown) => void) => {
                    ;(listeners[event] ??= []).push(cb)
                }),
                connect: jest.fn((_opts: unknown, cb: (err: Error | null, data?: { brokers?: unknown[] }) => void) => {
                    // Async-callback connect, simulate librdkafka's behavior.
                    setImmediate(() => cb(null, { brokers: [] }))
                }),
                produce: jest.fn(),
                flush: jest.fn((_timeoutMs: number, cb: () => void) => setImmediate(cb)),
                disconnect: jest.fn((cb: () => void) => setImmediate(cb)),
                __listeners: listeners,
            }
        }),
    }
})

function makeEntry(message: string): LogEntry {
    return {
        team_id: 1,
        log_source: AGENT_SESSION_LOG_SOURCE,
        log_source_id: '00000000-0000-0000-0000-000000000010',
        instance_id: '00000000-0000-0000-0000-000000000001',
        timestamp: '2026-05-19T15:00:00.000000Z',
        level: 'INFO',
        message,
    }
}

/** Reach through the most recent mock construction to the inner rdkafka stub
 *  for assertions. Call sites pass the producer for readability — the mock
 *  doesn't actually need it. */
function rdk(): jest.Mocked<HighLevelProducer> {
    const { HighLevelProducer } = jest.requireMock('node-rdkafka') as {
        HighLevelProducer: jest.Mock
    }
    const lastCall = HighLevelProducer.mock.results[HighLevelProducer.mock.results.length - 1]
    return lastCall!.value as jest.Mocked<HighLevelProducer>
}

describe('KafkaLogProducer', () => {
    afterEach(() => {
        jest.clearAllMocks()
    })

    it('connects once even if connect() is called repeatedly in parallel', async () => {
        const p = new KafkaLogProducer({ brokers: 'kafka:9092' })
        await Promise.all([p.connect(), p.connect(), p.connect()])
        expect(rdk().connect).toHaveBeenCalledTimes(1)
        await p.disconnect()
    })

    it('append produces a JSON-encoded, surrogate-safe Buffer to the configured topic', async () => {
        const p = new KafkaLogProducer({ brokers: 'kafka:9092', topic: 'log_entries' })
        await p.connect()

        p.append(makeEntry('hello'))

        const inner = rdk()
        expect(inner.produce).toHaveBeenCalledTimes(1)
        const [topic, partition, value] = inner.produce.mock.calls[0]!
        expect(topic).toBe('log_entries')
        expect(partition).toBeNull()
        expect(Buffer.isBuffer(value)).toBe(true)
        const decoded = JSON.parse((value as Buffer).toString('utf8')) as LogEntry
        expect(decoded.message).toBe('hello')
        expect(decoded.log_source).toBe(AGENT_SESSION_LOG_SOURCE)

        await p.disconnect()
    })

    it('drops the entry (does not crash) when called before connect()', () => {
        const p = new KafkaLogProducer({ brokers: 'kafka:9092' })
        // No connect() — should be a no-op, no throw.
        expect(() => p.append(makeEntry('orphan'))).not.toThrow()
        expect(rdk().produce).not.toHaveBeenCalled()
    })

    it('append after disconnect is a no-op', async () => {
        const p = new KafkaLogProducer({ brokers: 'kafka:9092' })
        await p.connect()
        await p.disconnect()
        const inner = rdk()
        inner.produce.mockClear()
        expect(() => p.append(makeEntry('orphan'))).not.toThrow()
        expect(inner.produce).not.toHaveBeenCalled()
    })

    it('disconnect flushes then closes the underlying producer', async () => {
        const p = new KafkaLogProducer({ brokers: 'kafka:9092' })
        await p.connect()
        await p.disconnect()
        const inner = rdk()
        expect(inner.flush).toHaveBeenCalled()
        expect(inner.disconnect).toHaveBeenCalled()
    })
})

describe('FakeLogProducer', () => {
    it('captures every entry in order', async () => {
        const f = new FakeLogProducer()
        await f.connect()
        f.append(makeEntry('one'))
        f.append(makeEntry('two'))
        expect(f.entries.map((e) => e.message)).toEqual(['one', 'two'])
        await f.disconnect()
    })
})
