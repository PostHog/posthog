import { WebPageDirectoryRow, WebPageDirectorySiteTotals } from '~/queries/schema/schema-general'

import {
    GoogleSearchConsoleState,
    PageHealthStatus,
    computeAiHealth,
    computeEngagementHealth,
    computeSearchHealth,
} from './pageHealth'

const site = (overrides: Partial<WebPageDirectorySiteTotals> = {}): WebPageDirectorySiteTotals => ({
    serverLogs: 100,
    visitors: { current: 10000 },
    googleSearch: { current: 3000 },
    aiReferrals: { current: 200 },
    aiCrawls: { current: 5000 },
    timeOnPageP90: 60,
    bounceRate: 0.4,
    ...overrides,
})

const page = (overrides: Partial<WebPageDirectoryRow> = {}): WebPageDirectoryRow => ({
    page: 'example.com/pricing',
    visitors: { current: 1000 },
    googleSearch: { current: 300, previous: 300 },
    aiReferrals: { current: 20, previous: 20 },
    aiCrawls: { current: 400 },
    aiCrawlers: 5,
    timeOnPageP90: 90,
    bounceRate: 0.4,
    ...overrides,
})

const connected: GoogleSearchConsoleState = { clicks: 300, impressions: 9000, position: 4.2 }

describe('pageHealth', () => {
    test.each<[string, WebPageDirectoryRow | null, GoogleSearchConsoleState, PageHealthStatus]>([
        ['loading until data arrives', null, connected, 'loading'],
        ['too few visitors to judge', page({ visitors: { current: 12 } }), connected, 'no_data'],
        [
            'no Google visitors and no impressions',
            page({ googleSearch: { current: 0 } }),
            { clicks: 0, impressions: 0, position: null },
            'not_found',
        ],
        ['Google share at the site level and a good position', page(), connected, 'strong'],
        ['a strong page without Search Console stays strong', page(), 'not_connected', 'strong'],
        ['a strong page stays strong when Search Console fails to load', page(), 'error', 'strong'],
        ['Google share well below the site', page({ googleSearch: { current: 50 } }), connected, 'needs_attention'],
        [
            'Google visitors falling',
            page({ googleSearch: { current: 300, previous: 500 } }),
            connected,
            'needs_attention',
        ],
        [
            'Google visitors falling exactly 20%',
            page({ googleSearch: { current: 240, previous: 300 } }),
            connected,
            'needs_attention',
        ],
        ['ranking past page two', page(), { clicks: 300, impressions: 9000, position: 31 }, 'needs_attention'],
        ['share between weak and strong', page({ googleSearch: { current: 200 } }), connected, 'fair'],
    ])('search visibility: %s', (_name, pageRow, searchConsole, status) => {
        expect(computeSearchHealth({ page: pageRow, site: site(), searchConsole }).status).toEqual(status)
    })

    test.each<[string, WebPageDirectoryRow, WebPageDirectorySiteTotals, PageHealthStatus]>([
        [
            'no server logs and no AI visitors',
            page({ aiReferrals: { current: 0 }, aiCrawls: { current: 0 }, aiCrawlers: 0 }),
            site({ serverLogs: 0, aiCrawls: { current: 0 } }),
            'not_set_up',
        ],
        [
            'crawler events without server logs',
            page({ aiReferrals: { current: 0 } }),
            site({ serverLogs: 0 }),
            'needs_attention',
        ],
        [
            'logs forwarded but nothing read or referred',
            page({ aiReferrals: { current: 0 }, aiCrawls: { current: 0 }, aiCrawlers: 0 }),
            site(),
            'not_found',
        ],
        ['read by several crawlers and recommended', page(), site(), 'strong'],
        [
            'crawled but never recommended',
            page({ aiReferrals: { current: 0 }, aiCrawlers: 4 }),
            site(),
            'needs_attention',
        ],
        ['only one crawler', page({ aiCrawlers: 1 }), site(), 'needs_attention'],
        [
            'AI visitors without measured crawlers',
            page({ aiCrawls: { current: 0 }, aiCrawlers: 0 }),
            site({ serverLogs: 0, aiCrawls: { current: 0 } }),
            'strong',
        ],
        ['fewer crawlers than strong needs', page({ aiCrawlers: 2 }), site(), 'fair'],
        [
            'crawled with too few visitors to judge referrals',
            page({ visitors: { current: 1 }, aiReferrals: { current: 1, previous: 1 }, aiCrawlers: 3 }),
            site(),
            'no_data',
        ],
        [
            'crawled but never recommended with few visitors',
            page({ visitors: { current: 5 }, aiReferrals: { current: 0 } }),
            site(),
            'needs_attention',
        ],
    ])('AI visibility: %s', (_name, pageRow, siteTotals, status) => {
        expect(computeAiHealth({ page: pageRow, site: siteTotals, searchConsole: 'not_connected' }).status).toEqual(
            status
        )
    })

    test.each<[string, WebPageDirectoryRow, PageHealthStatus, string, Partial<WebPageDirectorySiteTotals>?]>([
        ['no timing or bounce data', page({ timeOnPageP90: null, bounceRate: null }), 'no_data', ''],
        ['sub-second visits read as a redirect', page({ timeOnPageP90: 0.096 }), 'needs_attention', 'redirect'],
        ['quick exits', page({ timeOnPageP90: 6 }), 'needs_attention', ''],
        ['bounce far above the site', page({ bounceRate: 0.7 }), 'needs_attention', ''],
        ['bounce exactly at the poor margin', page({ bounceRate: 0.7 }), 'needs_attention', '', { bounceRate: 0.55 }],
        ['long visits and a normal bounce rate', page(), 'strong', ''],
        ['visits shorter than strong needs', page({ timeOnPageP90: 20 }), 'fair', ''],
    ])('engagement: %s', (_name, pageRow, status, headlineIncludes, siteOverrides = {}) => {
        const card = computeEngagementHealth({
            page: pageRow,
            site: site(siteOverrides),
            searchConsole: 'not_connected',
        })
        expect(card.status).toEqual(status)
        expect(card.headline).toContain(headlineIncludes)
    })
})
