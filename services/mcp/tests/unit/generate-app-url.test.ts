import { describe, expect, it, vi } from 'vitest'

import { ToolInputValidationError } from '@/lib/errors'
import generateAppUrl, { generateAppUrlHandler } from '@/tools/links/generate-app-url'
import type { Context } from '@/tools/types'

function createMockContext(): Context {
    return {
        api: {
            getProjectBaseUrl: (projectId: string): string =>
                projectId === '@current' ? 'https://us.posthog.com' : `https://us.posthog.com/project/${projectId}`,
        },
        stateManager: {
            getProjectId: vi.fn(async () => '354703'),
        },
    } as unknown as Context
}

async function urlOf(result: Promise<{ url: string } | { availableUrls: string[] }>): Promise<string> {
    const resolved = await result
    if (!('url' in resolved)) {
        throw new Error('expected a url result, got the catalog')
    }
    return resolved.url
}

describe('generate-app-url', () => {
    const ctx = createMockContext()

    // The regression: a person UUID belongs under the plural /persons slug, not the singular /person.
    it('builds a person-by-UUID link with the plural /persons slug', async () => {
        const url = urlOf(
            generateAppUrlHandler(ctx, {
                url: '/persons/{uuid}',
                params: { uuid: '12857b3c-2916-536b-af70-1e43c442a942' },
            })
        )
        expect(await url).toBe('https://us.posthog.com/project/354703/persons/12857b3c-2916-536b-af70-1e43c442a942')
    })

    it('builds a person-by-distinct-id link with the singular /person slug', async () => {
        const url = urlOf(generateAppUrlHandler(ctx, { url: '/person/{id}', params: { id: 'pekerr@ou.org' } }))
        expect(await url).toBe('https://us.posthog.com/project/354703/person/pekerr%40ou.org')
    })

    it('builds a single session replay link', async () => {
        const url = urlOf(
            generateAppUrlHandler(ctx, { url: '/replay/{id}', params: { id: '019e83d3-d262-7543-a677-5ea82d8e785c' } })
        )
        expect(await url).toBe('https://us.posthog.com/project/354703/replay/019e83d3-d262-7543-a677-5ea82d8e785c')
    })

    it('builds a multi-param event link and URL-encodes values', async () => {
        const url = urlOf(
            generateAppUrlHandler(ctx, {
                url: '/events/{id}/{timestamp}',
                params: { id: 'evt_1', timestamp: '2026-06-01T15:48:00Z' },
            })
        )
        expect(await url).toBe('https://us.posthog.com/project/354703/events/evt_1/2026-06-01T15%3A48%3A00Z')
    })

    it('uses the bare host (no project prefix) for global-scope pages', async () => {
        const url = urlOf(generateAppUrlHandler(ctx, { url: '/instance/status', params: {} }))
        expect(await url).toBe('https://us.posthog.com/instance/status')
    })

    // A single-exec client (Claude Code, Cowork, ...) never receives the catalog in a schema, so
    // calling with no `url` must return the catalog in-band rather than reject as a missing parameter.
    it('returns the catalog when called with no url', async () => {
        const result = await generateAppUrlHandler(ctx, { params: {} })
        expect(result).not.toHaveProperty('url')
        if ('availableUrls' in result) {
            expect(result.availableUrls).toContain('/persons/{uuid}')
            expect(result.availableUrls.length).toBeGreaterThan(1)
        } else {
            throw new Error('expected a catalog result')
        }
    })

    // Reclassified from a plain Error so the error tracker does not mint an issue per agent slip-up,
    // and value-free so the raw url is never persisted to telemetry.
    it('throws a recoverable validation error on an unknown url template', async () => {
        await expect(generateAppUrlHandler(ctx, { url: '/definitely/not/a/template', params: {} })).rejects.toThrow(
            ToolInputValidationError
        )
    })

    it('throws when a required param is missing', async () => {
        await expect(generateAppUrlHandler(ctx, { url: '/persons/{uuid}', params: {} })).rejects.toThrow(
            /must be exactly \[uuid\]/
        )
    })

    // The mismatch message is persisted verbatim to value-free telemetry, so it must report the count of
    // unexpected keys, never the caller-chosen key names from the open `params` record.
    it('reports an unexpected param by count without echoing the caller-chosen key', async () => {
        const error = await generateAppUrlHandler(ctx, {
            url: '/persons/{uuid}',
            params: { uuid: 'x', extra: 'y' },
        }).catch((e: unknown) => e)
        expect(error).toBeInstanceOf(ToolInputValidationError)
        expect((error as ToolInputValidationError).message).toContain('unexpected keys: 1')
        expect((error as ToolInputValidationError).message).not.toContain('extra')
    })

    it('exposes the tool name and accepts a valid payload', () => {
        const tool = generateAppUrl()
        expect(tool.name).toBe('generate-app-url')
        expect(tool.schema.safeParse({ url: '/persons/{uuid}', params: { uuid: 'x' } }).success).toBe(true)
        // `url` is optional: a no-url call reaches the handler (the discovery path) instead of being
        // rejected as a missing parameter before it runs.
        expect(tool.schema.safeParse({}).success).toBe(true)
    })
})
