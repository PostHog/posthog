import { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { MarketingAnalyticsScene } from 'scenes/marketing-analytics/MarketingAnalyticsScene'
import { urls } from 'scenes/urls'
import { MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

import { mswDecorator } from '~/mocks/browser'
import { Mocks } from '~/mocks/utils'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { MarketingAnalyticsSearchQuery, MarketingAnalyticsSearchRow } from '~/queries/schema/schema-general'

import IconBingAds from 'public/services/bing-ads.svg'
import IconGoogleAds from 'public/services/google-ads.png'

import { SearchPerformanceTab } from './SearchPerformanceTab'

const SOURCES = [
    {
        id: 'example-google',
        source_type: 'GoogleAds',
        description: 'Example Google Ads',
        prefix: 'example',
        status: 'Completed',
        schemas: ['keyword', 'keyword_stats'].map((name) => ({
            id: `example-${name}`,
            name,
            should_sync: true,
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
            {
                id: 'example-bing-keywords',
                name: 'keyword_performance_report',
                should_sync: true,
                table: { name: 'example_bing_keywords', hogql_name: 'example.bing_keywords' },
            },
        ],
    },
]

const ROWS: MarketingAnalyticsSearchRow[] = [
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
        },
        '/api/environments/:team_id/external_data_sources/': { results: SOURCES, count: 2, next: null, previous: null },
    },
    post: {
        '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': async ({ request }) => {
            const { query } = (await request.json()) as { query: MarketingAnalyticsSearchQuery }
            return [
                200,
                {
                    results: ROWS.filter(
                        (row) =>
                            query.sources.some((source) => source.sourceType === row.platform) &&
                            (row.keyword ?? '').includes((query.search ?? '').toLowerCase())
                    ).map((row) => ({
                        ...row,
                        previous: query.compareFilter?.compare
                            ? {
                                  clicks: row.clicks * 0.8,
                                  impressions: row.impressions * 0.9,
                                  cost: row.cost * 1.1,
                                  conversions: row.conversions * 0.75,
                                  ctr: row.impressions ? (row.clicks * 0.8) / (row.impressions * 0.9) : null,
                                  cpc: row.clicks ? (row.cost * 1.1) / (row.clicks * 0.8) : null,
                                  cpa: row.conversions ? (row.cost * 1.1) / (row.conversions * 0.75) : null,
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
    decorators: [
        mswDecorator({}),
        (Story) => (
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <Story />
            </BindLogic>
        ),
    ],
    parameters: { layout: 'padded', msw: { mocks: MOCKS } },
}
export default meta
type Story = StoryObj<typeof meta>

export const Connected: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?tab=search-performance&compare=false` },
}
export const Comparison: Story = {
    parameters: { pageUrl: `${urls.marketingAnalyticsApp()}?tab=search-performance&compare=true` },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
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
                            schemas: source.schemas.map((schema) => ({ ...schema, table: null })),
                        })),
                        count: 2,
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
export const Loading: Story = {
    parameters: {
        msw: {
            mocks: {
                post: {
                    '/api/environments/:team_id/query/MarketingAnalyticsSearchQuery/': () => new Promise(() => {}),
                },
            },
        },
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export const QueryError: Story = {
    parameters: {
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
        pageUrl: `${urls.marketingAnalyticsApp()}?tab=search-performance`,
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
