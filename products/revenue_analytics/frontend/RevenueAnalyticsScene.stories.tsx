import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'
import { EMPTY_PAGINATED_RESPONSE } from '~/mocks/handlers'
import { RevenueAnalyticsGroupBy } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator, RevenueAnalyticsPropertyFilter } from '~/types'

import databaseSchemaMock from './__mocks__/DatabaseSchemaQuery.json'
import revenueAnalyticsCustomerCountQueryMock from './__mocks__/RevenueAnalyticsCustomerCountQuery.json'
import revenueAnalyticsGrowthRateMock from './__mocks__/RevenueAnalyticsGrowthRateQuery.json'
import revenueAnalyticsRevenueQueryMock from './__mocks__/RevenueAnalyticsRevenueQuery.json'
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
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS, FEATURE_FLAGS.REVENUE_ANALYTICS_MRR],
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
                    } else if (queryKind === 'RevenueAnalyticsCustomerCountQuery') {
                        return [200, revenueAnalyticsCustomerCountQueryMock]
                    } else if (queryKind === 'RevenueAnalyticsGrowthRateQuery') {
                        return [200, revenueAnalyticsGrowthRateMock]
                    } else if (queryKind === 'RevenueAnalyticsTopCustomersQuery') {
                        return [200, revenueAnalyticsTopCustomersMock]
                    } else if (queryKind === 'RevenueAnalyticsOverviewQuery') {
                        return [200, revenueAnalyticsOverviewMock]
                    } else if (queryKind === 'RevenueAnalyticsRevenueQuery') {
                        return [200, revenueAnalyticsRevenueQueryMock]
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

export function RevenueAnalyticsDashboard(): JSX.Element {
    const { setGrowthRateDisplayMode, setTopCustomersDisplayMode, setGroupBy, setRevenueAnalyticsFilters } =
        useActions(revenueAnalyticsLogic)

    useEffect(() => {
        setGrowthRateDisplayMode('table')
        setTopCustomersDisplayMode('table')
        setRevenueAnalyticsFilters([PRODUCT_A_PROPERTY_FILTER])
        setGroupBy([RevenueAnalyticsGroupBy.PRODUCT])
    }, [setGrowthRateDisplayMode, setTopCustomersDisplayMode, setRevenueAnalyticsFilters, setGroupBy])

    return <App />
}

export function RevenueAnalyticsDashboardSyncInProgress(): JSX.Element {
    const { setGrowthRateDisplayMode, setTopCustomersDisplayMode, setGroupBy, setRevenueAnalyticsFilters } =
        useActions(revenueAnalyticsLogic)

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
        setGrowthRateDisplayMode('line')
        setTopCustomersDisplayMode('line')
        setRevenueAnalyticsFilters([PRODUCT_A_PROPERTY_FILTER])
        setGroupBy([RevenueAnalyticsGroupBy.PRODUCT])
    }, [setGrowthRateDisplayMode, setTopCustomersDisplayMode, setRevenueAnalyticsFilters, setGroupBy])

    return <App />
}

export const RevenueAnalyticsDashboardWithoutFeatureFlag: StoryObj<typeof meta> = {
    parameters: { featureFlags: [] },
}
