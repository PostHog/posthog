import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { BindLogic, useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { MarketingAnalyticsScene } from 'scenes/marketing-analytics/MarketingAnalyticsScene'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { MarketingAnalyticsFilters } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsFilters/MarketingAnalyticsFilters'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { mswDecorator } from '~/mocks/browser'
import { MockResolverInfo, MockSignature, Mocks } from '~/mocks/utils'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import {
    AttributionMode,
    NodeKind,
    MarketingAnalyticsSearchQuery,
    MarketingAnalyticsSearchRow,
} from '~/queries/schema/schema-general'

import IconBingAds from 'public/services/bing-ads.svg'
import IconGoogleAds from 'public/services/google-ads.png'
import IconGoogleSearchConsole from 'public/services/google-search-console.svg'

import { expect, userEvent } from 'storybook/test'

import { SearchPerformanceTab } from './SearchPerformanceTab'

const SOURCES = [
    {
        id: 'example-google',
        source_type: 'GoogleAds',
        description: 'Example Google Ads',
        prefix: 'example',
        status: 'Completed',
        schemas: [
            'campaign',
            'campaign_overview_stats',
            'keyword',
            'keyword_stats',
            'keyword_placement_stats',
            'landing_page_stats',
        ].map((name) => ({
            id: `example-${name}`,
            name,
            should_sync: true,
            sync_frequency: '24hour',
            last_synced_at: '2025-02-14T12:00:00Z',
            status: 'Completed',
            table: { name: `example_${name}`, hogql_name: `example.${name}` },
        })),
    },
    {
        id: 'example-bing',
        source_type: 'BingAds',
        description: 'Example Bing Ads',
        prefix: 'example',
        status: 'Completed',
        schemas: [
            'campaigns',
            'campaign_performance_report',
            'keyword_performance_report',
            'destination_url_performance_report',
        ].map((name) => ({
            id: `example-bing-${name}`,
            name,
            should_sync: true,
            sync_frequency: '24hour',
            last_synced_at: '2025-02-14T12:00:00Z',
            status: 'Completed',
            table: { name: `example_bing_${name}`, hogql_name: `example.bing_${name}` },
        })),
    },
    {
        id: 'example-organic',
        source_type: 'GoogleSearchConsole',
        description: 'example.com',
        prefix: 'example_organic',
        status: 'Completed',
        schemas: ['search_analytics_by_query', 'search_analytics_by_page', 'search_analytics_by_query_page'].map(
            (name) => ({
                id: `example-organic-${name}`,
                name,
                should_sync: true,
                sync_frequency: '24hour',
                last_synced_at: '2025-02-14T12:00:00Z',
                status: 'Completed',
                table: { name: `example_organic_${name}`, hogql_name: `example.organic_${name}` },
            })
        ),
    },
]

const ROWS: MarketingAnalyticsSearchRow[] = [
    {
        keyword: 'product analytics',
        platform: 'GoogleSearchConsole',
        matchType: null,
        currency: null,
        clicks: 1240,
        impressions: 18000,
        ctr: 1240 / 18000,
        position: 4.2,
        cost: null,
        conversions: null,
        cpc: null,
        cpa: null,
    },
    {
        keyword: 'product analytics',
        platform: 'GoogleAds',
        topImpressionRate: 0.72,
        absoluteTopImpressionRate: 0.38,
        matchType: 'exact',
        currency: 'USD',
        clicks: 840,
        impressions: 12000,
        cost: 1260,
        conversions: 42,
        ctr: 0.07,
        cpc: 1.5,
        cpa: 30,
    },
    {
        keyword: 'website analytics',
        platform: 'GoogleAds',
        topImpressionRate: 0.72,
        absoluteTopImpressionRate: 0.38,
        matchType: 'phrase',
        currency: 'USD',
        clicks: 520,
        impressions: 10400,
        cost: 1040,
        conversions: 26,
        ctr: 0.05,
        cpc: 2,
        cpa: 40,
    },
    {
        keyword: 'product analytics',
        platform: 'BingAds',
        topImpressionRate: 0.64,
        absoluteTopImpressionRate: 0.28,
        matchType: 'exact',
        currency: 'USD',
        clicks: 240,
        impressions: 6000,
        cost: 288,
        conversions: 12,
        ctr: 0.04,
        cpc: 1.2,
        cpa: 24,
    },
    {
        keyword: 'conversion tracking',
        platform: 'BingAds',
        topImpressionRate: 0.64,
        absoluteTopImpressionRate: 0.28,
        matchType: 'broad',
        currency: 'EUR',
        clicks: 80,
        impressions: 2000,
        cost: 96,
        conversions: 4.5,
        ctr: 0.04,
        cpc: 1.2,
        cpa: 96 / 4.5,
    },
    {
        keyword: 'analytics dashboard',
        platform: 'GoogleAds',
        topImpressionRate: 0.72,
        absoluteTopImpressionRate: 0.38,
        matchType: 'exact',
        currency: 'USD',
        clicks: 0,
        impressions: 250,
        cost: 0,
        conversions: 0,
        ctr: 0,
        cpc: null,
        cpa: null,
    },
]

const SEARCH_TERM_ROWS: MarketingAnalyticsSearchRow[] = [
    ['product analytics', 610, 9800, 915, 31],
    ['open source product analytics', 240, 2100, 312, 14],
    ['session replay tool', 185, 3900, 370, 6],
    ['feature flags pricing', 92, 1400, 138, 4.5],
].map(([keyword, clicks, impressions, cost, conversions]) => ({
    keyword: keyword as string,
    platform: 'GoogleAds',
    matchType: null,
    currency: 'USD',
    clicks: clicks as number,
    impressions: impressions as number,
    cost: cost as number,
    conversions: conversions as number,
    ctr: (clicks as number) / (impressions as number),
    cpc: (cost as number) / (clicks as number),
    cpa: (cost as number) / (conversions as number),
}))

type SearchTermTableStory = 'ready' | 'disabled' | 'syncing' | 'missing'

function searchTermSources(
    tables: Record<'search_term_stats' | 'performance_max_search_term_stats', SearchTermTableStory>
): typeof SOURCES {
    return SOURCES.map((source) =>
        source.source_type === 'GoogleAds'
            ? {
                  ...source,
                  schemas: [
                      ...source.schemas,
                      ...(Object.entries(tables)
                          .filter(([, state]) => state !== 'missing')
                          .map(([name, state]) => ({
                              id: `example-${name}`,
                              name,
                              should_sync: state !== 'disabled',
                              sync_frequency: '24hour',
                              last_synced_at: state === 'ready' ? '2025-02-14T12:00:00Z' : null,
                              status: state === 'syncing' ? 'Running' : 'Completed',
                              table:
                                  state === 'ready' ? { name: `example_${name}`, hogql_name: `example.${name}` } : null,
                          })) as typeof source.schemas),
                  ],
              }
            : source
    )
}

function searchTermMocks(
    tables: Record<'search_term_stats' | 'performance_max_search_term_stats', SearchTermTableStory>,
    channelTypes: string[]
): Mocks {
    const sources = searchTermSources(tables)
    return {
        get: {
            '/api/environments/:team_id/external_data_sources/': {
                results: sources,
                count: sources.length,
                next: null,
                previous: null,
            },
        },
        post: {
            '/api/environments/:team_id/query/HogQLQuery/': { results: [[channelTypes]] },
        },
        patch: {
            '/api/projects/:team_id/external_data_sources/:id/bulk_update_schemas/': [200, []],
        },
    }
}

const openSearchTerms = async ({ canvasElement }: { canvasElement: HTMLElement }): Promise<void> => {
    await userEvent.click(await within(canvasElement).findByText('Search terms', { exact: true }))
}

const MOCKS: Mocks = {
    delete: { '/api/projects/:team_id/query/:query_id/': [204] },
    get: {
        '/api/environments/:team_id/external_data_sources/wizard/': {
            GoogleAds: { name: 'GoogleAds', label: 'Google Ads', iconPath: IconGoogleAds, fields: [] },
            BingAds: { name: 'BingAds', label: 'Bing Ads', iconPath: IconBingAds, fields: [] },
            GoogleSearchConsole: {
                name: 'GoogleSearchConsole',
                label: 'Google Search Console',
                iconPath: IconGoogleSearchConsole,
                fields: [],
            },
        },
        '/api/environments/:team_id/external_data_sources/': {
            results: SOURCES,
            count: SOURCES.length,
            next: null,
            previous: null,
        },
    },
    post: {
        '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': async ({ request }) => {
            const { query } = (await request.json()) as { query: MarketingAnalyticsSearchQuery }
            return [
                200,
                {
                    posthogConversionGoals: query.includePostHogConversions
                        ? [
                              { id: 'signup', name: 'Signups' },
                              { id: 'purchase', name: 'Purchases' },
                          ]
                        : undefined,
                    posthogAttributionMode: query.includePostHogConversions ? AttributionMode.LastTouch : undefined,
                    results: (query.breakdown === 'page'
                        ? ROWS.filter((row) => row.clicks > 0).map((row) => ({
                              ...row,
                              page: `https://example.com/${row.keyword?.replaceAll(' ', '-')}`,
                              keyword: null,
                              matchType: null,
                          }))
                        : query.breakdown === 'search_term'
                          ? [...SEARCH_TERM_ROWS, ...ROWS.filter((row) => row.platform === 'GoogleSearchConsole')]
                          : ROWS
                    )
                        .filter(
                            (row) =>
                                query.sources.some((source) => source.sourceType === row.platform) &&
                                (row.page ?? row.keyword ?? '').includes((query.search ?? '').toLowerCase()) &&
                                (!query.keyword ||
                                    row.page === `https://example.com/${query.keyword.replaceAll(' ', '-')}`) &&
                                (!query.page ||
                                    `https://example.com/${row.keyword?.replaceAll(' ', '-')}` === query.page)
                        )
                        .map((row) => ({
                            ...row,
                            posthogConversions:
                                query.includePostHogConversions &&
                                (query.breakdown === 'page' || row.platform !== 'GoogleSearchConsole')
                                    ? [
                                          {
                                              id: 'signup',
                                              name: 'Signups',
                                              conversions: 24,
                                              costPerConversion: row.cost == null ? null : row.cost / 24,
                                              previousConversions: query.compareFilter?.compare ? 20 : null,
                                              previousCostPerConversion:
                                                  query.compareFilter?.compare && row.cost != null
                                                      ? (row.cost * 1.1) / 20
                                                      : null,
                                          },
                                          {
                                              id: 'purchase',
                                              name: 'Purchases',
                                              conversions: 6,
                                              costPerConversion: row.cost == null ? null : row.cost / 6,
                                              previousConversions: query.compareFilter?.compare ? 8 : null,
                                              previousCostPerConversion:
                                                  query.compareFilter?.compare && row.cost != null
                                                      ? (row.cost * 1.1) / 8
                                                      : null,
                                          },
                                      ]
                                    : undefined,
                            previous: query.compareFilter?.compare
                                ? {
                                      clicks: row.clicks * 0.8,
                                      topImpressionRate:
                                          row.topImpressionRate == null ? null : row.topImpressionRate - 0.08,
                                      absoluteTopImpressionRate:
                                          row.absoluteTopImpressionRate == null
                                              ? null
                                              : row.absoluteTopImpressionRate - 0.05,
                                      position: row.position == null ? null : row.position + 1.5,
                                      impressions: row.impressions * 0.9,
                                      cost: row.cost == null ? null : row.cost * 1.1,
                                      conversions: row.conversions == null ? null : row.conversions * 0.75,
                                      ctr: row.impressions ? (row.clicks * 0.8) / (row.impressions * 0.9) : null,
                                      cpc:
                                          row.cost != null && row.clicks ? (row.cost * 1.1) / (row.clicks * 0.8) : null,
                                      cpa:
                                          row.cost != null && row.conversions
                                              ? (row.cost * 1.1) / (row.conversions * 0.75)
                                              : null,
                                  }
                                : null,
                        })),
                },
            ]
        },
    },
}

const meta: Meta<typeof SearchPerformanceTab> = {
    title: 'Scenes-App/Marketing Analytics/Search performance',
    component: SearchPerformanceTab,
    beforeEach: () => {
        localStorage.removeItem('997__.scenes.webAnalytics.marketingAnalyticsLogic.integrationFilter')
        const originalNow = performance.now
        performance.now = () => 0
        return () => {
            performance.now = originalNow
        }
    },
    render: () => (
        <>
            <MarketingAnalyticsFilters tabs={<></>} />
            <SearchPerformanceTab />
        </>
    ),
    decorators: [
        mswDecorator({}),
        (Story) => (
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <Story />
            </BindLogic>
        ),
    ],
    parameters: {
        layout: 'fullscreen',
        mockDate: '2025-02-15T12:00:00Z',
        msw: { mocks: MOCKS },
        pageUrl: `${urls.marketingAnalyticsApp()}?tab=ad-performance&date_from=-7d`,
        featureFlags: [
            FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS,
            FEATURE_FLAGS.MARKETING_ANALYTICS_SEARCH_CONVERSIONS,
        ],
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const Connected: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?tab=ad-performance&compare=false` },
}
export const Pagination: Story = {
    parameters: {
        pageUrl: `${urls.marketingAnalyticsApp()}?tab=ad-performance&compare=true`,
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': async ({
                        request,
                    }: {
                        request: Request
                    }) => {
                        const { query } = (await request.json()) as { query: MarketingAnalyticsSearchQuery }
                        return [
                            200,
                            {
                                results: Array.from({ length: 23 }, (_, index) => ({
                                    ...ROWS[index % ROWS.length],
                                    previous: {
                                        clicks: 50,
                                        impressions: 1000,
                                        ctr: 0.05,
                                        cost: 100,
                                        conversions: 2,
                                        cpc: 2,
                                        cpa: 50,
                                        position: 5,
                                    },
                                    keyword: `Example keyword ${index + 1}`,
                                    page: query.breakdown === 'page' ? `https://example.com/page-${index + 1}` : null,
                                })),
                            },
                        ]
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('1-10 of 23 entries')
        await userEvent.click(canvas.getByRole('button', { name: 'Next page' }))
        await canvas.findByText('11-20 of 23 entries')
        const nextButton = canvas.getByRole('button', { name: 'Next page' })
        const arrowTop = nextButton.getBoundingClientRect().top
        await userEvent.click(canvas.getByRole('button', { name: 'Go to page' }))
        await userEvent.click(await within(canvasElement.ownerDocument.body).findByText('Page 3 of 3'))
        await canvas.findByText('21-23 of 23 entries')
        await expect(canvas.getByRole('button', { name: 'Next page' }).getBoundingClientRect().top).toBe(arrowTop)
        await userEvent.click(canvas.getByRole('button', { name: 'Landing pages' }))
        await canvas.findByText('1-10 of 23 entries')
        await userEvent.click(canvas.getByRole('button', { name: 'Next page' }))
        await canvas.findByText('11-20 of 23 entries')
        await userEvent.click(canvas.getByRole('button', { name: 'Keywords and queries' }))
        await expect(await canvas.findByText('1-10 of 23 entries')).toBeVisible()
    },
}
export const Comparison: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?tab=ad-performance&compare=true` },
    play: async ({ canvasElement }) => {
        await within(canvasElement).findByText('Google Search Console')
        const table = canvasElement.querySelector('.SearchPerformanceTable .LemonTable__content')!
        await expect(table.getBoundingClientRect().height).toBeLessThan(600)
    },
}
export const MixedWithPosition: Story = {
    ...Comparison,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByRole('columnheader', { name: /position|pos\./i })).toBeVisible()
        await expect(canvas.queryByRole('checkbox', { name: 'Show position' })).not.toBeInTheDocument()
    },
}
const ORGANIC_TRAFFIC_MOCKS = {
    get: {
        '/api/environments/:team_id/external_data_sources/': {
            results: SOURCES.filter((source) => source.source_type === 'GoogleSearchConsole'),
            count: 1,
            next: null,
            previous: null,
        },
    },
} satisfies Mocks

export const OrganicTraffic: Story = {
    ...Comparison,
    parameters: {
        ...Comparison.parameters,
        msw: {
            mocks: ORGANIC_TRAFFIC_MOCKS,
        },
    },
}
export const Narrow: Story = {
    ...Comparison,
    play: MixedWithPosition.play,
    parameters: { ...Comparison.parameters, layout: 'padded' },
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
export const LandingPages: Story = {
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Landing pages', { exact: true }))
    },
}
export const SearchTerms: Story = {
    parameters: {
        msw: {
            mocks: searchTermMocks({ search_term_stats: 'ready', performance_max_search_term_stats: 'ready' }, [
                'SEARCH',
                'PERFORMANCE_MAX',
            ]),
        },
    },
    play: async (context) => {
        await openSearchTerms(context)
        const canvas = within(context.canvasElement)
        await expect(await canvas.findByText('open source product analytics')).toBeVisible()
        expect(canvas.queryByText(/Enable/)).toBeNull()
    },
}
export const SearchTermsEnablePerformanceMax: Story = {
    parameters: {
        msw: {
            mocks: searchTermMocks({ search_term_stats: 'ready', performance_max_search_term_stats: 'disabled' }, [
                'SEARCH',
                'PERFORMANCE_MAX',
            ]),
        },
    },
    play: async (context) => {
        await openSearchTerms(context)
        const canvas = within(context.canvasElement)
        await expect(await canvas.findByText(/Enable the Performance Max search terms table/)).toBeVisible()
        await expect(
            await canvas.findByRole('button', { name: 'Enable Performance Max search terms table' })
        ).toBeVisible()
        await expect(await canvas.findByText('open source product analytics')).toBeVisible()
    },
}
export const SearchTermsSyncing: Story = {
    parameters: {
        msw: {
            mocks: searchTermMocks({ search_term_stats: 'missing', performance_max_search_term_stats: 'syncing' }, [
                'PERFORMANCE_MAX',
            ]),
        },
    },
    play: async (context) => {
        await openSearchTerms(context)
        await expect(
            await within(context.canvasElement).findByText(/The Performance Max search terms table is syncing/)
        ).toBeVisible()
    },
}
export const SearchTermsMissingTable: Story = {
    parameters: {
        msw: {
            mocks: searchTermMocks({ search_term_stats: 'disabled', performance_max_search_term_stats: 'missing' }, [
                'SEARCH',
                'PERFORMANCE_MAX',
            ]),
        },
    },
    play: async (context) => {
        await openSearchTerms(context)
        const canvas = within(context.canvasElement)
        await expect(await canvas.findByText(/Pull new schemas/)).toBeVisible()
        await expect(await canvas.findByRole('button', { name: 'Enable search terms table' })).toBeVisible()
    },
}
export const SearchTermsNarrow: Story = {
    ...SearchTermsEnablePerformanceMax,
    decorators: Narrow.decorators,
}
export const OrganicDetail: Story = {
    ...Comparison,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const keywords = await canvas.findAllByRole('button', { name: 'product analytics' })
        await userEvent.click(keywords[0])
    },
}
export const NotConnected: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': {
                        results: [],
                        count: 0,
                        next: null,
                        previous: null,
                    },
                },
            },
        },
    },
}
export const AwaitingSync: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': {
                        results: SOURCES.map((source) => ({
                            ...source,
                            schemas: source.schemas.map((schema) => ({ ...schema, table: null, last_synced_at: null })),
                        })),
                        count: SOURCES.length,
                        next: null,
                        previous: null,
                    },
                },
            },
        },
    },
}
export const StaleAggregate: Story = {
    parameters: {
        ...Comparison.parameters,
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': {
                        results: SOURCES.map((source) => ({
                            ...source,
                            schemas: source.schemas.map((schema) => ({
                                ...schema,
                                last_synced_at:
                                    schema.name === 'search_analytics_by_query'
                                        ? '2025-02-01T12:00:00Z'
                                        : schema.last_synced_at,
                            })),
                        })),
                        count: SOURCES.length,
                        next: null,
                        previous: null,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText(/search_analytics_by_query is out of date/)).toBeVisible()
        await expect(await canvas.findByText('840')).toBeVisible()
        await expect(canvas.queryByText('1,240')).toBeNull()
    },
}
export const UnavailableSources: Story = {
    parameters: {
        ...Comparison.parameters,
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': {
                        results: SOURCES.map((source) => ({
                            ...source,
                            schemas: source.schemas.map((schema) => ({
                                ...schema,
                                should_sync: source.source_type !== 'GoogleAds',
                                last_synced_at: source.source_type === 'BingAds' ? null : '2025-02-01T12:00:00Z',
                            })),
                        })),
                        count: SOURCES.length,
                        next: null,
                        previous: null,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText("Some search tables aren't ready")).toBeVisible()
        await expect(await canvas.findByText(/Enable keyword and keyword_stats/)).toBeVisible()
        for (const header of canvas.getAllByRole('button', { name: /1 connection/ })) {
            if (header.getAttribute('aria-expanded') === 'false') {
                await userEvent.click(header)
            }
        }
        await expect(await canvas.findByText(/Waiting for the first sync/)).toBeVisible()
        await expect(await canvas.findByText(/out of date/)).toBeVisible()
        expect(canvas.queryByRole('table')).toBeNull()
    },
}
export const UnavailableSourcesNarrow: Story = {
    ...UnavailableSources,
    decorators: Narrow.decorators,
}
const ONLY_GOOGLE_ADS_MOCKS = {
    get: {
        '/api/environments/:team_id/external_data_sources/': {
            results: SOURCES.filter((source) => source.source_type === 'GoogleAds'),
            count: 1,
            next: null,
            previous: null,
        },
    },
} satisfies Mocks

export const OnlyGoogleAds: Story = {
    parameters: {
        msw: {
            mocks: ONLY_GOOGLE_ADS_MOCKS,
        },
    },
}
export const PlacementUnavailable: Story = {
    parameters: {
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': {
                        results: ROWS.map((row) =>
                            row.platform === 'GoogleAds'
                                ? { ...row, topImpressionRate: null, absoluteTopImpressionRate: null }
                                : row
                        ),
                        placementUnavailable: true,
                    },
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(canvas.findByText(/Some Google Ads position data is unavailable/)).resolves.toBeVisible()
        expect((await canvas.findAllByRole('button', { name: 'product analytics' })).length).toBeGreaterThan(0)
    },
}
const EMPTY_MOCKS = {
    post: { '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': { results: [] } },
} satisfies Mocks

export const Empty: Story = {
    parameters: {
        msw: {
            mocks: EMPTY_MOCKS,
        },
    },
}
export const FilteredEmpty: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.type(await canvas.findByPlaceholderText('Filter keywords and queries'), 'no matching keyword')
        await canvas.findByText('No search data matches your filters. Try clearing them to see more results.')
        await expect(canvas.getByRole('button', { name: 'Clear filters' })).toBeVisible()
    },
}
export const EmptyGoogleAds: Story = {
    parameters: {
        msw: {
            mocks: {
                get: ONLY_GOOGLE_ADS_MOCKS.get,
                post: EMPTY_MOCKS.post,
            },
        },
    },
}
export const EmptyOrganic: Story = {
    parameters: {
        msw: {
            mocks: {
                get: ORGANIC_TRAFFIC_MOCKS.get,
                post: EMPTY_MOCKS.post,
            },
        },
    },
}
const pendingLoadingQueries = new Set<() => void>()

export const Loading: Story = {
    beforeEach: () => () => {
        // Release the query slot so the loading fixture cannot block later stories.
        pendingLoadingQueries.forEach((resolve) => resolve())
        pendingLoadingQueries.clear()
    },
    parameters: {
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': async () => {
                        await new Promise<void>((resolve) => pendingLoadingQueries.add(resolve))
                        return { results: [] }
                    },
                },
            },
        },
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export const QueryError: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByText('00000000-0000-4000-8000-000000000000')).toBeVisible()
        await expect(canvas.getByRole('button', { name: 'Retry' })).toBeVisible()
    },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="marketing-search-performance"] .LemonBanner--error',
        },
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': [
                        500,
                        { detail: 'Query failed' },
                    ],
                },
            },
        },
    },
}
export const SourcesError: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="marketing-search-performance"] .LemonBanner--error',
        },
        msw: {
            mocks: {
                get: { '/api/environments/:team_id/external_data_sources/': [500, { detail: 'Sources unavailable' }] },
            },
        },
    },
}
export const LegacyScene: Story = {
    render: () => <MarketingAnalyticsScene />,
    parameters: {
        pageUrl: `${urls.marketingAnalyticsApp()}?tab=ad-performance`,
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING, FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS],
    },
}
export const FlagOff: Story = {
    ...LegacyScene,
    parameters: { ...LegacyScene.parameters, featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING] },
}

export const PositionMetrics: Story = {
    ...Comparison,
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await expect(await canvas.findByRole('columnheader', { name: /position|pos\./i })).toBeVisible()
        await expect(await canvas.findAllByText('72.0%')).not.toHaveLength(0)
        await expect(await canvas.findAllByText('38.0%')).not.toHaveLength(0)
        await expect(await canvas.findAllByText('64.0%')).not.toHaveLength(0)
        await expect(await canvas.findAllByText('28.0%')).not.toHaveLength(0)
        await expect(canvas.queryByRole('button', { name: 'Visibility' })).not.toBeInTheDocument()
        const topLabel = (await canvas.findAllByText('Top'))[0]
        topLabel.scrollIntoView({ block: 'center', inline: 'center' })
        topLabel.focus()
        await userEvent.tab({ shift: true })
        await userEvent.tab()
        await expect(topLabel).toHaveFocus()
        await waitFor(() =>
            expect(
                within(document.body).getByText(
                    'Percentage of Google Search ad impressions shown among the top ads. Excludes Search partners. Requires a sync with ad placement data.'
                )
            ).toBeVisible()
        )
        await userEvent.tab()
        await expect((await canvas.findAllByText('72.0%'))[0].parentElement).toHaveFocus()
        await waitFor(() =>
            expect(
                within(document.body).getByText(
                    'Percentage of Google Search ad impressions shown among the top ads. Excludes Search partners.'
                )
            ).toBeVisible()
        )
        await userEvent.tab()
        const firstLabel = (await canvas.findAllByText('First'))[0]
        await expect(firstLabel).toHaveFocus()
        await waitFor(() =>
            expect(
                within(document.body).getByText(
                    'Percentage of Google Search ad impressions shown as the first ad. Excludes Search partners. Requires a sync with ad placement data.'
                )
            ).toBeVisible()
        )
        await userEvent.keyboard('{Escape}')
        firstLabel.blur()
        await userEvent.hover(topLabel)
        await waitFor(() =>
            expect(
                within(document.body).getByText(
                    'Percentage of Google Search ad impressions shown among the top ads. Excludes Search partners. Requires a sync with ad placement data.'
                )
            ).toBeVisible()
        )
    },
}
export const NarrowPositionMetrics: Story = {
    ...Narrow,
    play: PositionMetrics.play,
}

export const PostHogConversions: Story = {
    ...Comparison,
    parameters: {
        ...Comparison.parameters,
        msw: {
            mocks: {
                ...MOCKS,
                post: {
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': async (
                        info: MockResolverInfo
                    ) => {
                        const resolver = MOCKS.post!['/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/']
                        const result = typeof resolver === 'function' ? await resolver(info) : resolver
                        const [status, response] = result as [number, { results: MarketingAnalyticsSearchRow[] }]
                        return [
                            status,
                            {
                                ...response,
                                results: response.results.map((row) => ({
                                    ...row,
                                    page: row.page
                                        ? `${row.page}/guides/understanding-search-performance-and-conversion-attribution?campaign=organic-search`
                                        : row.page,
                                })),
                            },
                        ]
                    },
                },
            },
        },
    },
    render: function Render(): JSX.Element {
        const { includeConversionGoals } = useValues(marketingAnalyticsLogic)
        const { setAdPerformanceConversionGoals } = useActions(marketingAnalyticsLogic)
        return (
            <>
                <MarketingAnalyticsFilters tabs={<></>} />
                <LemonSwitch
                    className="mb-4"
                    label="Include conversion goals"
                    checked={includeConversionGoals}
                    onChange={setAdPerformanceConversionGoals}
                />
                <SearchPerformanceTab />
            </>
        )
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByRole('button', { name: 'Landing pages' }))
        await userEvent.click(await canvas.findByRole('button', { name: 'Conversions' }))
        teamLogic.actions.loadCurrentTeamSuccess({
            ...teamLogic.values.currentTeam!,
            marketing_analytics_config: {
                conversion_goals: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'purchase',
                        conversion_goal_id: 'purchase-goal',
                        conversion_goal_name: 'Purchases',
                        schema_map: {},
                    },
                ],
            },
        })
        await expect(canvas.findByRole('columnheader', { name: /Cost per Purchases/ })).resolves.toBeVisible()
        await userEvent.click(canvas.getByRole('switch', { name: 'Include conversion goals' }))
        await waitFor(() =>
            expect(canvas.queryByRole('columnheader', { name: /Cost per Purchases/ })).not.toBeInTheDocument()
        )
        await expect(canvas.findByRole('columnheader', { name: /Reported conversions/ })).resolves.toBeVisible()
        await userEvent.click(canvas.getByRole('switch', { name: 'Include conversion goals' }))
        await expect(canvas.findByRole('columnheader', { name: /Cost per Purchases/ })).resolves.toBeVisible()
    },
}

export const PostHogConversionsFlagOff: Story = {
    ...PostHogConversions,
    parameters: {
        ...PostHogConversions.parameters,
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS],
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        teamLogic.actions.loadCurrentTeamSuccess({
            ...teamLogic.values.currentTeam!,
            marketing_analytics_config: {
                conversion_goals: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'purchase',
                        conversion_goal_id: 'purchase-goal',
                        conversion_goal_name: 'Purchases',
                        schema_map: {},
                    },
                ],
            },
        })
        await userEvent.click(await canvas.findByText('Landing pages'))
        await userEvent.click(await canvas.findByText('Conversions'))
        await expect(canvas.findByText('Reported conversions')).resolves.toBeVisible()
        expect(canvas.queryByText('Cost per Purchases')).not.toBeInTheDocument()
    },
}

export const PostHogConversionsNarrow: Story = {
    ...PostHogConversions,
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}

export const KeywordPostHogConversions: Story = {
    ...PostHogConversions,
    play: async (context) => {
        await PostHogConversions.play?.(context)
        const canvas = within(context.canvasElement)
        await userEvent.click(canvas.getByRole('button', { name: 'Keywords and queries' }))
        await expect(canvas.findByText(/Paid keywords are matched/)).resolves.toBeVisible()
        await expect(canvas.findByRole('columnheader', { name: /Cost per Purchases/ })).resolves.toBeVisible()
    },
}

export const KeywordPostHogConversionsNarrow: Story = {
    ...KeywordPostHogConversions,
    decorators: PostHogConversionsNarrow.decorators,
}

function conversionLoadingMock(state: 'loading' | 'error'): MockSignature {
    return async (info) => {
        const { query } = (await info.request.clone().json()) as { query: MarketingAnalyticsSearchQuery }
        if (query.includePostHogConversions) {
            if (state === 'loading') {
                await new Promise<void>((resolve) => pendingLoadingQueries.add(resolve))
                return { results: [] }
            }
            return [500, { detail: 'Could not calculate conversions' }]
        }
        const resolver = MOCKS.post!['/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/']
        return typeof resolver === 'function' ? resolver(info) : resolver
    }
}

async function showPostHogConversionColumns(canvasElement: HTMLElement): Promise<void> {
    teamLogic.actions.loadCurrentTeamSuccess({
        ...teamLogic.values.currentTeam!,
        marketing_analytics_config: {
            conversion_goals: [
                {
                    kind: NodeKind.EventsNode,
                    event: 'purchase',
                    conversion_goal_id: 'purchase',
                    conversion_goal_name: 'Purchases',
                    schema_map: {},
                },
            ],
        },
    })
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByRole('button', { name: 'Landing pages' }))
    await userEvent.click(await canvas.findByRole('button', { name: 'Conversions' }))
    await expect(
        (await canvas.findAllByRole('cell', { name: /https:\/\/example.com\/product-analytics/ }))[0]
    ).toBeVisible()
}

export const PostHogConversionsLoading: Story = {
    ...PostHogConversions,
    beforeEach: Loading.beforeEach,
    parameters: {
        ...PostHogConversions.parameters,
        testOptions: { waitForLoadersToDisappear: false },
        msw: {
            mocks: {
                ...MOCKS,
                post: {
                    ...MOCKS.post,
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': conversionLoadingMock('loading'),
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        await showPostHogConversionColumns(canvasElement)
        await expect(within(canvasElement).findByText('Loading PostHog conversions…')).resolves.toBeVisible()
    },
}

export const PostHogConversionsError: Story = {
    ...PostHogConversions,
    parameters: {
        ...PostHogConversions.parameters,
        msw: {
            mocks: {
                ...MOCKS,
                post: {
                    ...MOCKS.post,
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': conversionLoadingMock('error'),
                },
            },
        },
    },
    play: async ({ canvasElement }) => {
        await showPostHogConversionColumns(canvasElement)
        await expect(
            within(canvasElement).findByText('Could not load PostHog conversions. Your search data is still available.')
        ).resolves.toBeVisible()
        await expect(within(canvasElement).findByText('00000000-0000-4000-8000-000000000000')).resolves.toBeVisible()
    },
}

export const WrappedLandingPages: Story = {
    ...PostHogConversions,
    play: async (context) => {
        await PostHogConversions.play?.(context)
        const canvas = within(context.canvasElement)
        await userEvent.click(canvas.getByRole('button', { name: 'Table options' }))
        await userEvent.click(within(document.body).getByRole('switch', { name: 'Wrap text' }))
        await userEvent.keyboard('{Escape}')
    },
}

export const WrappedLandingPagesNarrow: Story = {
    ...WrappedLandingPages,
    decorators: PostHogConversionsNarrow.decorators,
}
