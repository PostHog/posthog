import { afterEach, describe, expect, it, vi } from 'vitest'

import { resolveProjectSecretKeyProjectId } from '@/hono/project-secret-key-project'
import { findPostHogPermissionError, formatPermissionErrorMessage } from '@/lib/errors'
import type { RequestProperties } from '@/lib/request-properties'

const props = { apiToken: 'phs_test', userHash: 'hash' } as RequestProperties

function makeCache(): { get: () => Promise<string | undefined>; set: (key: string, value: string) => Promise<void> } {
    let stored: string | undefined
    return {
        get: async () => stored,
        set: async (_key, value) => {
            stored = value
        },
    }
}

function stubApi(status: number, body: unknown): void {
    vi.stubGlobal(
        'fetch',
        vi.fn(
            async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
        )
    )
}

describe('resolveProjectSecretKeyProjectId', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('asks the API once for the project of a key, then answers from the cache', async () => {
        stubApi(200, { project_id: 42, is_limited: false, library_id: null })
        const cache = makeCache()

        expect(await resolveProjectSecretKeyProjectId(props, cache)).toBe('42')
        expect(await resolveProjectSecretKeyProjectId(props, cache)).toBe('42')

        const urls = vi
            .mocked(fetch)
            .mock.calls.map(([input]) => (input instanceof Request ? input.url : String(input)))
        expect(urls).toHaveLength(1)
        expect(urls[0]).toContain('/api/projects/@current/business_knowledge/access/')
    })

    it('tells a refused key where to create one that works', async () => {
        stubApi(403, { type: 'authentication_error', code: 'permission_denied', detail: 'Missing scope.' })

        const error = await resolveProjectSecretKeyProjectId(props, makeCache()).catch((e: Error) => e)

        const permissionError = findPostHogPermissionError(error)
        expect(permissionError && formatPermissionErrorMessage(permissionError)).toContain('Connect your agent')
    })
})
