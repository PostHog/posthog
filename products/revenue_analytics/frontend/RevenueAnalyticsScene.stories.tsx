import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { router } from 'kea-router'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'

import databaseSchemaMock from './__mocks__/DatabaseSchemaQuery.json'
import revenueAnalyticsGrowthRateMock from './__mocks__/RevenueAnalyticsGrowthRateQuery.json'
import revenueAnalyticsOverviewMock from './__mocks__/RevenueAnalyticsOverviewQuery.json'
import revenueAnalyticsTopCustomersMock from './__mocks__/RevenueAnalyticsTopCustomersQuery.json'
import trendsQueryMock from './__mocks__/TrendsQuery.json'
import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

const meta: Meta = {
    title: 'Scenes-App/Revenue Analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        featureFlags: [FEATURE_FLAGS.REVENUE_ANALYTICS],
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query': (req) => {
                    const query = (req.body as any).query
                    const queryKind = query.kind

                    if (queryKind === 'DatabaseSchemaQuery') {
                        return [200, databaseSchemaMock]
                    } else if (queryKind === 'RevenueAnalyticsGrowthRateQuery') {
                        return [200, revenueAnalyticsGrowthRateMock]
                    } else if (queryKind === 'RevenueAnalyticsTopCustomersQuery') {
                        return [200, revenueAnalyticsTopCustomersMock]
                    } else if (queryKind === 'RevenueAnalyticsOverviewQuery') {
                        return [200, revenueAnalyticsOverviewMock]
                    } else if (queryKind === 'TrendsQuery') {
                        return [200, trendsQueryMock]
                    }
                },
            },
        }),
    ],
}
export default meta

export function RevenueAnalyticsDashboardOnboarding(): JSX.Element {
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/': (req) => {
                const query = (req.body as any).query
                const queryKind = query.kind

                if (queryKind === 'DatabaseSchemaQuery') {
                    return [200, { tables: {} }] // Empty schema, we don't care about this here
                }
            },
        },
    })

    // Open the revenue analytics dashboard page
    useEffect(() => router.actions.push(urls.revenueAnalytics()), [])

    return <App />
}

export function RevenueAnalyticsDashboardTableView(): JSX.Element {
    const { setGrowthRateDisplayMode, setTopCustomersDisplayMode } = useActions(revenueAnalyticsLogic)

    useEffect(() => {
        // Open the revenue analytics dashboard page
        router.actions.push(urls.revenueAnalytics())

        setGrowthRateDisplayMode('table')
        setTopCustomersDisplayMode('table')
    }, [setGrowthRateDisplayMode, setTopCustomersDisplayMode])

    useEffect(() => {
        // Open the revenue analytics dashboard page
        router.actions.push(urls.revenueAnalytics())
    }, [])

    return <App />
}

export function RevenueAnalyticsDashboardLineView(): JSX.Element {
    const { setGrowthRateDisplayMode, setTopCustomersDisplayMode } = useActions(revenueAnalyticsLogic)

    useEffect(() => {
        // Open the revenue analytics dashboard page
        router.actions.push(urls.revenueAnalytics())

        setGrowthRateDisplayMode('line')
        setTopCustomersDisplayMode('line')
    }, [setGrowthRateDisplayMode, setTopCustomersDisplayMode])

    return <App />
}

export const RevenueAnalyticsDashboardWithoutFeatureFlag: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.revenueAnalytics())
    }, [])

    return <App />
}
RevenueAnalyticsDashboardWithoutFeatureFlag.parameters = {
    ...meta.parameters,
    featureFlags: [],
}
