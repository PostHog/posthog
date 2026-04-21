import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'

import DatabaseSchemaQuery from '../__mocks__/DatabaseSchemaQuery.json'

const getEffectiveQueryKind = (req: {
    body?: { query?: { kind?: string; source?: { kind?: string } } }
}): string | undefined => req.body?.query?.source?.kind ?? req.body?.query?.kind

const EMPTY_REVENUE_EXAMPLE_QUERY_RESPONSE = {
    results: [],
    hasMore: false,
    columns: [],
    types: [],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management/Revenue Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-01',
        pageUrl: urls.revenueSettings(),
        testOptions: {
            waitForSelector: ['[data-attr="scene-name"]', '.LemonTabs'],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => {
                    return [
                        200,
                        {
                            ...EMPTY_PAGINATED_RESPONSE,
                            results: [
                                externalDataSourceResponseMock,
                                {
                                    ...externalDataSourceResponseMock,
                                    prefix: 'dev_',
                                    revenue_analytics_config: {
                                        enabled: false,
                                        include_invoiceless_charges: true,
                                    },
                                },
                            ],
                        },
                    ]
                },
                '/api/environments/:team_id/external_data_sources/wizard': () => {
                    return [
                        200,
                        {
                            Stripe: {
                                iconPath: '/static/services/stripe.png',
                            },
                        },
                    ]
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind': (req) => {
                    const queryKind = getEffectiveQueryKind(req)

                    if (queryKind === 'DatabaseSchemaQuery') {
                        return [200, DatabaseSchemaQuery]
                    }
                    if (
                        queryKind === 'RevenueExampleEventsQuery' ||
                        queryKind === 'RevenueExampleDataWarehouseTablesQuery'
                    ) {
                        return [200, EMPTY_REVENUE_EXAMPLE_QUERY_RESPONSE]
                    }
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const Settings: Story = {}
