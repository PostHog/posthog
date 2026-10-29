import { describe, expect, it, vi } from 'vitest'

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

describe('generate-app-url', () => {
    const ctx = createMockContext()

    // The regression: a person UUID belongs under the plural /persons slug, not the singular /person.
    it('builds a person-by-UUID link with the plural /persons slug', async () => {
        const result = await generateAppUrlHandler(ctx, {
            url: '/persons/{uuid}',
            params: { uuid: '12857b3c-2916-536b-af70-1e43c442a942' },
        })
        expect(result.url).toBe('https://us.posthog.com/project/354703/persons/12857b3c-2916-536b-af70-1e43c442a942')
    })

    it('builds a person-by-distinct-id link with the singular /person slug', async () => {
        const result = await generateAppUrlHandler(ctx, {
            url: '/person/{id}',
            params: { id: 'pekerr@ou.org' },
        })
        expect(result.url).toBe('https://us.posthog.com/project/354703/person/pekerr%40ou.org')
    })

    it('builds a single session replay link', async () => {
        const result = await generateAppUrlHandler(ctx, {
            url: '/replay/{id}',
            params: { id: '019e83d3-d262-7543-a677-5ea82d8e785c' },
        })
        expect(result.url).toBe('https://us.posthog.com/project/354703/replay/019e83d3-d262-7543-a677-5ea82d8e785c')
    })

    it('builds a multi-param event link and URL-encodes values', async () => {
        const result = await generateAppUrlHandler(ctx, {
            url: '/events/{id}/{timestamp}',
            params: { id: 'evt_1', timestamp: '2026-06-01T15:48:00Z' },
        })
        expect(result.url).toBe('https://us.posthog.com/project/354703/events/evt_1/2026-06-01T15%3A48%3A00Z')
    })

    it.each([
        ['/error_tracking/{id}', { id: 'issue-1' }, '/error-tracking/issue-1'],
        ['/error-tracking/{id}', { id: 'issue-1' }, '/error-tracking/issue-1'],
        ['/error_tracking/fingerprint/{fingerprint}', { fingerprint: 'fp' }, '/error-tracking/fingerprint/fp'],
        ['/error_tracking', {}, '/error-tracking'],
        ['/feature_flags/{id}', { id: '42' }, '/feature-flags/42'],
        ['/feature-flags/{id}', { id: '42' }, '/feature-flags/42'],
        ['/feature_flags', {}, '/feature-flags'],
        [
            '/ai-evals/evaluations/offline/experiments?tab=datasets',
            {},
            '/ai-evals/evaluations/offline/experiments?tab=datasets',
        ],
        ['/ai-evals/evaluations/offline/experiments', {}, '/ai-evals/evaluations/offline/experiments'],
        [
            '/ai-evals/evaluations/offline/datasets/{id}',
            { id: 'example-dataset' },
            '/ai-evals/evaluations/offline/datasets/example-dataset',
        ],
    ])('builds the canonical app link for the template %s', async (url, params, path) => {
        const result = await generateAppUrlHandler(ctx, { url, params })
        expect(result.url).toBe(`https://us.posthog.com/project/354703${path}`)
    })

    it('uses the bare host (no project prefix) for global-scope pages', async () => {
        const result = await generateAppUrlHandler(ctx, { url: '/instance/status', params: {} })
        expect(result.url).toBe('https://us.posthog.com/instance/status')
    })

    it('throws on an unknown url template', async () => {
        await expect(generateAppUrlHandler(ctx, { url: '/definitely/not/a/template', params: {} })).rejects.toThrow(
            /Unknown url "\/definitely\/not\/a\/template"/
        )
    })

    it('throws when a required param is missing', async () => {
        await expect(generateAppUrlHandler(ctx, { url: '/persons/{uuid}', params: {} })).rejects.toThrow(
            /must be exactly \[uuid\]/
        )
    })

    it('throws on an unexpected param', async () => {
        await expect(
            generateAppUrlHandler(ctx, { url: '/persons/{uuid}', params: { uuid: 'x', extra: 'y' } })
        ).rejects.toThrow(/unexpected: extra/)
    })

    it('exposes the tool name and accepts a valid payload', () => {
        const tool = generateAppUrl()
        expect(tool.name).toBe('generate-app-url')
        expect(tool.schema.safeParse({ url: '/persons/{uuid}', params: { uuid: 'x' } }).success).toBe(true)
    })
})
