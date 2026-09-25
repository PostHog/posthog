import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { MarketingAnalyticsSourceStatusBanner } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'

import { mswDecorator } from '~/mocks/browser'
import { DatabaseSchemaDataWarehouseTable, MARKETING_INTEGRATION_CONFIGS } from '~/queries/schema/schema-general'

const table: DatabaseSchemaDataWarehouseTable = {
    id: 'example-insights-table',
    name: 'openai_campaign_insights',
    type: 'data_warehouse',
    schema: { id: 'example-insights', name: 'campaign_insights', should_sync: true, incremental: false },
    fields: Object.fromEntries(
        ['campaign_id', 'start_time', 'impressions', 'clicks', 'spend'].map((name) => [
            name,
            { name, hogql_value: name, type: 'string', schema_valid: true },
        ])
    ),
}

const meta: Meta<typeof MarketingAnalyticsSourceStatusBanner> = {
    title: 'Scenes-App/Marketing Analytics/Source status',
    component: MarketingAnalyticsSourceStatusBanner,
    render: () => (
        <div id="source-status-snapshot" className="w-200 max-w-[calc(100vw-2rem)]">
            <MarketingAnalyticsSourceStatusBanner />
        </div>
    ),
    parameters: {
        featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_OPENAI_ADS],
        testOptions: {
            waitForSelector: '[data-attr="marketing-source-status-settings"][href*="managed-example-openai-source"]',
            snapshotTargetSelector: '#source-status-snapshot',
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/marketing_analytics/source_validation/': () => [
                    200,
                    {
                        errors_by_source: {
                            'example-openai-source': [
                                "OpenAI Ads is missing 'currency_code' in 'openai_campaign_insights'. Sync this table again.",
                            ],
                        },
                    },
                ],
                '/api/projects/:team_id/external_data_sources/wizard/': () => [200, {}],
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    {
                        count: 2,
                        next: null,
                        previous: null,
                        results: [
                            {
                                id: 'example-google-source',
                                source_type: 'GoogleAds',
                                status: 'Cancelled',
                                schemas: [
                                    MARKETING_INTEGRATION_CONFIGS.GoogleAds.campaignTableName,
                                    MARKETING_INTEGRATION_CONFIGS.GoogleAds.statsTableName,
                                ].map((name) => ({
                                    id: `example-google-${name}`,
                                    name,
                                    should_sync: true,
                                    status: 'Cancelled',
                                })),
                            },
                            {
                                id: 'example-openai-source',
                                source_type: 'OpenAIAds',
                                status: 'Completed',
                                schemas: [
                                    {
                                        id: 'example-campaigns',
                                        name: 'campaigns',
                                        should_sync: true,
                                        status: 'Completed',
                                    },
                                    {
                                        id: 'example-insights',
                                        name: 'campaign_insights',
                                        should_sync: true,
                                        status: 'Completed',
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            post: {
                '/api/environments/:team_id/query/:kind': () => [200, { tables: { [table.name]: table }, joins: [] }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof MarketingAnalyticsSourceStatusBanner>
export const SourceIssues: Story = {}
