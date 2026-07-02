import { describe, expect, it, vi } from 'vitest'

import { isToolCallPayload, type ToolResultPayload } from '@/lib/build-tool-result'
import { PostHogApiError } from '@/lib/errors'
import sessionRecordingGet from '@/tools/replay/sessionRecordingGet'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

function apiError(status: number): PostHogApiError {
    return new PostHogApiError({
        status,
        statusText: status === 404 ? 'Not Found' : 'Server Error',
        body: status === 404 ? 'Recording not found' : 'boom',
        url: '/api/projects/42/session_recordings/sess-1/',
        method: 'GET',
    })
}

describe('session-recording-get wrapper', () => {
    it('returns a structured not-found result instead of an error on 404', async () => {
        const requestMock = vi.fn().mockRejectedValue(apiError(404))
        const context = createMockContext(requestMock)

        const result = (await sessionRecordingGet().handler(context, { id: 'sess-1' })) as ToolResultPayload

        // A pre-built payload so the session-recording UI app is not rendered against a
        // recording that does not exist.
        expect(isToolCallPayload(result)).toBe(true)
        expect(result.structuredContent).toBeUndefined()

        const text = result.content[0]!.text
        expect(text).toContain('exists')
        expect(text).toContain('false')
        expect(text).toContain('not_found')
        expect(text).toContain('sess-1')
    })

    it('passes through a found recording with its PostHog URL', async () => {
        const recording = { id: 'sess-1', duration: 42 }
        const requestMock = vi.fn().mockResolvedValue(recording)
        const context = createMockContext(requestMock)

        const result = (await sessionRecordingGet().handler(context, { id: 'sess-1' })) as Record<string, unknown>

        expect(isToolCallPayload(result)).toBe(false)
        expect(result.id).toBe('sess-1')
        expect(result._posthogUrl).toBe('https://us.posthog.com/project/42/replay/sess-1')
    })

    it('re-throws non-404 API errors so the executor still captures them', async () => {
        const requestMock = vi.fn().mockRejectedValue(apiError(500))
        const context = createMockContext(requestMock)

        await expect(sessionRecordingGet().handler(context, { id: 'sess-1' })).rejects.toThrow(PostHogApiError)
    })
})
