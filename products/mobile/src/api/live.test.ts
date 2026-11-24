import {
    DEFAULT_LIVE_TRAFFIC_FILTERS,
    liveTrafficFilterCount,
    normalizeLiveTrafficFilters,
} from '@/model/liveTrafficFilters'
import { type LiveQueryKey, liveQuery, liveWindow } from './live'

const options = {
    window: liveWindow(1800000000000),
    pathCleaning: true,
    filterTestAccounts: true,
    trafficFilters: normalizeLiveTrafficFilters({
        excludeBots: true,
        hostname: '  APP.EXAMPLE.COM:8080 ',
        pathPrefix: " Products/V1.2/[SKU]+_%'s ",
        channelType: ' Organic Search ',
        countryCode: ' ca ',
        deviceType: 'Tablet',
        referringDomain: ' SEARCH.EXAMPLE.COM ',
    }),
}
const expectedProperties = [
    { key: '$virt_is_bot', type: 'event', operator: 'exact', value: 'false' },
    { key: '$host', type: 'event', operator: 'exact', value: 'app.example.com:8080' },
    { key: '$pathname', type: 'event', operator: 'regex', value: "^/Products/V1\\.2/\\[SKU\\]\\+_%'s" },
    { key: '$geoip_country_code', type: 'event', operator: 'exact', value: 'CA' },
    { key: '$device_type', type: 'event', operator: 'exact', value: 'Tablet' },
    { key: '$channel_type', type: 'session', operator: 'exact', value: 'Organic Search' },
    { key: '$entry_referring_domain', type: 'session', operator: 'exact', value: 'search.example.com' },
]

describe('Live traffic filters', () => {
    it('normalizes host and path input while keeping URL path case and literal characters', () => {
        expect(options.trafficFilters).toEqual({
            excludeBots: true,
            hostname: 'app.example.com:8080',
            pathPrefix: "/Products/V1.2/[SKU]+_%'s",
            pathMode: 'prefix',
            countryCode: 'CA',
            deviceType: 'Tablet',
            channelType: 'Organic Search',
            referringDomain: 'search.example.com',
        })
        expect(liveTrafficFilterCount(options.trafficFilters)).toBe(7)
        expect(normalizeLiveTrafficFilters({ excludeBots: false, hostname: '  ', pathPrefix: ' ' })).toEqual(
            DEFAULT_LIVE_TRAFFIC_FILTERS
        )
    })

    it('matches an exact path including punctuation by default, preserving legacy prefix selections', () => {
        const pathPrefix = '/Docs/[v2]/readme.md'
        const filters = { ...DEFAULT_LIVE_TRAFFIC_FILTERS, pathPrefix }
        const exact = liveQuery('paths', { ...options, trafficFilters: filters })
        expect(exact.properties).toEqual([{ key: '$pathname', type: 'event', operator: 'exact', value: pathPrefix }])
        expect(normalizeLiveTrafficFilters({ excludeBots: false, hostname: '', pathPrefix }).pathMode).toBe('prefix')
        expect(liveTrafficFilterCount(filters)).toBe(1)
    })

    it('filters direct visits by the recorded entry-domain sentinel and accepts custom project channels', () => {
        const query = liveQuery('usersOnline', {
            ...options,
            trafficFilters: {
                ...DEFAULT_LIVE_TRAFFIC_FILTERS,
                channelType: 'Partner Network',
                referringDomain: '$direct',
            },
        })
        expect(query.filters).toEqual({
            filterTestAccounts: true,
            properties: [
                { key: '$channel_type', type: 'session', operator: 'exact', value: 'Partner Network' },
                { key: '$entry_referring_domain', type: 'session', operator: 'exact', value: '$direct' },
            ],
        })
    })

    it.each<LiveQueryKey>([
        'usersPageviews',
        'usersOnline',
        'geo',
        'recentEvents',
        'device',
        'browser',
        'platforms',
        'mobileMetrics',
        'mobileSessions',
        'referrer',
        'screens',
    ])('applies the same structured filters inside the %s event query', (key) => {
        const query = liveQuery(key, { ...options, mobileOnly: true })
        expect(query.query).toContain('AND {filters}')
        expect(query.query).not.toContain(options.trafficFilters.pathPrefix)
        expect(query.filters).toEqual({ filterTestAccounts: true, properties: expectedProperties })
    })

    it.each<LiveQueryKey>(['paths', 'screens'])(
        'applies the traffic filters to the All audience %s breakdown',
        (key) => {
            const query = liveQuery(key, options)
            expect(query.properties).toEqual(expectedProperties)
            expect(query.filterTestAccounts).toBe(true)
        }
    )

    it('intersects the web SDK and traffic property groups for top pages', () => {
        const query = liveQuery('paths', { ...options, webOnly: true })
        expect(query.properties).toEqual({
            type: 'AND',
            values: [
                { type: 'OR', values: expect.arrayContaining([expect.objectContaining({ key: '$lib' })]) },
                { type: 'AND', values: expectedProperties },
            ],
        })
    })

    it('filters the online count even when internal users are included', () => {
        const query = liveQuery('usersOnline', { ...options, filterTestAccounts: false })
        expect(query.query).toContain('AND {filters}')
        expect(query.filters).toEqual({ filterTestAccounts: false, properties: expectedProperties })
    })
})
