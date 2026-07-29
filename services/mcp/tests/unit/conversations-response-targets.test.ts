import { describe, expect, it, vi } from 'vitest'

import {
    getResponseTargetsTool,
    normalizeResponseTargetGroups,
    updateResponseTargetsTool,
    validateResponseTargetGroups,
} from '@/tools/conversations/responseTargets'
import type { Context } from '@/tools/types'

const LADDER = [
    { label: 'VIPs', tags: ['vip'] },
    { label: 'Everyone else', tags: ['plan_free', 'plan_paid'] },
]

function mockContext(options: {
    conversationsSettings?: Record<string, unknown> | null
    onPatch?: (body: unknown) => unknown
}): Context {
    const project = { id: 123, conversations_settings: options.conversationsSettings ?? null }
    return {
        stateManager: { getProjectId: vi.fn().mockResolvedValue('123') },
        api: {
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/123'),
            projects: () => ({
                get: vi.fn().mockResolvedValue({ success: true, data: project }),
                updateConversationsResponseTargetGroups: vi.fn().mockImplementation(async ({ groups }) => ({
                    success: true,
                    data: options.onPatch
                        ? options.onPatch(groups)
                        : { ...project, conversations_settings: { response_target_groups: groups } },
                })),
            }),
        },
    } as unknown as Context
}

describe('normalizeResponseTargetGroups', () => {
    it('returns a clean copy of a stored ladder', () => {
        expect(normalizeResponseTargetGroups(LADDER)).toEqual(LADDER)
    })

    it('returns null for absent or malformed values', () => {
        expect(normalizeResponseTargetGroups(undefined)).toBeNull()
        expect(normalizeResponseTargetGroups(null)).toBeNull()
        expect(normalizeResponseTargetGroups('garbage')).toBeNull()
        expect(normalizeResponseTargetGroups([{ nope: true }])).toBeNull()
        expect(normalizeResponseTargetGroups([])).toBeNull()
        // duplicate labels and a tag in two groups read as malformed,
        // matching the backend's fallback
        expect(
            normalizeResponseTargetGroups([
                { label: 'A', tags: ['x'] },
                { label: 'A', tags: ['y'] },
            ])
        ).toBeNull()
        expect(
            normalizeResponseTargetGroups([
                { label: 'A', tags: ['vip'] },
                { label: 'B', tags: ['vip', 'y'] },
            ])
        ).toBeNull()
    })
})

describe('validateResponseTargetGroups', () => {
    it('accepts a well-formed ladder', () => {
        expect(() => validateResponseTargetGroups(LADDER)).not.toThrow()
    })

    it('rejects duplicate labels', () => {
        expect(() =>
            validateResponseTargetGroups([
                { label: 'A', tags: ['x'] },
                { label: 'A', tags: ['y'] },
            ])
        ).toThrow(/duplicate group label/i)
    })

    it('rejects a tag appearing in two groups', () => {
        expect(() =>
            validateResponseTargetGroups([
                { label: 'A', tags: ['vip'] },
                { label: 'B', tags: ['vip'] },
            ])
        ).toThrow(/more than one group/i)
    })
})

describe('conversations-response-targets-get', () => {
    it('reports the saved ladder when customized', async () => {
        const context = mockContext({ conversationsSettings: { response_target_groups: LADDER } })
        const result = await getResponseTargetsTool().handler(context, {})
        expect(result).toMatchObject({ customized: true, groups: LADDER })
        expect(result.settings_url).toContain('/support/settings')
    })

    it('reports uncustomized teams as following the examples', async () => {
        const context = mockContext({ conversationsSettings: { widget_enabled: true } })
        const result = await getResponseTargetsTool().handler(context, {})
        expect(result).toMatchObject({ customized: false, groups: null })
        expect(result.message).toMatch(/example/i)
    })
})

describe('conversations-response-targets-update', () => {
    it('previews without saving when confirm is omitted', async () => {
        const context = mockContext({ conversationsSettings: null })
        const patch = vi.fn()
        context.api.projects = () =>
            ({
                get: vi.fn().mockResolvedValue({ success: true, data: { conversations_settings: null } }),
                updateConversationsResponseTargetGroups: patch,
            }) as any
        const result = await updateResponseTargetsTool().handler(context, { groups: LADDER })
        expect(result.applied).toBe(false)
        expect(result.groups).toEqual(LADDER)
        expect(patch).not.toHaveBeenCalled()
    })

    it('saves when confirm is true', async () => {
        const context = mockContext({ conversationsSettings: null })
        const result = await updateResponseTargetsTool().handler(context, { groups: LADDER, confirm: true })
        expect(result.applied).toBe(true)
        expect(result.groups).toEqual(LADDER)
    })

    it('skips the read and PATCHes directly on a confirmed write', async () => {
        const get = vi.fn()
        const context = mockContext({ conversationsSettings: null })
        const inner = context.api.projects()
        context.api.projects = () => ({ ...inner, get }) as any
        const result = await updateResponseTargetsTool().handler(context, { groups: LADDER, confirm: true })
        expect(result.applied).toBe(true)
        expect(get).not.toHaveBeenCalled()
    })

    it('previews a reset as a no-op when the team already follows the examples', async () => {
        const context = mockContext({ conversationsSettings: null })
        const result = await updateResponseTargetsTool().handler(context, { groups: null })
        expect(result.applied).toBe(false)
        expect(result.message).toMatch(/no-op/i)
    })

    it('previews a reset as discarding the ladder only when one exists', async () => {
        const context = mockContext({ conversationsSettings: { response_target_groups: LADDER } })
        const result = await updateResponseTargetsTool().handler(context, { groups: null })
        expect(result.applied).toBe(false)
        expect(result.message).toMatch(/discarding its custom ladder/i)
    })

    it('resets to the examples with groups null', async () => {
        const context = mockContext({ conversationsSettings: { response_target_groups: LADDER } })
        const result = await updateResponseTargetsTool().handler(context, { groups: null, confirm: true })
        expect(result.applied).toBe(true)
        expect(result.groups).toBeNull()
        expect(result.message).toMatch(/example/i)
    })

    it('fails fast on a tag in two groups without calling the API', async () => {
        const context = mockContext({ conversationsSettings: null })
        await expect(
            updateResponseTargetsTool().handler(context, {
                groups: [
                    { label: 'A', tags: ['vip'] },
                    { label: 'B', tags: ['vip'] },
                ],
                confirm: true,
            })
        ).rejects.toThrow(/more than one group/i)
    })
})
