import type { SessionEvent } from '../pubsub/types'
import { FakeLogProducer } from './producer'
import { createSessionLogger, formatEvent } from './session-logger'
import { AGENT_SESSION_LOG_SOURCE } from './types'

const teamId = 42
const applicationId = '00000000-0000-0000-0000-000000000010'
const sessionId = '00000000-0000-0000-0000-000000000001'
const fixedAt = '2026-05-19T15:00:00.123Z'

describe('createSessionLogger', () => {
    it('writes a LogEntry per SessionEvent with the expected line shape', () => {
        const producer = new FakeLogProducer()
        const now = (): Date => new Date('2026-05-19T15:00:00.000Z')
        const logger = createSessionLogger({ teamId, applicationId, sessionId, producer, now })

        const events: SessionEvent[] = [
            { type: 'turn_started', at: fixedAt },
            { type: 'message', at: fixedAt, role: 'user', content: 'hi' },
            { type: 'tool_call', at: fixedAt, tool: 'http.fetch@v1.get', args: { url: 'https://example.com' } },
            { type: 'tool_result', at: fixedAt, tool: 'http.fetch@v1.get', ok: true, result: { status: 200 } },
            { type: 'tool_result', at: fixedAt, tool: 'broken', ok: false, error: 'timeout' },
            { type: 'session_completed', at: fixedAt, output: 'done' },
            { type: 'session_failed', at: fixedAt, error: 'boom' },
        ]
        for (const event of events) {
            logger.appendEvent(event)
        }

        expect(producer.entries.map((e) => e.message)).toEqual([
            '[event] turn_started',
            '[chat] user: hi',
            '[tool] http.fetch@v1.get args={"url":"https://example.com"}',
            '[tool] http.fetch@v1.get → ok result={"status":200}',
            '[error] broken failed: timeout',
            '[event] session_completed',
            '[error] session_failed: boom',
        ])

        expect(producer.entries.map((e) => e.level)).toEqual(['INFO', 'INFO', 'INFO', 'INFO', 'ERROR', 'INFO', 'ERROR'])

        expect(producer.entries[0]).toMatchObject({
            team_id: teamId,
            log_source: AGENT_SESSION_LOG_SOURCE,
            log_source_id: applicationId,
            instance_id: sessionId,
            timestamp: '2026-05-19 15:00:00.123000',
        })
    })

    it('appendLog defaults to INFO/[meta] and supports ERROR/[error]', () => {
        const producer = new FakeLogProducer()
        const now = (): Date => new Date('2026-05-19T15:00:00.000Z')
        const logger = createSessionLogger({ teamId, applicationId, sessionId, producer, now })

        logger.appendLog({ message: 'session_init' })
        logger.appendLog({ level: 'ERROR', message: 'anthropic 429 rate_limit' })

        expect(producer.entries.map((e) => [e.level, e.message])).toEqual([
            ['INFO', '[meta] session_init'],
            ['ERROR', '[error] anthropic 429 rate_limit'],
        ])
    })

    it('uses event.at when available; otherwise stamps with now() at microsecond precision', () => {
        const producer = new FakeLogProducer()
        const now = (): Date => new Date('2026-05-19T15:00:00.456Z')
        const logger = createSessionLogger({ teamId, applicationId, sessionId, producer, now })

        logger.appendEvent({ type: 'turn_started', at: '2026-05-19T15:00:00.999Z' })
        logger.appendLog({ message: 'free-form' })

        // Both converted to CH-friendly `YYYY-MM-DD HH:MM:SS.ffffff` shape.
        expect(producer.entries[0]!.timestamp).toBe('2026-05-19 15:00:00.999000')
        expect(producer.entries[1]!.timestamp).toBe('2026-05-19 15:00:00.456000')
    })

    it('drops message_delta events without persisting them (ephemeral)', () => {
        const producer = new FakeLogProducer()
        const logger = createSessionLogger({ teamId, applicationId, sessionId, producer })
        logger.appendEvent({ type: 'message_delta', at: fixedAt, text: 'tok' })
        logger.appendEvent({ type: 'message_delta', at: fixedAt, text: 'en' })
        // The durable record is the final message — deltas leave no rows.
        logger.appendEvent({ type: 'message', at: fixedAt, role: 'assistant', content: 'token' })
        expect(producer.entries.map((e) => e.message)).toEqual(['[chat] assistant: token'])
    })

    it('drops writes silently when applicationId is null (orphan jobs)', () => {
        const producer = new FakeLogProducer()
        const logger = createSessionLogger({
            teamId,
            applicationId: null,
            sessionId,
            producer,
        })
        logger.appendEvent({ type: 'turn_started', at: fixedAt })
        logger.appendLog({ message: 'should-not-appear' })
        expect(producer.entries).toEqual([])
    })

    it('collapses newlines in assistant content to keep messages single-line', () => {
        const producer = new FakeLogProducer()
        const logger = createSessionLogger({ teamId, applicationId, sessionId, producer })
        logger.appendEvent({
            type: 'message',
            at: fixedAt,
            role: 'assistant',
            content: 'line one\n\n  line two',
        })
        expect(producer.entries[0]!.message).toBe('[chat] assistant: line one line two')
    })

    it('truncates long tool args / results to keep CH rows reasonable', () => {
        const producer = new FakeLogProducer()
        const logger = createSessionLogger({ teamId, applicationId, sessionId, producer })
        const big = 'x'.repeat(500)
        logger.appendEvent({ type: 'tool_call', at: fixedAt, tool: 't', args: big })
        const msg = producer.entries[0]!.message
        expect(msg.length).toBeLessThan(380)
        expect(msg.endsWith('…')).toBe(true)
    })
})

describe('formatEvent', () => {
    it('maps every SessionEvent variant', () => {
        // Smoke — making sure adding a new SessionEvent variant trips us early.
        const checks: SessionEvent[] = [
            { type: 'turn_started', at: fixedAt },
            { type: 'turn_completed', at: fixedAt },
            { type: 'message', at: fixedAt, role: 'system', content: 'ready' },
            { type: 'message_delta', at: fixedAt, text: 'tok' },
            { type: 'tool_call', at: fixedAt, tool: 'x' },
            { type: 'tool_result', at: fixedAt, tool: 'x', ok: true },
            { type: 'status', at: fixedAt, text: 'fetching…' },
            { type: 'awaiting_input', at: fixedAt, prompt: 'what next?' },
            { type: 'session_completed', at: fixedAt, output: null },
            { type: 'session_failed', at: fixedAt, error: 'e' },
        ]
        for (const event of checks) {
            const [level, message] = formatEvent(event)
            expect(['INFO', 'ERROR']).toContain(level)
            expect(message).toMatch(/^\[(meta|chat|tool|event|error)\] /)
        }
    })
})
