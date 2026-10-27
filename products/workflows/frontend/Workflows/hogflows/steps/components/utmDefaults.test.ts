import { matchesTeamUtmDefaults, utmKeysFromDefaultAfterEdit } from './utmDefaults'
import type { UtmTagKey } from './UtmTagFields'

describe('utmDefaults', () => {
    describe('utmKeysFromDefaultAfterEdit', () => {
        it.each([
            {
                case: 'an edited value stops following the team default',
                fromDefault: ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content'] as UtmTagKey[],
                next: { utm_source: 'partner', utm_campaign: 'spring' },
                expected: ['utm_medium', 'utm_campaign', 'utm_content'],
            },
            {
                case: 'a step from before team defaults follows every key it did not change',
                fromDefault: undefined,
                next: { utm_source: 'newsletter', utm_campaign: 'summer' },
                expected: ['utm_source', 'utm_medium', 'utm_content'],
            },
            {
                case: 'a key that already stopped following never comes back on its own',
                fromDefault: ['utm_medium'] as UtmTagKey[],
                next: { utm_source: 'newsletter', utm_campaign: 'spring' },
                expected: ['utm_medium'],
            },
        ])('$case', ({ fromDefault, next, expected }) => {
            const previous = { utm_source: 'newsletter', utm_campaign: 'spring' }

            expect(utmKeysFromDefaultAfterEdit(fromDefault, previous, next)).toEqual(expected)
        })
    })

    describe('matchesTeamUtmDefaults', () => {
        it.each([
            { case: 'surrounding spaces still match the saved value', value: ' newsletter ', expected: true },
            { case: 'a different value does not match', value: 'partner', expected: false },
        ])('$case', ({ value, expected }) => {
            const defaults = { enabled: true, params: { utm_source: 'newsletter' } }

            expect(matchesTeamUtmDefaults({ utm_source: value }, defaults)).toBe(expected)
        })
    })
})
