import { describe, expect, it, vi } from 'vitest'

import sessionRecordingConsoleLogs from '@/tools/replay/sessionRecordingConsoleLogs'
import type { Context } from '@/tools/types'

function createMockContext(executeMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            query: vi.fn().mockReturnValue({ execute: executeMock }),
            getProjectBaseUrl: () => 'https://us.posthog.com/project/42',
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('sessionRecordingConsoleLogs', () => {
    it('builds a session-scoped HogQL query and maps rows to log lines', async () => {
        const executeMock = vi.fn().mockResolvedValue({
            success: true,
            data: { results: [['2026-06-24T00:00:00Z', 'error', 'boom']] },
        })
        const context = createMockContext(executeMock)
        const tool = sessionRecordingConsoleLogs()

        const result = await tool.handler(context, { session_id: 'sess-abc' })

        const { queryBody } = executeMock.mock.calls[0]![0]
        expect(queryBody.kind).toBe('HogQLQuery')
        expect(queryBody.values).toEqual({ session_id: 'sess-abc' })
        // session id is passed as a placeholder, never interpolated into the SQL string
        expect(queryBody.query).toContain('log_source_id = {session_id}')
        expect(queryBody.query).not.toContain('sess-abc')
        expect(queryBody.query).toContain('FROM console_logs_log_entries')
        expect(queryBody.query).toContain('ORDER BY timestamp ASC')
        expect(queryBody.query).toContain('LIMIT 200')

        expect(result.results).toEqual([{ timestamp: '2026-06-24T00:00:00Z', level: 'error', message: 'boom' }])
        expect(result._posthogUrl).toBe('https://us.posthog.com/project/42/replay/sess-abc')
    })

    it('applies level, search, limit and order filters as placeholders', async () => {
        const executeMock = vi.fn().mockResolvedValue({ success: true, data: { results: [] } })
        const context = createMockContext(executeMock)
        const tool = sessionRecordingConsoleLogs()

        await tool.handler(context, {
            session_id: 'sess-abc',
            level: ['Error', 'WARN'],
            search: 'timeout',
            limit: 50,
            order: 'desc',
        })

        const { queryBody } = executeMock.mock.calls[0]![0]
        // levels are lowercased and matched case-insensitively
        expect(queryBody.values.levels).toEqual(['error', 'warn'])
        expect(queryBody.query).toContain('lower(level) IN {levels}')
        // search is wrapped in wildcards for an ILIKE substring match
        expect(queryBody.values.search).toBe('%timeout%')
        expect(queryBody.query).toContain('message ILIKE {search}')
        expect(queryBody.query).toContain('ORDER BY timestamp DESC')
        expect(queryBody.query).toContain('LIMIT 50')
    })

    it('throws when the query fails', async () => {
        const executeMock = vi.fn().mockResolvedValue({ success: false, error: { message: 'nope' } })
        const context = createMockContext(executeMock)
        const tool = sessionRecordingConsoleLogs()

        await expect(tool.handler(context, { session_id: 'sess-abc' })).rejects.toThrow('nope')
    })
})
