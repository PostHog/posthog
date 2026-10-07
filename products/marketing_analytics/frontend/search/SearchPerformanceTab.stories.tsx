import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
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
import { Mocks } from '~/mocks/utils'
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
        schemas: ['campaign', 'campaign_overview_stats', 'keyword', 'keyword_stats', 'landing_page_stats'].map(
            (name) => ({
                id: `example-${name}`,
                name,
                should_sync: true,
                sync_frequency: '24hour',
                last_synced_at: '2025-02-14T12:00:00Z',
                status: 'Completed',
                table: { name: `example_${name}`, hogql_name: `example.${name}` },
            })
        ),
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

const MOCKS: Mocks = {
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
                            posthogConversions: query.includePostHogConversions
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
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS],
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
        await userEvent.click(await within(canvasElement).findByRole('checkbox', { name: 'Show position' }))
    },
}
export const OrganicTraffic: Story = {
    ...Comparison,
    parameters: {
        ...Comparison.parameters,
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': {
                        results: SOURCES.filter((source) => source.source_type === 'GoogleSearchConsole'),
                        count: 1,
                        next: null,
                        previous: null,
                    },
                },
            },
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
        await expect(await canvas.findByText(/Showing query-and-page data instead/)).toBeVisible()
        await expect(await canvas.findByText('1,240')).toBeVisible()
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
        await expect(await canvas.findByText(/Enable keyword and keyword_stats/)).toBeVisible()
        await expect(await canvas.findByText(/Waiting for the first sync/)).toBeVisible()
        await expect(await canvas.findByText(/out of date/)).toBeVisible()
        expect(canvas.queryByRole('table')).toBeNull()
    },
}
export const UnavailableSourcesNarrow: Story = {
    ...UnavailableSources,
    decorators: Narrow.decorators,
}
export const OnlyGoogleAds: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/external_data_sources/': {
                        results: SOURCES.filter((source) => source.source_type === 'GoogleAds'),
                        count: 1,
                        next: null,
                        previous: null,
                    },
                },
            },
        },
    },
}
export const Empty: Story = {
    parameters: {
        msw: {
            mocks: { post: { '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': { results: [] } } },
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
                get: OnlyGoogleAds.parameters!.msw.mocks.get,
                post: Empty.parameters!.msw.mocks.post,
            },
        },
    },
}
export const EmptyOrganic: Story = {
    parameters: {
        msw: {
            mocks: {
                get: OrganicTraffic.parameters!.msw.mocks.get,
                post: Empty.parameters!.msw.mocks.post,
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
export const NewDashboardScene: Story = {
    ...LegacyScene,
    parameters: {
        ...LegacyScene.parameters,
        featureFlags: [
            FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
            FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD,
            FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS,
        ],
    },
}
export const FlagOff: Story = {
    ...LegacyScene,
    parameters: { ...LegacyScene.parameters, featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING] },
}
export const NewDashboardFlagOff: Story = {
    ...LegacyScene,
    parameters: {
        ...LegacyScene.parameters,
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING, FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD],
    },
}

export const PostHogConversions: Story = {
    ...Comparison,
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
        await expect(canvas.queryByRole('columnheader', { name: /Cost per Purchases/ })).not.toBeInTheDocument()
        await expect(canvas.getByRole('columnheader', { name: /Reported conversions/ })).toBeVisible()
        await userEvent.click(canvas.getByRole('switch', { name: 'Include conversion goals' }))
        await expect(canvas.findByRole('columnheader', { name: /Cost per Purchases/ })).resolves.toBeVisible()
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
