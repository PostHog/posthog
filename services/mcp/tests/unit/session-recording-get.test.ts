import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError } from '@/lib/errors'
import getSessionRecording from '@/tools/replay/getSessionRecording'
import type { Context } from '@/tools/types'

const recordingUrl = 'https://us.posthog.com/api/projects/42/session_recordings/session-123/'

function createContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request,
            getProjectBaseUrl: () => 'https://us.posthog.com/project/42',
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') },
    } as unknown as Context
}

function apiError(status: number, url = recordingUrl): PostHogApiError {
    return new PostHogApiError({ status, statusText: 'Not Found', body: '', url, method: 'GET' })
}

describe('session-recording-get', () => {
    const tool = getSessionRecording()

    it('preserves the generated tool schema and UI app metadata', () => {
        expect(tool.name).toBe('session-recording-get')
        expect(tool.schema.safeParse({ id: 'session-123' }).success).toBe(true)
        expect(tool._meta?.ui?.resourceUri).toBeTruthy()
    })

    it('returns recording metadata on a hit', async () => {
        const request = vi.fn().mockResolvedValue({ id: 'session-123', person: { properties: { email: 'private' } } })

        await expect(tool.handler(createContext(request), { id: 'session-123' })).resolves.toEqual({
            id: 'session-123',
            person: {},
            _posthogUrl: 'https://us.posthog.com/project/42/replay/session-123',
        })
        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/session_recordings/session-123/',
        })
    })

    it('treats a missing recording as a normal lookup result', async () => {
        const request = vi.fn().mockRejectedValue(apiError(404))

        await expect(tool.handler(createContext(request), { id: 'session-123' })).resolves.toEqual({
            found: false,
            id: 'session-123',
            reason: 'recording_not_found',
            message: 'No session recording is available for this ID in the active project.',
        })
    })

    it.each([
        ['permission failure', apiError(403)],
        ['server failure', apiError(503)],
        ['unrelated 404', apiError(404, 'https://us.posthog.com/api/projects/42/')],
    ])('still throws on %s', async (_reason, error) => {
        const request = vi.fn().mockRejectedValue(error)

        await expect(tool.handler(createContext(request), { id: 'session-123' })).rejects.toBe(error)
    })
})
