import { SKILL_DESCRIPTION_MAX_LENGTH } from 'products/skills/frontend/skillConstants'

import {
    decodeScoutCreateTemplate,
    encodeScoutCreateTemplate,
    storeCommunityScoutCreateTemplate,
} from './scoutTemplateDeepLink'

describe('scoutTemplateDeepLink', () => {
    it('moves a large community draft outside the URL and disconnects MCP servers', () => {
        const body = 'x'.repeat(50_000)
        const key = storeCommunityScoutCreateTemplate({ description: 'Large scout', body })

        expect(key.length).toBeLessThan(100)
        expect(decodeScoutCreateTemplate(key)).toEqual({
            description: 'Large scout',
            body,
            config: { mcp_gateway_server_ids: [] },
        })
        expect(decodeScoutCreateTemplate(key)).toBeNull()
    })

    it('round-trips a full template', () => {
        const encoded = encodeScoutCreateTemplate({
            name: 'signals-scout-silent-failure',
            description: 'Watches the core action for silent failures',
            body: '# Scout\n\nSpeak up when completions fall while attempts hold steady.',
        })
        // URL-safe: must survive a hash fragment untouched.
        expect(encoded).not.toMatch(/[+/=]/)
        expect(decodeScoutCreateTemplate(encoded)).toEqual({
            name: 'signals-scout-silent-failure',
            description: 'Watches the core action for silent failures',
            body: '# Scout\n\nSpeak up when completions fall while attempts hold steady.',
        })
    })

    it('round-trips multibyte content', () => {
        const encoded = encodeScoutCreateTemplate({ description: 'Watches naïve 🦔 flows – en dashes too' })
        expect(decodeScoutCreateTemplate(encoded)).toEqual({ description: 'Watches naïve 🦔 flows – en dashes too' })
    })

    it('prefixes an unprefixed name', () => {
        const encoded = encodeScoutCreateTemplate({ name: 'silent-failure', description: 'd' })
        expect(decodeScoutCreateTemplate(encoded)?.name).toBe('signals-scout-silent-failure')
    })

    it('drops an invalid name but keeps the rest', () => {
        const encoded = encodeScoutCreateTemplate({ name: 'signals-scout-INVALID NAME!', description: 'd' })
        expect(decodeScoutCreateTemplate(encoded)).toEqual({ description: 'd' })
    })

    it('truncates an oversized description', () => {
        const encoded = encodeScoutCreateTemplate({ description: 'x'.repeat(SKILL_DESCRIPTION_MAX_LENGTH + 50) })
        expect(decodeScoutCreateTemplate(encoded)?.description).toHaveLength(SKILL_DESCRIPTION_MAX_LENGTH)
    })

    it('carries the settings the modal shows', () => {
        const encoded = encodeScoutCreateTemplate({
            description: 'd',
            config: { run_interval_minutes: 720, emit: false, tags: ['Web Analytics', 'web analytics'] },
        })
        expect(decodeScoutCreateTemplate(encoded)).toEqual({
            description: 'd',
            config: { run_interval_minutes: 720, emit: false, tags: ['web-analytics'] },
        })
    })

    it.each([
        ['a setting the modal never shows', { network_access: 'full', model: 'claude', enabled: false }],
        ['an out-of-range interval', { run_interval_minutes: 5 }],
        ['an interval past the 30-day cap', { run_interval_minutes: 43201 }],
        ['a cron expression with the wrong field count', { run_cron_schedule: '0 9 * *' }],
        ['a non-boolean emit', { emit: 'yes' }],
        ['a non-array tags value', { tags: 'web-analytics' }],
    ])('drops %s', (_label, config) => {
        // @ts-expect-error deliberately smuggling values the payload type doesn't allow
        const encoded = encodeScoutCreateTemplate({ description: 'd', config })
        expect(decodeScoutCreateTemplate(encoded)).toEqual({ description: 'd' })
    })

    it('keeps a valid cron expression', () => {
        const encoded = encodeScoutCreateTemplate({ description: 'd', config: { run_cron_schedule: '0 9 * * 1' } })
        expect(decodeScoutCreateTemplate(encoded)?.config).toEqual({ run_cron_schedule: '0 9 * * 1' })
    })

    it('ignores unknown top-level fields', () => {
        // @ts-expect-error deliberately smuggling an extra field
        const encoded = encodeScoutCreateTemplate({ description: 'd', extra: 'nope' })
        expect(decodeScoutCreateTemplate(encoded)).toEqual({ description: 'd' })
    })

    it.each([
        ['undefined', undefined],
        ['empty string', ''],
        ['not base64', '!!!not-base64!!!'],
        ['base64 of non-JSON', 'bm90IGpzb24'],
        ['base64 of a JSON array', 'W10'],
        ['name-only payload', encodeScoutCreateTemplate({ name: 'signals-scout-x' })],
        ['oversized payload', 'A'.repeat(20000)],
    ])('returns null for %s', (_label, raw) => {
        expect(decodeScoutCreateTemplate(raw)).toBeNull()
    })
})
