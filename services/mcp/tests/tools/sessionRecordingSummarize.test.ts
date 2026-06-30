import { describe, expect, it } from 'vitest'

import sessionRecordingSummarize from '@/tools/replay/sessionRecordingSummarize'
import type { Context } from '@/tools/types'

type Emit = (event: string, data: unknown) => void
type SseDriver = (emit: Emit) => void | Promise<void>

/** Minimal Context whose requestSSE is driven by `driver` — it emits SSE events, then may throw. */
function makeContext(driver: SseDriver): Context {
    return {
        api: {
            requestSSE: async (opts: { onEvent: Emit }) => {
                await driver(opts.onEvent)
            },
            getProjectBaseUrl: () => 'https://us.posthog.com/project/1',
        },
        stateManager: {
            getProjectId: async () => '1',
        },
    } as unknown as Context
}

const tool = sessionRecordingSummarize()

describe('session-recording-summarize handler', () => {
    it('keeps completed summaries and marks the rest incomplete when the stream is cut short', async () => {
        const context = makeContext((emit) => {
            emit('summary', { session_id: 's1', summary: { outcome: 'good' } })
            throw new Error('SSE stream timed out after 600000ms')
        })

        const result = (await tool.handler(context, { session_ids: ['s1', 's2', 's3'] })) as Record<string, any>

        expect(result.s1).toEqual({ outcome: 'good' })
        expect(result.s2.error).toBe('incomplete')
        expect(result.s3.error).toBe('incomplete')
        expect(result._posthogUrl).toContain('/replay')
    })

    it('rethrows when the stream fails before producing anything (auth / validation / server error)', async () => {
        const context = makeContext(() => {
            throw new Error('SSE request failed: 403 permission_denied')
        })

        await expect(tool.handler(context, { session_ids: ['s1', 's2'] })).rejects.toThrow('403')
    })

    it('returns partial results when the stream ends without a done event', async () => {
        const context = makeContext((emit) => {
            emit('summary', { session_id: 's1', summary: { outcome: 'good' } })
            emit('summary', { session_id: 's2', summary: { outcome: 'bad' } })
            // stream ends cleanly, no `done` event
        })

        const result = (await tool.handler(context, { session_ids: ['s1', 's2'] })) as Record<string, any>

        expect(result.s1).toEqual({ outcome: 'good' })
        expect(result.s2).toEqual({ outcome: 'bad' })
    })

    it('preserves real per-session errors instead of overwriting them with incomplete', async () => {
        const context = makeContext((emit) => {
            emit('summary', { session_id: 's1', summary: { outcome: 'good' } })
            emit('error', { session_id: 's2', error: 'no_events_or_too_short', error_message: 'too short' })
            throw new Error('SSE stream timed out after 600000ms')
        })

        const result = (await tool.handler(context, { session_ids: ['s1', 's2', 's3'] })) as Record<string, any>

        expect(result.s2.error).toBe('no_events_or_too_short')
        expect(result.s3.error).toBe('incomplete')
    })

    it('returns every summary with no incomplete markers on a fully completed batch', async () => {
        const context = makeContext((emit) => {
            emit('summary', { session_id: 's1', summary: { outcome: 'good' } })
            emit('summary', { session_id: 's2', summary: { outcome: 'bad' } })
            emit('done', { completed: ['s1', 's2'], failed: [] })
        })

        const result = (await tool.handler(context, { session_ids: ['s1', 's2'] })) as Record<string, any>

        expect(result.s1).toEqual({ outcome: 'good' })
        expect(result.s2).toEqual({ outcome: 'bad' })
    })
})
