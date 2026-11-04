import { Meta, StoryObj } from '@storybook/react'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { MarketingAnalyticsOverview } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsOverview/MarketingAnalyticsOverview'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsTilesLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import { MarketingAnalyticsTrendTile } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { useStorybookMocks } from '~/mocks/browser'
import {
    DatabaseSchemaDataWarehouseTable,
    InsightVizNode,
    MARKETING_INTEGRATION_CONFIGS,
    MarketingAnalyticsAggregatedQueryResponse,
    NodeKind,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { ExternalDataSource } from '~/types'

const days = ['2026-09-10', '2026-09-11', '2026-09-12', '2026-09-13', '2026-09-14', '2026-09-15', '2026-09-16']
const data: Record<string, number[]> = {
    cost: [2200, 2600, 2100, 3100, 3000, 2400, 2800],
    clicks: [1200, 1400, 1000, 1800, 1500, 1300, 1400],
    impressions: [80000, 90000, 70000, 110000, 100000, 90000, 100000],
    reported_conversion: [40, 50, 30, 70, 60, 45, 55],
    reported_conversion_value: [11000, 13000, 9000, 16000, 15000, 12000, 15000],
}
for (const [metric, numerator, denominator, scale] of [
    ['cpc', 'cost', 'clicks', 1],
    ['ctr', 'clicks', 'impressions', 100],
    ['roas', 'reported_conversion_value', 'cost', 1],
    ['cost_per_reported_conversion', 'cost', 'reported_conversion', 1],
] as const) {
    data[metric] = data[numerator].map((value, index) => (value / data[denominator][index]) * scale)
}

const schemaNames = [
    MARKETING_INTEGRATION_CONFIGS.GoogleAds.campaignTableName,
    MARKETING_INTEGRATION_CONFIGS.GoogleAds.statsTableName,
]
const source = {
    id: 'example-google-ads',
    source_type: 'GoogleAds',
    prefix: 'example',
    status: 'Completed',
    schemas: schemaNames.map((name) => ({ id: `example-${name}`, name, should_sync: true, status: 'Completed' })),
} as ExternalDataSource
const tables = Object.fromEntries(
    schemaNames.map((name) => [
        name,
        {
            id: `table-${name}`,
            name,
            type: 'data_warehouse',
            schema: { id: `example-${name}`, name, should_sync: true, incremental: false },
            fields: Object.fromEntries(
                [
                    'campaign_id',
                    'id',
                    'name',
                    'segments_date',
                    'customer_currency_code',
                    'metrics_cost_micros',
                    'metrics_clicks',
                    'metrics_impressions',
                    'metrics_conversions',
                    'metrics_conversions_value',
                ].map((field) => [field, { name: field, hogql_value: field, type: 'float', schema_valid: true }])
            ),
        } satisfies DatabaseSchemaDataWarehouseTable,
    ])
)

const summary: MarketingAnalyticsAggregatedQueryResponse = {
    results: {
        Cost: {
            key: 'Cost',
            value: 18200,
            previous: 20000,
            changeFromPreviousPct: -9,
            kind: 'currency',
            isIncreaseBad: true,
        },
        Clicks: { key: 'Clicks', value: 9600, previous: 8000, changeFromPreviousPct: 20, kind: 'unit' },
        Impressions: { key: 'Impressions', value: 640000, previous: 600000, changeFromPreviousPct: 7, kind: 'unit' },
        'Reported Conversions': {
            key: 'Reported Conversions',
            value: 350,
            previous: 300,
            changeFromPreviousPct: 17,
            kind: 'unit',
        },
        'Reported Conversion Value': {
            key: 'Reported Conversion Value',
            value: 91000,
            previous: 75000,
            changeFromPreviousPct: 21,
            kind: 'currency',
        },
        'Trial started': { key: 'Trial started', value: 620, previous: 540, changeFromPreviousPct: 15, kind: 'unit' },
        'Demo booked': { key: 'Demo booked', value: 84, previous: 70, changeFromPreviousPct: 20, kind: 'unit' },
        CPC: {
            key: 'CPC',
            value: 1.9,
            previous: 2.5,
            changeFromPreviousPct: -24,
            kind: 'currency',
            isIncreaseBad: true,
        },
        CTR: { key: 'CTR', value: 1.5, previous: 1.33, changeFromPreviousPct: 13, kind: 'percentage' },
        'Cost per Reported Conversions': {
            key: 'Cost per Reported Conversions',
            value: 52,
            previous: 66.67,
            changeFromPreviousPct: -22,
            kind: 'currency',
            isIncreaseBad: true,
        },
        'Reported ROAS': { key: 'Reported ROAS', value: 5, previous: 3.75, changeFromPreviousPct: 33, kind: 'unit' },
        'Cost per Trial started': { key: 'Cost per Trial started', value: 29.35, kind: 'currency' },
        'Cost per Demo booked': { key: 'Cost per Demo booked', value: 216.67, kind: 'currency' },
    },
}

const meta: Meta<typeof MarketingAnalyticsOverview> = {
    title: 'Marketing Analytics/Ad performance metric trends',
    component: MarketingAnalyticsOverview,
    parameters: { layout: 'padded', mockDate: '2026-09-16', featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING] },
    args: {
        query: {
            kind: NodeKind.MarketingAnalyticsAggregatedQuery,
            properties: [],
            dateRange: { date_from: '2026-09-10', date_to: '2026-09-16' },
        },
        cachedResults: summary,
        context: {},
        uniqueKey: 'ad-performance-trends-story',
    },
}
export default meta
type Story = StoryObj<typeof MarketingAnalyticsOverview>

export const WithTrends: Story = {
    render: function Render(args) {
        const { loadSourcesSuccess, setDatesAndInterval } = useActions(marketingAnalyticsLogic)
        const { marketingChartTile } = useValues(marketingAnalyticsTilesLogic)
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/external_data_sources/wizard/': {},
                '/api/environments/:team_id/external_data_sources/': {
                    count: 1,
                    results: [source],
                    next: null,
                    previous: null,
                },
                '/api/projects/:team_id/marketing_analytics/source_validation/': { errors_by_source: {} },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: TrendsQuery }
                    if (query.kind === (NodeKind.DatabaseSchemaQuery as string)) {
                        return [200, { tables, joins: [] }]
                    }
                    return [
                        200,
                        {
                            results: (query.series ?? []).map((series, index) => {
                                const metric =
                                    series.custom_name && data[series.custom_name]
                                        ? series.custom_name
                                        : marketingAnalyticsLogic.values.tileColumnSelection
                                return {
                                    order: index,
                                    label: series.custom_name ?? metric,
                                    days,
                                    dates: days,
                                    labels: days,
                                    data: data[metric] ?? data.cost,
                                    count: (data[metric] ?? data.cost).reduce((total, value) => total + value, 0),
                                    aggregated_value: (data[metric] ?? data.cost).reduce(
                                        (total, value) => total + value,
                                        0
                                    ),
                                }
                            }),
                        },
                    ]
                },
            },
        })
        useEffect(() => {
            loadSourcesSuccess({ count: 1, results: [source], next: null, previous: null })
            databaseTableListLogic.actions.loadDatabaseSuccess({ tables, joins: [] })
            setDatesAndInterval('2026-09-10', '2026-09-16', 'day')
        }, [loadSourcesSuccess, setDatesAndInterval])
        return (
            <div className="flex flex-col gap-4">
                <MarketingAnalyticsOverview {...args} />
                <MarketingAnalyticsTrendTile
                    query={marketingChartTile.query as InsightVizNode}
                    insightProps={marketingChartTile.insightProps}
                    uniqueKey="ad-performance-main-trend-story"
                    showIntervalTile
                />
            </div>
        )
    },
}
