import { SKILL_DESCRIPTION_MAX_LENGTH } from 'products/skills/frontend/skillConstants'

import { decodeScoutCreateTemplate, encodeScoutCreateTemplate } from './scoutTemplateDeepLink'

describe('scoutTemplateDeepLink', () => {
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

    it('ignores config and unknown fields — scheduling is never URL-controlled', () => {
        const encoded = encodeScoutCreateTemplate({
            description: 'd',
            // @ts-expect-error deliberately smuggling extra fields
            config: { enabled: true, emit: true, run_interval_minutes: 30 },
            extra: 'nope',
        })
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
