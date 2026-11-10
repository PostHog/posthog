import {
    DefaultChannelTypes,
    NativeMarketingSource,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
    WebStatsTableQueryResponse,
} from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    buildMarketingAnalyticsDestination,
    detectAdPlatforms,
    isMarketingCrossSellSnoozed,
    meetsPaidTrafficThreshold,
    paidTrafficTarget,
    paidTrafficTargetFromFilters,
    snoozeAfterDismissal,
    summarizePaidTraffic,
} from './marketingCrossSellUtils'

const ENABLED: NativeMarketingSource[] = ['GoogleAds', 'MetaAds', 'LinkedinAds']
const DAY = 24 * 60 * 60 * 1000

const table = (rows: [string, [number, number | null]][]): WebStatsTableQueryResponse => ({
    results: rows,
    columns: ['context.columns.breakdown_value', 'context.columns.visitors'],
})

describe('marketing cross sell utils', () => {
    it.each([
        [DefaultChannelTypes.PaidSearch, [1, 0], true],
        [DefaultChannelTypes.PaidSocial, [10, null], true],
        [DefaultChannelTypes.CrossNetwork, [2, null], true],
        [DefaultChannelTypes.PaidUnknown, [5, null], true],
        ['Display', [5, null], true],
        [DefaultChannelTypes.OrganicSearch, [100, null], false],
        [DefaultChannelTypes.Direct, [100, null], false],
        [DefaultChannelTypes.PaidSearch, [0, 50], false],
        ['google', [100, null], false],
    ])('classifies %s with visitors %j as paid=%s', (channel, visitors, expected) => {
        const response: WebStatsTableQueryResponse = {
            results: [[channel, visitors]],
            columns: ['context.columns.channel_type', 'context.columns.visitors'],
        }
        expect((summarizePaidTraffic(response)?.paidVisitors ?? 0) > 0).toBe(expected)
    })

    it('requires visitors in the response rather than treating a different metric as evidence', () => {
        expect(
            summarizePaidTraffic({
                results: [[DefaultChannelTypes.PaidSearch, [4, null]]],
                columns: ['channel', 'views'],
            })
        ).toBeNull()
        expect(summarizePaidTraffic(null)).toBeNull()
    })

    it.each([
        ['enough paid visitors and share', 60, 940, true],
        ['too few paid visitors', 49, 51, false],
        ['too small a share', 60, 9940, false],
        ['exactly at both limits', 50, 1616, true],
    ])('applies the paid traffic threshold for %s', (_, paid, organic, expected) => {
        const summary = summarizePaidTraffic(
            table([
                [DefaultChannelTypes.PaidSearch, [paid, null]],
                [DefaultChannelTypes.Direct, [organic, null]],
            ])
        )
        expect(meetsPaidTrafficThreshold(summary)).toBe(expected)
    })

    it('ranks detected ad platforms by visitors and honors custom source mappings', () => {
        const response = table([
            ['google', [40, null]],
            ['fb-paid', [70, null]],
            ['newsletter', [500, null]],
            ['adwords', [45, null]],
            ['tiktok', [300, null]],
            ['linkedin', [0, 20]],
        ])
        expect(detectAdPlatforms(response, { custom_source_mappings: { MetaAds: ['fb-paid'] } }, ENABLED)).toEqual([
            'GoogleAds',
            'MetaAds',
        ])
    })

    it.each([
        ['first dismissal, inside the snooze', 1, 29 * DAY, true],
        ['first dismissal, after the snooze', 1, 31 * DAY, false],
        ['second dismissal, long after', 2, 365 * DAY, true],
    ])('snoozes after the %s', (_, dismissals, elapsed, expected) => {
        let snooze = { dismissedAt: null as number | null, dismissCount: 0 }
        for (let i = 0; i < dismissals; i++) {
            snooze = snoozeAfterDismissal(snooze, 1000)
        }
        expect(isMarketingCrossSellSnoozed(snooze, 1000 + elapsed)).toBe(expected)
    })

    it.each([
        [WebStatsBreakdown.InitialChannelType, DefaultChannelTypes.PaidSocial, { platform: null }],
        [WebStatsBreakdown.InitialChannelType, DefaultChannelTypes.OrganicSocial, null],
        [WebStatsBreakdown.InitialUTMSource, 'Facebook', { platform: 'MetaAds' }],
        [WebStatsBreakdown.InitialUTMSource, 'tiktok', null],
        [WebStatsBreakdown.InitialUTMCampaign, 'google', null],
    ])('targets %s=%s as %j', (breakdown, value, expected) => {
        expect(paidTrafficTarget(breakdown, value, null, ENABLED)).toEqual(expected)
    })

    it('prefers a filter that names an ad platform over a paid channel filter', () => {
        const filters: WebAnalyticsPropertyFilters = [
            {
                key: '$channel_type',
                type: PropertyFilterType.Session,
                operator: PropertyOperator.Exact,
                value: [DefaultChannelTypes.PaidSearch],
            },
            {
                key: '$entry_utm_source',
                type: PropertyFilterType.Session,
                operator: PropertyOperator.Exact,
                value: 'google',
            },
            {
                key: '$entry_utm_source',
                type: PropertyFilterType.Session,
                operator: PropertyOperator.IsNot,
                value: 'facebook',
            },
        ]
        expect(paidTrafficTargetFromFilters(filters, null, ENABLED)).toEqual({ platform: 'GoogleAds' })
    })

    it.each([
        [
            false,
            'GoogleAds' as const,
            '/data-warehouse/new-source?kind=GoogleAds&returnUrl=%2Fmarketing%3Fdate_from%3D-7d%26date_to%3D&returnLabel=Marketing+analytics&entry_point=web_analytics_cross_sell',
        ],
        [false, null, '/marketing?date_from=-7d&date_to=&tab=setup&section=sources'],
        [true, 'GoogleAds' as const, '/marketing?date_from=-7d&date_to='],
        [null, 'GoogleAds' as const, '/marketing?date_from=-7d&date_to='],
    ])('sends connected=%s with platform %s to %s', (hasConnectedSources, platform, expected) => {
        expect(
            buildMarketingAnalyticsDestination({
                hasConnectedSources,
                platform,
                dateRange: { date_from: '-7d', date_to: null },
                setupEnabled: true,
            })
        ).toContain(expected)
    })
})
