import type { WebBreakdown, WebFilter } from '../views'
import { breakdownFilter, toggleFilter, utcOffsetLabel } from './webAnalyticsBreakdowns'

function filter(id: string, value: string | number): WebFilter {
    return { id, label: id, value: String(value), properties: [{ key: id, type: 'event', operator: 'exact', value }] }
}

describe('web analytics breakdowns', () => {
    test.each<[string, WebBreakdown, unknown, WebFilter['properties'] | null]>([
        ['a path', 'Page', '/pricing', [{ key: '$pathname', type: 'event', operator: 'exact', value: '/pricing' }]],
        [
            'an entry path, a session property',
            'InitialPage',
            '/',
            [{ key: '$entry_pathname', type: 'session', operator: 'exact', value: '/' }],
        ],
        [
            'a missing channel',
            'InitialChannelType',
            null,
            [{ key: '$channel_type', type: 'session', operator: 'is_not_set' }],
        ],
        [
            'a viewport, by width and height',
            'Viewport',
            [1440, 900],
            [
                { key: '$viewport_width', type: 'event', operator: 'exact', value: 1440 },
                { key: '$viewport_height', type: 'event', operator: 'exact', value: 900 },
            ],
        ],
        [
            'a time zone, as the browser offset in minutes',
            'Timezone',
            5.5,
            [{ key: '$timezone_offset', type: 'event', operator: 'exact', value: -330 }],
        ],
        [
            'a region, by its subdivision code',
            'Region',
            ['US', 'CA', 'California'],
            [{ key: '$geoip_subdivision_1_code', type: 'event', operator: 'exact', value: 'CA' }],
        ],
        [
            'a city, by its name',
            'City',
            ['GB', 'London'],
            [{ key: '$geoip_city_name', type: 'event', operator: 'exact', value: 'London' }],
        ],
        [
            'a language without a region',
            'Language',
            'nl-',
            [{ key: '$browser_language', type: 'event', operator: 'regex', value: '^nl(-|$)' }],
        ],
        [
            'a language grouped across regions',
            'Language',
            'en-US',
            [{ key: '$browser_language', type: 'event', operator: 'regex', value: '^en(-|$)' }],
        ],
        ['a missing language', 'Language', '-', [{ key: '$browser_language', type: 'event', operator: 'is_not_set' }]],
        ['a region without a subdivision', 'Region', ['NL', null, null], null],
        ['an outbound link', 'ExitClick', 'https://example.com/', null],
    ])('a row tap on %s filters like the web', (_name, breakdown, raw, properties) => {
        expect(breakdownFilter(breakdown, raw)?.properties ?? null).toEqual(properties)
    })

    test.each<[string, WebFilter[], WebFilter, WebFilter[], string]>([
        [
            'adds a new property',
            [filter('$os', 'iOS')],
            filter('$pathname', '/'),
            [filter('$os', 'iOS'), filter('$pathname', '/')],
            'added',
        ],
        [
            'replaces another value of the same property in place',
            [filter('$pathname', '/'), filter('$os', 'iOS')],
            filter('$pathname', '/pricing'),
            [filter('$pathname', '/pricing'), filter('$os', 'iOS')],
            'replaced',
        ],
        ['turns off the same value', [filter('$pathname', '/')], filter('$pathname', '/'), [], 'removed'],
    ])('toggleFilter %s', (_name, before, tapped, after, kind) => {
        expect(toggleFilter(before, tapped)).toEqual({ filters: after, kind })
    })

    test.each([
        [0, 'UTC'],
        [-5, 'UTC-5'],
        [5.5, 'UTC+5:30'],
        [5.75, 'UTC+5:45'],
    ])('labels an offset of %s hours as %s', (hours, label) => {
        expect(utcOffsetLabel(hours)).toBe(label)
    })
})
