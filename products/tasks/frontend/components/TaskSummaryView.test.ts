import { LogEntry } from '../lib/parse-logs'
import { extractConversationSummary } from './TaskSummaryView'

const entry = (overrides: Partial<LogEntry>): LogEntry => ({
    id: 'e-1',
    type: 'user',
    ...overrides,
})

describe('extractConversationSummary', () => {
    it('returns only user and agent entries with non-empty messages', () => {
        const entries: LogEntry[] = [
            entry({ id: 'u-1', type: 'user', message: 'hi' }),
            entry({ id: 'a-1', type: 'agent', message: 'hello!' }),
            entry({ id: 't-1', type: 'thinking', message: 'pondering' }),
            entry({ id: 'tool-1', type: 'tool', toolName: 'Read' }),
            entry({ id: 'c-1', type: 'console', message: 'log line' }),
            entry({ id: 's-1', type: 'system', message: 'system notice' }),
            entry({ id: 'r-1', type: 'raw', raw: 'unknown payload' }),
        ]
        const summary = extractConversationSummary(entries)
        expect(summary.map((e) => e.id)).toEqual(['u-1', 'a-1'])
    })

    it('drops entries with whitespace-only messages', () => {
        const entries: LogEntry[] = [
            entry({ id: 'u-1', type: 'user', message: '   \n  ' }),
            entry({ id: 'a-1', type: 'agent', message: 'real reply' }),
            entry({ id: 'u-2', type: 'user', message: '' }),
        ]
        const summary = extractConversationSummary(entries)
        expect(summary.map((e) => e.id)).toEqual(['a-1'])
    })

    it('preserves the order of qualifying entries', () => {
        const entries: LogEntry[] = [
            entry({ id: 'u-1', type: 'user', message: 'one' }),
            entry({ id: 'a-1', type: 'agent', message: 'two' }),
            entry({ id: 'u-2', type: 'user', message: 'three' }),
            entry({ id: 'a-2', type: 'agent', message: 'four' }),
        ]
        const summary = extractConversationSummary(entries)
        expect(summary.map((e) => e.message)).toEqual(['one', 'two', 'three', 'four'])
    })
})
