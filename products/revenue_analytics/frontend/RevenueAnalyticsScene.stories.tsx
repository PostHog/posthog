import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { RevenueAnalyticsBreakdown } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, RevenueAnalyticsPropertyFilter } from '~/types'

import databaseSchemaMock from './__mocks__/DatabaseSchemaQuery.json'
import revenueAnalyticsGrossRevenueQueryMock from './__mocks__/RevenueAnalyticsGrossRevenueQuery.json'
import revenueAnalyticsMRRQueryMock from './__mocks__/RevenueAnalyticsMRRQuery.json'
import revenueAnalyticsMetricsQueryMock from './__mocks__/RevenueAnalyticsMetricsQuery.json'
import revenueAnalyticsOverviewMock from './__mocks__/RevenueAnalyticsOverviewQuery.json'
import revenueAnalyticsTopCustomersMock from './__mocks__/RevenueAnalyticsTopCustomersQuery.json'
import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Revenue Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: urls.revenueAnalytics(),
        testOptions: {
            waitForLoadersToDisappear: true,
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
                            results: [externalDataSourceResponseMock],
                        },
                    ]
                },
            },
            post: {
                '/api/environments/:team_id/query': (req) => {
                    const query = (req.body as any).query
                    const queryKind = query.kind

                    if (queryKind === 'DatabaseSchemaQuery') {
                        return [200, databaseSchemaMock]
                    } else if (queryKind === 'RevenueAnalyticsMetricsQuery') {
                        return [200, revenueAnalyticsMetricsQueryMock]
                    } else if (queryKind === 'RevenueAnalyticsOverviewQuery') {
                        return [200, revenueAnalyticsOverviewMock]
                    } else if (queryKind === 'RevenueAnalyticsGrossRevenueQuery') {
                        return [200, revenueAnalyticsGrossRevenueQueryMock]
                    } else if (queryKind === 'RevenueAnalyticsMRRQuery') {
                        return [200, revenueAnalyticsMRRQueryMock]
                    } else if (queryKind === 'RevenueAnalyticsTopCustomersQuery') {
                        return [200, revenueAnalyticsTopCustomersMock]
                    }
                },
            },
        }),
    ],
}
export default meta

const PRODUCT_A_PROPERTY_FILTER: RevenueAnalyticsPropertyFilter = {
    key: 'product',
    operator: PropertyOperator.Exact,
    value: 'Product A',
    type: PropertyFilterType.RevenueAnalytics,
}

const PRODUCT_A_BREAKDOWN: RevenueAnalyticsBreakdown = {
    property: 'revenue_analytics_product.name',
    type: 'revenue_analytics',
}

export function RevenueAnalyticsDashboard(): JSX.Element {
    const { setTopCustomersDisplayMode, addBreakdown, setRevenueAnalyticsFilters } = useActions(revenueAnalyticsLogic)

    useEffect(() => {
        setTopCustomersDisplayMode('table')
        setRevenueAnalyticsFilters([PRODUCT_A_PROPERTY_FILTER])
        addBreakdown(PRODUCT_A_BREAKDOWN)
    }, [setTopCustomersDisplayMode, setRevenueAnalyticsFilters, addBreakdown])

    return <App />
}

export function RevenueAnalyticsDashboardSyncInProgress(): JSX.Element {
    const { setTopCustomersDisplayMode, addBreakdown, setRevenueAnalyticsFilters } = useActions(revenueAnalyticsLogic)

    useStorybookMocks({
        get: {
            '/api/environments/:team_id/external_data_sources/': () => {
                return [
                    200,
                    {
                        ...EMPTY_PAGINATED_RESPONSE,
                        results: [{ ...externalDataSourceResponseMock, status: 'Running', last_run_at: null }],
                    },
                ]
            },
        },
    })

    useEffect(() => {
        setTopCustomersDisplayMode('line')
        setRevenueAnalyticsFilters([PRODUCT_A_PROPERTY_FILTER])
        addBreakdown(PRODUCT_A_BREAKDOWN)
    }, [setTopCustomersDisplayMode, setRevenueAnalyticsFilters, addBreakdown])

    return <App />
}
