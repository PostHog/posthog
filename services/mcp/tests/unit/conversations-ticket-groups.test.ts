import { describe, expect, it, vi } from 'vitest'

import {
    type TicketGroup,
    getTicketGroupsTool,
    normalizeTicketGroups,
    updateTicketGroupsTool,
    validateTicketGroups,
} from '@/tools/conversations/ticketGroups'
import type { Context } from '@/tools/types'

const GROUPS: TicketGroup[] = [
    { label: 'VIPs', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['vip'] }] },
    {
        label: 'Recent email',
        filters: [
            { type: 'ticket_property', key: 'channel_source', operator: 'in', value: ['email'] },
            { type: 'ticket_property', key: 'created_at', operator: 'date_after', value: '-3d' },
        ],
    },
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
                updateConversationsTicketGroups: vi.fn().mockImplementation(async ({ groups }) => ({
                    success: true,
                    data: options.onPatch
                        ? options.onPatch(groups)
                        : { ...project, conversations_settings: { ticket_groups: groups } },
                })),
            }),
        },
    } as unknown as Context
}

describe('normalizeTicketGroups', () => {
    it('returns a clean copy of stored groups', () => {
        expect(normalizeTicketGroups(GROUPS)).toEqual(GROUPS)
    })

    it('accepts every filter shape, including valueless is_set/is_not_set and empty filter lists', () => {
        const groups = [
            {
                label: 'Everything',
                filters: [
                    { type: 'ticket_tags', operator: 'any_of', value: ['vip'] },
                    { type: 'ticket_property', key: 'status', operator: 'in', value: ['open'] },
                    { type: 'ticket_property', key: 'email_from', operator: 'icontains', value: '@bigcorp.com' },
                    { type: 'ticket_property', key: 'sla_due_at', operator: 'is_set' },
                    { type: 'ticket_property', key: 'created_at', operator: 'date_before', value: '-1mStart' },
                ],
            },
            { label: 'Placeholder', filters: [] },
        ]
        expect(normalizeTicketGroups(groups)).toEqual(groups)
    })

    it('returns null for absent or malformed values', () => {
        expect(normalizeTicketGroups(undefined)).toBeNull()
        expect(normalizeTicketGroups(null)).toBeNull()
        expect(normalizeTicketGroups('garbage')).toBeNull()
        expect(normalizeTicketGroups([{ nope: true }])).toBeNull()
        expect(normalizeTicketGroups([])).toBeNull()
    })

    it('returns null for the pre-rename {label, tags} shape', () => {
        expect(normalizeTicketGroups([{ label: 'VIPs', tags: ['vip'] }])).toBeNull()
    })

    it('returns null for filters with wrong value types or unknown vocabulary', () => {
        const withFilters = (filters: unknown[]): unknown => [{ label: 'A', filters }]
        // value must be a string list for ticket_tags and "in"
        expect(
            normalizeTicketGroups(withFilters([{ type: 'ticket_tags', operator: 'any_of', value: 'vip' }]))
        ).toBeNull()
        expect(
            normalizeTicketGroups(withFilters([{ type: 'ticket_tags', operator: 'any_of', value: ['vip', 7] }]))
        ).toBeNull()
        expect(
            normalizeTicketGroups(
                withFilters([{ type: 'ticket_property', key: 'status', operator: 'in', value: 'open' }])
            )
        ).toBeNull()
        // string value required for icontains / dates
        expect(
            normalizeTicketGroups(
                withFilters([{ type: 'ticket_property', key: 'email_from', operator: 'icontains', value: ['x'] }])
            )
        ).toBeNull()
        expect(
            normalizeTicketGroups(
                withFilters([{ type: 'ticket_property', key: 'created_at', operator: 'date_after', value: 3 }])
            )
        ).toBeNull()
        // unknown type / key / operator combos
        expect(normalizeTicketGroups(withFilters([{ type: 'nope', operator: 'any_of', value: [] }]))).toBeNull()
        expect(
            normalizeTicketGroups(withFilters([{ type: 'ticket_property', key: 'nope', operator: 'in', value: ['x'] }]))
        ).toBeNull()
        expect(
            normalizeTicketGroups(
                withFilters([{ type: 'ticket_property', key: 'email_from', operator: 'in', value: ['x'] }])
            )
        ).toBeNull()
        expect(normalizeTicketGroups(withFilters(['garbage']))).toBeNull()
    })

    it('returns null for duplicate labels, matching the backend fallback', () => {
        expect(
            normalizeTicketGroups([
                { label: 'A', filters: [] },
                { label: 'A', filters: [] },
            ])
        ).toBeNull()
    })

    it('allows the same tag in two groups (overlap is valid — first match wins)', () => {
        const groups = [
            { label: 'A', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['vip'] }] },
            { label: 'B', filters: [{ type: 'ticket_tags', operator: 'any_of', value: ['vip', 'urgent'] }] },
        ]
        expect(normalizeTicketGroups(groups)).toEqual(groups)
    })
})

describe('validateTicketGroups', () => {
    it('accepts well-formed groups', () => {
        expect(() => validateTicketGroups(GROUPS)).not.toThrow()
    })

    it('rejects duplicate labels', () => {
        expect(() =>
            validateTicketGroups([
                { label: 'A', filters: [] },
                { label: 'A', filters: [] },
            ])
        ).toThrow(/duplicate group label/i)
    })

    it('rejects empty labels', () => {
        expect(() => validateTicketGroups([{ label: '   ', filters: [] }])).toThrow(/non-empty label/i)
    })

    it('rejects more than 10 filters in a group', () => {
        const filters = Array.from({ length: 11 }, (_, index) => ({
            type: 'ticket_tags' as const,
            operator: 'any_of' as const,
            value: [`tag_${index}`],
        }))
        expect(() => validateTicketGroups([{ label: 'A', filters }])).toThrow(/at most 10 filters/i)
    })

    it('rejects empty value lists', () => {
        expect(() =>
            validateTicketGroups([{ label: 'A', filters: [{ type: 'ticket_tags', operator: 'any_of', value: [] }] }])
        ).toThrow(/at least one value/i)
    })

    it('rejects a value on is_set/is_not_set', () => {
        const filters = [
            { type: 'ticket_property', key: 'sla_due_at', operator: 'is_set', value: 'nope' },
        ] as unknown as TicketGroup['filters']
        expect(() => validateTicketGroups([{ label: 'A', filters }])).toThrow(/takes no value/i)
    })

    it('accepts the full date grammar', () => {
        for (const value of ['-3d', '-12h', '-1mStart', '-1yEnd', '2026-07-01', '2026-07-01T12:00:00Z']) {
            expect(() =>
                validateTicketGroups([
                    {
                        label: 'A',
                        filters: [{ type: 'ticket_property', key: 'created_at', operator: 'date_before', value }],
                    },
                ])
            ).not.toThrow()
        }
    })

    it('rejects dates outside the strict grammar', () => {
        for (const value of [
            '3d',
            '+3d',
            '-3days',
            '-3dstart',
            '-0d',
            '-1001d',
            'yesterday',
            '2026-2-3',
            '',
            // calendar-invalid shapes V8's Date would forgive but the server rejects
            '2026-02-30',
            '2026-06-31',
            '2026-07-01T24:00',
            '0000-01-01',
        ]) {
            expect(() =>
                validateTicketGroups([
                    {
                        label: 'A',
                        filters: [{ type: 'ticket_property', key: 'created_at', operator: 'date_after', value }],
                    },
                ])
            ).toThrow(/can't parse the date/i)
        }
    })
})

describe('conversations-ticket-groups-get', () => {
    it('reports the saved groups when customized', async () => {
        const context = mockContext({ conversationsSettings: { ticket_groups: GROUPS } })
        const result = await getTicketGroupsTool().handler(context, {})
        expect(result).toMatchObject({ customized: true, groups: GROUPS })
        expect(result.settings_url).toContain('/support/settings')
        expect(result.settings_url).toContain('conversations-ticket-groups')
    })

    it('reports uncustomized teams as following the examples', async () => {
        const context = mockContext({ conversationsSettings: { widget_enabled: true } })
        const result = await getTicketGroupsTool().handler(context, {})
        expect(result).toMatchObject({ customized: false, groups: null })
        expect(result.message).toMatch(/example/i)
    })
})

describe('conversations-ticket-groups-update', () => {
    it('previews without saving when confirm is omitted', async () => {
        const context = mockContext({ conversationsSettings: null })
        const patch = vi.fn()
        context.api.projects = () =>
            ({
                get: vi.fn().mockResolvedValue({ success: true, data: { conversations_settings: null } }),
                updateConversationsTicketGroups: patch,
            }) as any
        const result = await updateTicketGroupsTool().handler(context, { groups: GROUPS })
        expect(result.applied).toBe(false)
        expect(result.groups).toEqual(GROUPS)
        expect(patch).not.toHaveBeenCalled()
    })

    it('saves when confirm is true', async () => {
        const context = mockContext({ conversationsSettings: null })
        const result = await updateTicketGroupsTool().handler(context, { groups: GROUPS, confirm: true })
        expect(result.applied).toBe(true)
        expect(result.groups).toEqual(GROUPS)
    })

    it('skips the read and PATCHes directly on a confirmed write', async () => {
        const get = vi.fn()
        const context = mockContext({ conversationsSettings: null })
        const inner = context.api.projects()
        context.api.projects = () => ({ ...inner, get }) as any
        const result = await updateTicketGroupsTool().handler(context, { groups: GROUPS, confirm: true })
        expect(result.applied).toBe(true)
        expect(get).not.toHaveBeenCalled()
    })

    it('previews a reset as a no-op when the team already follows the examples', async () => {
        const context = mockContext({ conversationsSettings: null })
        const result = await updateTicketGroupsTool().handler(context, { groups: null })
        expect(result.applied).toBe(false)
        expect(result.message).toMatch(/no-op/i)
    })

    it('previews a reset as discarding the groups only when custom ones exist', async () => {
        const context = mockContext({ conversationsSettings: { ticket_groups: GROUPS } })
        const result = await updateTicketGroupsTool().handler(context, { groups: null })
        expect(result.applied).toBe(false)
        expect(result.message).toMatch(/discarding its custom groups/i)
    })

    it('resets to the examples with groups null', async () => {
        const context = mockContext({ conversationsSettings: { ticket_groups: GROUPS } })
        const result = await updateTicketGroupsTool().handler(context, { groups: null, confirm: true })
        expect(result.applied).toBe(true)
        expect(result.groups).toBeNull()
        expect(result.message).toMatch(/example/i)
    })

    it('fails fast on a duplicate label without calling the API', async () => {
        const context = mockContext({ conversationsSettings: null })
        await expect(
            updateTicketGroupsTool().handler(context, {
                groups: [
                    { label: 'A', filters: [] },
                    { label: 'A', filters: [] },
                ],
                confirm: true,
            })
        ).rejects.toThrow(/duplicate group label/i)
    })

    it('fails fast on a bad date value without calling the API', async () => {
        const context = mockContext({ conversationsSettings: null })
        await expect(
            updateTicketGroupsTool().handler(context, {
                groups: [
                    {
                        label: 'A',
                        filters: [
                            { type: 'ticket_property', key: 'created_at', operator: 'date_after', value: '3 days ago' },
                        ],
                    },
                ],
                confirm: true,
            })
        ).rejects.toThrow(/can't parse the date/i)
    })
})
